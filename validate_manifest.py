#!/usr/bin/env python3
"""Validate content_manifest.json against what Amphora assumes at runtime.

Every rule here corresponds to a failure mode that only shows up on a device,
usually after an automated pin bump:

* a component the engine resolves by name goes missing, or is misspelled (the
  app skips keys it does not recognise, so a typo would look like a clean parse
  and fail later as a missing component);
* a component without a pinned SHA-256 downloads unverified;
* a non-WCP component without a remoteUrl throws in RemoteUrlResolver;
* the same file is pinned in both components[] and runtimeAssets[]. This is how
  graphics_driver/wrapper.tzst used to be pinned, and the two halves drifted
  apart. Its components.turnip copy has since been removed; the check stays so
  the arrangement cannot come back;
* a WCP pin whose version / verName / verCode / contentType disagree (install
  path is contents/<type>/<verName>-<verCode>/). With VALIDATE_FETCH_WCP=1, also
  that the published .wcp profile.json matches those fields and the sha/size pin.

Usage: python3 validate_manifest.py [content_manifest.json]
       VALIDATE_FETCH_WCP=1 python3 validate_manifest.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

SHA256 = re.compile(r"^[0-9a-f]{64}$")
KINDS = {"WCP", "ARCHIVE", "ROOTFS"}
COMPRESSIONS = {"zstd", "xz"}

# Amphora's ContentComponent enum. The app skips component keys it does not
# recognise so that adding one here cannot brick installed builds -- which means
# a misspelled key is silent on the device and has to be caught here instead.
KNOWN_COMPONENTS = {"rootfs", "wine", "box64", "dxvk", "vkd3d", "dxvk_sarek"}

class Report:
    def __init__(self) -> None:
        self.errors: list[str] = []

    def check(self, ok: bool, message: str) -> bool:
        if not ok:
            self.errors.append(message)
        return ok


def validate_component(report: Report, name: str, entry: dict) -> None:
    where = f"components.{name}"

    asset_path = entry.get("assetPath")
    report.check(bool(asset_path), f"{where}: assetPath is required")

    sha = entry.get("sha256")
    report.check(
        isinstance(sha, str) and bool(SHA256.match(sha)),
        f"{where}: sha256 must be 64 lowercase hex chars, got {sha!r}",
    )

    report.check(
        bool(entry.get("version")),
        f"{where}: version is required (it is encoded into the install path)",
    )

    kind = entry.get("kind")
    report.check(kind in KINDS, f"{where}: kind must be one of {sorted(KINDS)}, got {kind!r}")

    compression = entry.get("compression")
    if compression is not None:
        report.check(
            compression in COMPRESSIONS,
            f"{where}: compression must be one of {sorted(COMPRESSIONS)}, got {compression!r}",
        )

    url = entry.get("remoteUrl")
    if url is None:
        # RemoteUrlResolver only knows how to look a filename up in the WCP
        # catalog; anything else needs an explicit URL.
        if report.check(
            kind == "WCP",
            f"{where}: remoteUrl is required for kind={kind} "
            f"(only WCP entries resolve through wcpCatalogUrl)",
        ):
            report.check(
                bool(entry.get("contentType")) and bool(entry.get("verName")),
                f"{where}: a WCP entry without remoteUrl needs contentType + verName "
                f"to compute its install dir",
            )
    else:
        report.check(
            isinstance(url, str) and url.startswith("https://"),
            f"{where}: remoteUrl must be https, got {url!r}",
        )

    size = entry.get("size")
    report.check(
        isinstance(size, int) and not isinstance(size, bool) and size > 0,
        f"{where}: size is required and must be a positive integer, got {size!r}",
    )

    if kind == "WCP":
        validate_wcp_identity(report, where, entry)


def validate_wcp_identity(report: Report, where: str, entry: dict) -> None:
    """WCP install path is contents/<type>/<verName>-<verCode>/ — pin fields must agree.

    Amphora's isInstalled / reconcileToPin look up that exact directory. A pin with
    verCode=0 while profile.json says versionCode=1 looks permanently "Update needed"
    even though the package is installed.
    """
    content_type = entry.get("contentType")
    ver_name = entry.get("verName")
    ver_code = entry.get("verCode")
    version = entry.get("version")

    report.check(
        isinstance(content_type, str) and bool(content_type),
        f"{where}: WCP contentType is required",
    )
    report.check(
        isinstance(ver_name, str) and bool(ver_name),
        f"{where}: WCP verName is required",
    )
    report.check(
        isinstance(ver_code, int) and not isinstance(ver_code, bool) and ver_code >= 0,
        f"{where}: WCP verCode must be a non-negative int, got {ver_code!r}",
    )
    if (
        isinstance(content_type, str)
        and isinstance(ver_name, str)
        and isinstance(ver_code, int)
        and not isinstance(ver_code, bool)
    ):
        expected = f"{content_type}-{ver_name}-{ver_code}"
        report.check(
            version == expected,
            f"{where}: version must equal contentType-verName-verCode "
            f"({expected!r}), got {version!r}",
        )


def read_wcp_profile(archive: Path) -> dict:
    """Extract profile.json from a zstd/xz/plain tar .wcp."""
    import io
    import tarfile

    def profile_from_tar(tar: tarfile.TarFile) -> dict:
        member = next(
            (m for m in tar.getmembers() if m.name.endswith("profile.json")),
            None,
        )
        if member is None:
            raise ValueError(f"{archive}: no profile.json")
        raw = tar.extractfile(member)
        if raw is None:
            raise ValueError(f"{archive}: cannot read profile.json")
        return json.loads(raw.read().decode("utf-8"))

    # Prefer stdlib modes when available (xz / uncompressed).
    for mode in ("r:xz", "r:"):
        try:
            with tarfile.open(archive, mode) as tar:
                return profile_from_tar(tar)
        except (tarfile.ReadError, tarfile.CompressionError):
            continue

    # Amphora / WinNative WCPs are typically zstd tar; Python needs the
    # zstandard package (stdlib has no r:zst).
    try:
        import zstandard
    except ImportError as failure:
        raise ValueError(
            f"{archive}: zstd WCP requires the 'zstandard' package"
        ) from failure
    with archive.open("rb") as compressed:
        with zstandard.ZstdDecompressor().stream_reader(compressed) as reader:
            plain = reader.read()
    with tarfile.open(fileobj=io.BytesIO(plain), mode="r:") as tar:
        return profile_from_tar(tar)



def validate_wcp_profiles_match_pins(
    report: Report,
    components: dict,
    *,
    work_dir: Path,
) -> None:
    """Optional network check: download each WCP and assert pin ≡ profile.json.

    Enabled with VALIDATE_FETCH_WCP=1. Catches rebuilds that bump sha/size but
    leave a stale verCode / verName in content_manifest.
    """
    import hashlib
    import urllib.request

    work_dir.mkdir(parents=True, exist_ok=True)
    for name, entry in components.items():
        if not isinstance(entry, dict) or entry.get("kind") != "WCP":
            continue
        url = entry.get("remoteUrl")
        if not isinstance(url, str) or not url.startswith("https://"):
            continue
        where = f"components.{name}"
        dest = work_dir / Path(str(entry.get("assetPath") or f"{name}.wcp")).name
        try:
            urllib.request.urlretrieve(url, dest)
        except Exception as failure:  # noqa: BLE001 — surface as report error
            report.check(False, f"{where}: failed to fetch {url}: {failure}")
            continue

        digest = hashlib.sha256(dest.read_bytes()).hexdigest()
        report.check(
            digest == entry.get("sha256"),
            f"{where}: downloaded sha256={digest} != pin {entry.get('sha256')}",
        )
        report.check(
            dest.stat().st_size == entry.get("size"),
            f"{where}: downloaded size={dest.stat().st_size} != pin {entry.get('size')}",
        )

        try:
            profile = read_wcp_profile(dest)
        except Exception as failure:  # noqa: BLE001
            report.check(False, f"{where}: cannot read profile.json: {failure}")
            continue

        report.check(
            str(profile.get("type", "")).lower() == str(entry.get("contentType", "")).lower(),
            f"{where}: contentType {entry.get('contentType')!r} != "
            f"profile.type {profile.get('type')!r}",
        )
        report.check(
            profile.get("versionName") == entry.get("verName"),
            f"{where}: verName {entry.get('verName')!r} != "
            f"profile.versionName {profile.get('versionName')!r}",
        )
        report.check(
            int(profile.get("versionCode", -1)) == int(entry.get("verCode", -2)),
            f"{where}: verCode {entry.get('verCode')!r} != "
            f"profile.versionCode {profile.get('versionCode')!r}",
        )


def validate_runtime_asset(report: Report, index: int, entry: dict) -> None:
    where = f"runtimeAssets[{index}]"

    report.check(bool(entry.get("assetPath")), f"{where}: assetPath is required")

    sha = entry.get("sha256")
    report.check(
        isinstance(sha, str) and bool(SHA256.match(sha)),
        f"{where}: sha256 must be 64 lowercase hex chars, got {sha!r}",
    )

    url = entry.get("remoteUrl")
    report.check(
        isinstance(url, str) and url.startswith("https://"),
        f"{where}: remoteUrl must be https, got {url!r}",
    )

    size = entry.get("size")
    report.check(
        isinstance(size, int) and not isinstance(size, bool) and size > 0,
        f"{where}: size is required and must be a positive integer, got {size!r}",
    )


def validate_cross_section(report: Report, components: dict, runtime_assets: list) -> None:
    """An asset must have exactly one owner/provisioning path."""
    runtime_paths = {
        entry.get("assetPath") for entry in runtime_assets if isinstance(entry, dict)
    }
    for name, entry in components.items():
        asset_path = entry.get("assetPath")
        report.check(
            asset_path not in runtime_paths,
            f"components.{name} and runtimeAssets[] both pin {asset_path}; "
            "an asset must be provisioned by exactly one section",
        )


def main(argv: list[str]) -> int:
    path = Path(argv[1]) if len(argv) > 1 else Path(__file__).with_name("content_manifest.json")
    report = Report()

    try:
        manifest = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError) as failure:
        print(f"{path}: {failure}", file=sys.stderr)
        return 1

    report.check(manifest.get("version") == 1, "top-level version must be 1")

    catalog_url = manifest.get("wcpCatalogUrl")
    report.check(
        isinstance(catalog_url, str) and catalog_url.startswith("https://"),
        f"wcpCatalogUrl must be https, got {catalog_url!r}",
    )

    components = manifest.get("components")
    if report.check(isinstance(components, dict) and bool(components),
                    "components must be a non-empty object"):
        report.check(
            set(components) == KNOWN_COMPONENTS,
            f"components must be exactly {sorted(KNOWN_COMPONENTS)}; "
            f"unexpected={sorted(set(components) - KNOWN_COMPONENTS)} "
            f"missing={sorted(KNOWN_COMPONENTS - set(components))}",
        )
        for name, entry in components.items():
            if report.check(isinstance(entry, dict), f"components.{name} must be an object"):
                validate_component(report, name, entry)

    runtime_assets = manifest.get("runtimeAssets", [])
    if report.check(isinstance(runtime_assets, list), "runtimeAssets must be a list"):
        for index, entry in enumerate(runtime_assets):
            if report.check(isinstance(entry, dict), f"runtimeAssets[{index}] must be an object"):
                validate_runtime_asset(report, index, entry)

        duplicates = [
            path_ for path_, count in Counter(
                entry.get("assetPath") for entry in runtime_assets if isinstance(entry, dict)
            ).items() if count > 1
        ]
        report.check(
            not duplicates,
            f"duplicate runtimeAssets assetPath (the provisioner would race): {duplicates}",
        )

    if isinstance(components, dict) and isinstance(runtime_assets, list):
        validate_cross_section(report, components, runtime_assets)

    if isinstance(components, dict) and os.environ.get("VALIDATE_FETCH_WCP") == "1":
        validate_wcp_profiles_match_pins(
            report,
            components,
            work_dir=path.parent / ".validate-wcp-cache",
        )

    if report.errors:
        print(f"{path}: {len(report.errors)} problem(s)", file=sys.stderr)
        for error in report.errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print(
        f"{path}: OK "
        f"({len(components)} components, {len(runtime_assets)} runtime assets)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
