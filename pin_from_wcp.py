#!/usr/bin/env python3
"""Extract pin fields from a built .wcp so CI can bump content_manifest idempotently.

Prints shell-friendly assignments for bump-manifest.sh:

  VER_NAME=11.0-amphora-x86_64
  VER_CODE=1
  CONTENT_TYPE=Proton
  SHA256=...
  SIZE=...

Usage:
  python3 pin_from_wcp.py path/to/Proton-11.0-amphora-x86_64.wcp
  eval "$(python3 pin_from_wcp.py ./out.wcp)" && \\
    COMPONENT=wine ASSET_PATH=$ASSET_PATH ./bump-manifest.sh
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
import tarfile
from pathlib import Path


def read_profile(archive: Path) -> dict:
    for mode in ("r:xz", "r:"):
        try:
            with tarfile.open(archive, mode) as tar:
                return _profile_from_tar(tar, archive)
        except (tarfile.ReadError, tarfile.CompressionError):
            continue

    try:
        import zstandard
    except ImportError as failure:
        raise SystemExit(
            f"{archive}: zstd WCP requires the 'zstandard' package"
        ) from failure
    with archive.open("rb") as compressed:
        with zstandard.ZstdDecompressor().stream_reader(compressed) as reader:
            plain = reader.read()
    with tarfile.open(fileobj=io.BytesIO(plain), mode="r:") as tar:
        return _profile_from_tar(tar, archive)


def _profile_from_tar(tar: tarfile.TarFile, archive: Path) -> dict:
    member = next(
        (m for m in tar.getmembers() if m.name.endswith("profile.json")),
        None,
    )
    if member is None:
        raise SystemExit(f"{archive}: no profile.json")
    raw = tar.extractfile(member)
    if raw is None:
        raise SystemExit(f"{archive}: cannot read profile.json")
    return json.loads(raw.read().decode("utf-8"))


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print(f"usage: {argv[0]} <package.wcp>", file=sys.stderr)
        return 2
    path = Path(argv[1])
    if not path.is_file():
        print(f"{path}: not a file", file=sys.stderr)
        return 1

    profile = read_profile(path)
    data = path.read_bytes()
    print(f"VER_NAME={profile['versionName']}")
    print(f"VER_CODE={int(profile['versionCode'])}")
    print(f"CONTENT_TYPE={profile['type']}")
    print(f"SHA256={hashlib.sha256(data).hexdigest()}")
    print(f"SIZE={len(data)}")
    print(f"ASSET_PATH={path.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
