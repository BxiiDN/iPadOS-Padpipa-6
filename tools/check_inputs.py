#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""What the pipa kernel step needs that the pinned public trees do NOT provide.

Reads [kernel] archives of UniXNU-pipa's board.toml and resolves every builder script in UniXNU/scripts or
UniXNU-pipa/scripts, then lists the out-of-tree inputs the UniXNU-pipa README and the builders name. Exit 1 if any is
missing, so a CI log or a local run says exactly why `unixnu build kernel` cannot complete.

    python3 tools/check_inputs.py --work work [--tree work/UniXNU/out/pipa/tree] [--json report.json]
"""
from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
import tomllib

# Out-of-tree inputs (UniXNU-pipa cdb3d627 README "Inputs kept outside Git" and the builders' require() calls).
EXTERNAL = [
    ("build/storage-abi/interface-audit.json",
     "README: copied from out/tb128fu/tree. Public generator: scripts/audit-storage-interface.py (needs refer/IOStorageFamily)",
     "generate"),
    ("build/verified-root-os/trusted-key.bin",
     "the 395-byte VROOTKEY anchor of the owner RSA-3072 key; README: from out/tb128fu/tree (another owner's key)",
     "owner"),
    ("build/xnu/ios-obj/EXPORT_HDRS/libsa", "README: an empty directory", "create"),
    ("<PIPA_DISPLAY_REFERENCE>/build/xnu-prelink/native-owner-mobile-graphics-candidate.macho",
     "build-gop-legacy-display.py: UniXNU-qemu's built tree", "reference"),
    ("<PIPA_DISPLAY_REFERENCE>/build/darwinboot-owner-hvf-mobile-graphics-legacy-class/gdb-stop.json",
     "build-gop-legacy-display.py: a DarwinBoot run under macOS Hypervisor.framework (needs an Apple-silicon Mac with HVF)",
     "reference"),
    (".cache/firmware/gpu/a650_gmu.bin", "manifest/firmware.toml", "firmware"),
    (".cache/firmware/gpu/a650_zap.elf", "manifest/firmware.toml", "firmware"),
    (".cache/firmware/linux-firmware/a650_sqe.fw", "manifest/firmware.toml", "firmware"),
    (".cache/firmware/touch/novatek_nt36532_m82_fw_tm.bin", "manifest/firmware.toml", "firmware"),
]


def resolve(script: str, bases: list[str]) -> str | None:
    for b in bases:
        p = os.path.join(b, "scripts", script)
        if os.path.isfile(p):
            return p
    return None


def check(work: str, tree: str | None, board_path: str | None = None) -> dict:
    board_path = board_path or os.path.join(work, "UniXNU-pipa", "board.toml")
    with open(board_path, "rb") as f:
        board = tomllib.load(f)
    bases = [os.path.join(work, "UniXNU"), os.path.join(work, "UniXNU-pipa")]
    if tree:
        bases.insert(0, tree)
    # build-arm-driver.py only accepts components of UniXNU's components.toml (ids, legacy names, aliases).
    known: set[str] = set()
    comp = os.path.join(work, "UniXNU", "components.toml")
    if os.path.isfile(comp):
        with open(comp, "rb") as f:
            for c in tomllib.load(f).get("component", []):
                known |= {c.get("id", ""), c.get("legacy_name", "")} | set(c.get("aliases", []))
    archives = []
    for entry in board.get("kernel", {}).get("archives", []):
        argv = shlex.split(entry)
        script = argv[0]
        found = resolve(script, bases)
        rec = {"builder": entry, "script": script, "found": found}
        if found and script == "build-arm-driver.py" and known and len(argv) > 1 and argv[1] not in known:
            rec["found"] = None
            rec["why"] = f"component {argv[1]!r} is not in UniXNU components.toml"
        archives.append(rec)
    ref = os.environ.get("PIPA_DISPLAY_REFERENCE", "")
    external = []
    for rel, why, kind in EXTERNAL:
        if rel.startswith("<PIPA_DISPLAY_REFERENCE>"):
            path = rel.replace("<PIPA_DISPLAY_REFERENCE>", ref) if ref else None
        elif rel.startswith(".cache/"):
            path = os.path.join(work, "UniXNU-pipa", rel)
        else:
            path = os.path.join(tree, rel) if tree else None
        present = bool(path and os.path.exists(path))
        external.append({"input": rel, "why": why, "kind": kind, "present": present})
    missing = [a["builder"] for a in archives if not a["found"]] + [e["input"] for e in external if not e["present"]]
    return {"archives": archives, "external": external, "missing": missing}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", required=True)
    ap.add_argument("--tree")
    ap.add_argument("--board")
    ap.add_argument("--json")
    args = ap.parse_args(argv)
    res = check(args.work, args.tree, args.board)
    for a in res["archives"]:
        print(f"{'ok     ' if a['found'] else 'MISSING'}  builder {a['builder']}{'  (' + a['why'] + ')' if a.get('why') else ''}")
    for e in res["external"]:
        print(f"{'ok     ' if e['present'] else 'MISSING'}  [{e['kind']}] {e['input']}  ({e['why']})")
    if args.json:
        os.makedirs(os.path.dirname(os.path.abspath(args.json)), exist_ok=True)
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=2)
            f.write("\n")
    print(f"{'FAIL' if res['missing'] else 'PASS'}  kernel inputs: {len(res['missing'])} missing")
    return 1 if res["missing"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
