#!/usr/bin/env python3
"""Validate content_manifest.json against what Amphora assumes at runtime.

Every rule here corresponds to a failure mode that only shows up on a device,
usually after an automated pin bump:

* a component without a pinned SHA-256 downloads unverified;
* a non-WCP component without a remoteUrl throws in RemoteUrlResolver;
* graphics_driver/wrapper.tzst is pinned twice -- once as components.turnip and
  once in runtimeAssets[] -- and the two halves have drifted apart before
  (amphora-dev/imagefs "sync runtimeAssets when bumping turnip/wrapper pin").

Usage: python3 validate_manifest.py [content_manifest.json]
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

SHA256 = re.compile(r"^[0-9a-f]{64}$")
KINDS = {"WCP", "ARCHIVE", "ROOTFS"}
COMPRESSIONS = {"zstd", "xz"}

# Fields that must agree when the same assetPath is pinned in both sections.
SHARED_FIELDS = ("sha256", "remoteUrl", "size")


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
    if size is not None:
        report.check(
            isinstance(size, int) and size > 0,
            f"{where}: size must be a positive integer, got {size!r}",
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
    if size is not None:
        report.check(
            isinstance(size, int) and size > 0,
            f"{where}: size must be a positive integer, got {size!r}",
        )


def validate_cross_section(report: Report, components: dict, runtime_assets: list) -> None:
    """A file pinned in both sections must be pinned identically."""
    by_path = {entry.get("assetPath"): entry for entry in runtime_assets}
    for name, entry in components.items():
        twin = by_path.get(entry.get("assetPath"))
        if twin is None:
            continue
        for field in SHARED_FIELDS:
            report.check(
                entry.get(field) == twin.get(field),
                f"components.{name} and runtimeAssets[] both pin "
                f"{entry.get('assetPath')} but disagree on {field}: "
                f"{entry.get(field)!r} != {twin.get(field)!r}",
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
