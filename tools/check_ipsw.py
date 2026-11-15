#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Refuse an IPSW that is not the pinned one, before any build step reads it.

Checks, from the IPSW itself (a zip): BuildManifest.plist ProductVersion / ProductBuildVersion, that the board's product
(iPad7,1) is in SupportedProductTypes, and the SHA-256 of every member pinned in board.toml [ipsw.sha256] (the OS and
SystemOS disk images that become the root). A local file is hashed fully; nothing is substituted silently.

    python3 tools/check_ipsw.py --board work/UniXNU-pipa/board.toml --ipsw C:/ipsw/iPad_Pro_HFR_17.7.11_21H461_Restore.ipsw
For the official URL, `unixnu ipsw fetch` reads members by HTTP range; run this on a downloaded copy for the full check.
"""
from __future__ import annotations

import argparse
import hashlib
import plistlib
import sys
import tomllib
import zipfile


def check(ipsw_path: str, board: dict, *, hash_members: bool = True) -> list[str]:
    pin = board["ipsw"]
    errors: list[str] = []
    try:
        z = zipfile.ZipFile(ipsw_path)
    except (zipfile.BadZipFile, OSError) as e:
        return [f"not a readable IPSW (zip): {e}"]
    with z:
        try:
            manifest = plistlib.loads(z.read("BuildManifest.plist"))
        except KeyError:
            return ["no BuildManifest.plist in the IPSW"]
        if manifest.get("ProductVersion") != pin["version"]:
            errors.append(f"ProductVersion {manifest.get('ProductVersion')} != pinned {pin['version']}")
        if manifest.get("ProductBuildVersion") != pin["build"]:
            errors.append(f"ProductBuildVersion {manifest.get('ProductBuildVersion')} != pinned {pin['build']}")
        if pin["product"] not in manifest.get("SupportedProductTypes", []):
            errors.append(f"{pin['product']} not in SupportedProductTypes {manifest.get('SupportedProductTypes')}")
        idents = [i for i in manifest.get("BuildIdentities", [])
                  if i.get("Info", {}).get("DeviceClass", "").lower() == pin.get("device_class", "").lower()]
        if pin.get("device_class") and not idents:
            errors.append(f"no build identity for device class {pin['device_class']}")
        names = set(z.namelist())
        for member, want in pin.get("sha256", {}).items():
            if member not in names:
                errors.append(f"pinned member {member} missing from the IPSW")
                continue
            if not hash_members:
                continue
            h = hashlib.sha256()
            with z.open(member) as f:
                for chunk in iter(lambda: f.read(1 << 22), b""):
                    h.update(chunk)
            if h.hexdigest() != want:
                errors.append(f"{member}: sha256 {h.hexdigest()} != pinned {want}")
    return errors


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--board", required=True)
    ap.add_argument("--ipsw", required=True)
    ap.add_argument("--no-hash", action="store_true", help="identity only (quick); the build still needs the full check")
    args = ap.parse_args(argv)
    with open(args.board, "rb") as f:
        board = tomllib.load(f)
    errors = check(args.ipsw, board, hash_members=not args.no_hash)
    for e in errors:
        print(f"FAIL  {e}")
    pin = board["ipsw"]
    print(f"{'FAIL' if errors else 'PASS'}  IPSW {pin['product']} {pin['version']} ({pin['build']})"
          f"{'' if not args.no_hash else ' (members not hashed)'}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
