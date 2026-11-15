#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Board configuration gate: the generated board.toml describes a Xiaomi Pad 6 and THIS unit.

Fails on: another board/SoC, an IPSW other than the pinned iPadOS 17.7.11 (21H461, iPad7,1), a cpu_regs list that is
not pipa's eight MPIDRs, a dram_size that does not end at the unit's last bank (e.g. the 16 GB reference's 0x980000000
on an 8 GB unit), owned memory over dram, kernel arguments over DarwinBoot's 1000 bytes, or a userdata window that
does not match the measured GPT (or is missing the NOT-FOR-FLASH marker when the GPT is not measured).

    python3 tools/checks/check_board.py --board work/UniXNU-pipa/board.toml --facts device/pipa-8g256/unit-facts.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import unitfacts  # noqa: E402
from pipa_board import DARWINBOOT_CMDLINE_LIMIT, NOT_FOR_FLASH  # noqa: E402

PIN = {"name": "pipa", "soc": "SM8250", "product": "iPad7,1", "version": "17.7.11", "build": "21H461",
       "chip_id": 0x8011, "cpu_regs": "0,0x100,0x200,0x300,0x400,0x500,0x600,0x700"}


def check(text: str, facts: dict) -> dict:
    errors, warnings = [], []
    b = tomllib.loads(text)
    if b["board"].get("name") != PIN["name"] or b["board"].get("soc") != PIN["soc"]:
        errors.append(f"board is {b['board'].get('name')}/{b['board'].get('soc')}, not pipa/SM8250")
    ipsw = b.get("ipsw", {})
    for k in ("product", "version", "build", "chip_id"):
        if ipsw.get(k) != PIN[k]:
            errors.append(f"[ipsw] {k} = {ipsw.get(k)!r}, pinned {PIN[k]!r}")
    if not ipsw.get("sha256"):
        errors.append("[ipsw.sha256] digests missing: the root disk images would not be pinned")
    if not ipsw.get("url", "").startswith("https://updates.cdn-apple.com/"):
        errors.append("[ipsw] url is not Apple's update CDN")
    adt = b.get("payload", {}).get("adt", {})
    if adt.get("cpu_regs") != PIN["cpu_regs"]:
        errors.append(f"[payload.adt] cpu_regs {adt.get('cpu_regs')!r} != pipa's 8 cores {PIN['cpu_regs']!r}")
    try:
        want = unitfacts.dram_size(facts)
        got = int(b["payload"]["dram_size"], 0)
        if got != want:
            errors.append(f"[payload] dram_size {got:#x} != unit's {want:#x} (banks {facts['memory']['banks']})")
        owned = int(adt["owned_memory_size"], 0)
        if owned > got:
            errors.append(f"owned_memory_size {owned:#x} > dram_size {got:#x}")
    except (ValueError, KeyError) as e:
        errors.append(f"memory: {e}")
    args = " ".join(b["payload"].get("kernel_args", []))
    if len(args.encode()) > DARWINBOOT_CMDLINE_LIMIT:
        errors.append(f"kernel_args {len(args.encode())} bytes > {DARWINBOOT_CMDLINE_LIMIT}")
    elif len(args.encode()) > DARWINBOOT_CMDLINE_LIMIT - 40:
        warnings.append(f"kernel_args {len(args.encode())} bytes: under 40 bytes left before DarwinBoot's limit")
    ud = b.get("userdata", {})
    measured = not unitfacts.problems(facts, need_storage=True)
    flash_allowed = False
    if measured:
        m = facts["storage"]["userdata"]
        if (ud.get("first_lba"), ud.get("last_lba")) != (int(m["first_lba"], 0), int(m["last_lba"], 0)):
            errors.append(f"[userdata] {ud.get('first_lba'):#x}..{ud.get('last_lba'):#x} != measured "
                          f"{m['first_lba']}..{m['last_lba']}")
        else:
            flash_allowed = True
        if ud.get("lba_bytes") != facts["storage"]["lba_bytes"]:
            errors.append(f"[userdata] lba_bytes {ud.get('lba_bytes')} != measured {facts['storage']['lba_bytes']}")
    elif NOT_FOR_FLASH not in text:
        errors.append("userdata window is not measured and board.toml lacks the NOT-FOR-FLASH marker")
    if adt.get("unique_chip_id") != "required":
        errors.append("[payload.adt] unique_chip_id must stay 'required' (the platform seed is never stored in Git)")
    return {"errors": errors, "warnings": warnings, "flash_allowed": flash_allowed,
            "kernel_args_bytes": len(args.encode())}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--board", required=True)
    ap.add_argument("--facts", required=True)
    ap.add_argument("--json")
    args = ap.parse_args(argv)
    with open(args.board, encoding="utf-8") as f:
        text = f.read()
    res = check(text, unitfacts.load(args.facts))
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=2)
            f.write("\n")
    for w in res["warnings"]:
        print(f"WARN  {w}")
    for e in res["errors"]:
        print(f"FAIL  {e}")
    print(f"{'FAIL' if res['errors'] else 'PASS'}  board {args.board} (flash allowed: {res['flash_allowed']})")
    return 1 if res["errors"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
