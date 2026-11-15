#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Firmware gate: the proprietary images the build needs are the expected ones, and none of them is in Git.

manifest/firmware.toml lists every image with its origin and SHA-256. "UNMEASURED" means the digest has not been
pinned yet: the check warns and prints the digest it sees, so it can be pinned after the owner confirms the source
(their own tablet's partitions, or linux-firmware for files that ship there).

    python3 tools/checks/check_firmware.py --manifest manifest/firmware.toml --cache .cache/firmware [--stage gpu]
    python3 tools/checks/check_firmware.py --manifest manifest/firmware.toml --scan-repo .     # no blobs in Git
"""
from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import subprocess
import sys
import tomllib

BLOB_PATTERNS = ["*.mbn", "*.mdt", "*.b[0-9][0-9]", "a6[0-9]0_*", "*.fw", "bdwlan*", "amss*", "regdb.bin", "m3.bin",
                 "*_fw_*.bin", "novatek_*.bin", "aw882xx*.bin", "*.ipsw", "*.dmg", "*.img", "*.fd"]
ALLOWED_IN_GIT = {"tests/fixtures/"}  # synthetic fixtures only


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def check_cache(manifest: dict, cache: str, stage: str | None) -> dict:
    errors, warnings, seen = [], [], []
    for fw in manifest.get("firmware", []):
        if stage and stage not in fw.get("stages", []):
            continue
        path = os.path.join(cache, fw["cache_path"])
        entry = {"name": fw["name"], "path": path, "expected": fw["sha256"]}
        if not os.path.isfile(path):
            (errors if fw.get("required", True) else warnings).append(f"{fw['name']}: missing at {path}")
            entry["state"] = "missing"
        else:
            got = sha256(path)
            entry["sha256"] = got
            entry["bytes"] = os.path.getsize(path)
            if fw["sha256"] == "UNMEASURED":
                warnings.append(f"{fw['name']}: digest not pinned yet, seen {got}")
                entry["state"] = "unpinned"
            elif got != fw["sha256"].lower():
                errors.append(f"{fw['name']}: sha256 {got} != pinned {fw['sha256']}")
                entry["state"] = "mismatch"
            else:
                entry["state"] = "ok"
            if fw.get("min_bytes") and entry["bytes"] < fw["min_bytes"]:
                errors.append(f"{fw['name']}: {entry['bytes']} bytes < {fw['min_bytes']}")
        seen.append(entry)
    return {"errors": errors, "warnings": warnings, "firmware": seen}


def tracked_files(repo: str) -> list[str]:
    try:
        out = subprocess.run(["git", "-C", repo, "ls-files"], capture_output=True, text=True, check=True).stdout
        return [p for p in out.splitlines() if p]
    except (subprocess.CalledProcessError, FileNotFoundError):
        files = []
        for root, dirs, names in os.walk(repo):
            dirs[:] = [d for d in dirs if d not in (".git", "work", ".cache", "out", "build")]
            files += [os.path.relpath(os.path.join(root, n), repo) for n in names]
        return files


def scan_repo(repo: str, manifest: dict) -> dict:
    names = {fw["name"] for fw in manifest.get("firmware", [])}
    errors = []
    for rel in tracked_files(repo):
        rel = rel.replace("\\", "/")
        if any(rel.startswith(a) for a in ALLOWED_IN_GIT):
            continue
        base = os.path.basename(rel)
        if base in names or any(fnmatch.fnmatch(base, p) for p in BLOB_PATTERNS):
            errors.append(f"{rel}: looks like a proprietary image or an Apple file; keep it in .cache/, not in Git")
    return {"errors": errors, "warnings": []}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", required=True)
    ap.add_argument("--cache")
    ap.add_argument("--stage")
    ap.add_argument("--scan-repo")
    ap.add_argument("--json")
    args = ap.parse_args(argv)
    with open(args.manifest, "rb") as f:
        manifest = tomllib.load(f)
    res = {"errors": [], "warnings": []}
    if args.cache:
        r = check_cache(manifest, args.cache, args.stage)
        res["errors"] += r["errors"]
        res["warnings"] += r["warnings"]
        res["firmware"] = r["firmware"]
    if args.scan_repo:
        r = scan_repo(args.scan_repo, manifest)
        res["errors"] += r["errors"]
    if not args.cache and not args.scan_repo:
        print("check_firmware: give --cache and/or --scan-repo", file=sys.stderr)
        return 2
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=2)
            f.write("\n")
    for w in res["warnings"]:
        print(f"WARN  {w}")
    for e in res["errors"]:
        print(f"FAIL  {e}")
    print(f"{'FAIL' if res['errors'] else 'PASS'}  firmware ({len(manifest.get('firmware', []))} entries in manifest)")
    return 1 if res["errors"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
