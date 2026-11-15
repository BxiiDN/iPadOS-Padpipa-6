#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Memory-map consistency for pipa: UEFI descriptors, device-tree carve-outs, DRAM banks, the ABL load window and the
range DarwinBoot gives XNU must not collide.

Inputs
  --memmap   uefi-pipa Platforms/Xiaomi/pipaPkg/Library/MemoryMapLib/MemoryMapLib.c (the firmware's fixed descriptors)
  --dtb      the DTB handed to the firmware (uefi-pipa Resources/DTBs/pipa.dtb)
  --facts    unit facts (memory banks of THIS tablet); default: the DTB's /memory
  --board    the generated board.toml (owned_memory_size, payload size)
  --firmware-top-reserve  bytes the firmware allocates at the top of the highest bank before DarwinBoot runs
             (unknown until the UEFI log of the unit is read; default 256 MiB, deliberately pessimistic)

Errors (exit 1)
  * two UEFI DRAM descriptors overlap, or one is not page aligned, or lies outside the DRAM banks
  * a device-tree no-map carve-out is not covered by a reserved UEFI descriptor (the firmware could hand it out)
  * an MMIO descriptor lies inside DRAM
  * the boot image (kernel + ramdisk) cannot fit the ABL load window
  * no free run holds owned_memory_size
Warnings
  * the predicted XNU window leaves less than 128 MiB above it
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tomllib

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import fdt as _fdt  # noqa: E402
import unitfacts  # noqa: E402

PAGE = 0x1000
ABL_WINDOW = ("Kernel", 0xA0000000, 0x10000000)  # MemoryMapLib.c: where ABL loads a boot image's kernel and ramdisk
DESC_RE = re.compile(
    r'\{\s*"(?P<name>[^"]+)"\s*,\s*(?P<base>0x[0-9A-Fa-f]+)\s*,\s*(?P<size>0x[0-9A-Fa-f]+)\s*,\s*(?P<hob>\w+)\s*,'
    r'\s*(?P<res>\w+)\s*,\s*(?P<attr>\w+)\s*,\s*(?P<mem>\w+)\s*,\s*(?P<arm>\w+)\s*\}')


def parse_memmap(text: str) -> list[dict]:
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    out = []
    for m in DESC_RE.finditer(text):
        d = m.groupdict()
        out.append({"name": d["name"], "base": int(d["base"], 16), "size": int(d["size"], 16), "hob": d["hob"],
                    "res": d["res"], "mem": d["mem"], "mmio": d["res"] == "MMAP_IO"})
    return out


def overlaps(a0, a1, b0, b1) -> bool:
    return a0 < b1 and b0 < a1


def subtract(runs: list[tuple[int, int]], cut: tuple[int, int]) -> list[tuple[int, int]]:
    c0, c1 = cut
    out = []
    for r0, r1 in runs:
        if c1 <= r0 or c0 >= r1:
            out.append((r0, r1))
            continue
        if r0 < c0:
            out.append((r0, c0))
        if c1 < r1:
            out.append((c1, r1))
    return out


def check(memmap: list[dict], tree, banks: list[tuple[int, int]], owned: int | None, payload_bytes: int | None,
          top_reserve: int) -> dict:
    errors: list[str] = []
    warnings: list[str] = []
    in_dram = lambda b, s: any(a <= b and b + s <= a + z for a, z in banks)  # noqa: E731
    touches_dram = lambda b, s: any(overlaps(b, b + s, a, a + z) for a, z in banks)  # noqa: E731

    dram_desc = [d for d in memmap if not d["mmio"]]
    for d in memmap:
        if d["base"] % PAGE or d["size"] % PAGE:
            errors.append(f"UEFI '{d['name']}' {d['base']:#x}+{d['size']:#x} is not 4 KiB aligned")
        if d["mmio"] and touches_dram(d["base"], d["size"]):
            errors.append(f"UEFI MMIO '{d['name']}' {d['base']:#x}+{d['size']:#x} lies in DRAM")
        if not d["mmio"] and not in_dram(d["base"], d["size"]):
            errors.append(f"UEFI '{d['name']}' {d['base']:#x}+{d['size']:#x} is outside the DRAM banks")
    srt = sorted(dram_desc, key=lambda d: d["base"])
    for a, b in zip(srt, srt[1:]):
        if a["base"] + a["size"] > b["base"]:
            errors.append(f"UEFI '{a['name']}' and '{b['name']}' overlap at {b['base']:#x}")

    reserved_desc = [d for d in dram_desc if d["mem"] != "Conv"]
    carve = [r for r in _fdt.reserved_regions(tree) if r["addr"] is not None and r["size"]] if tree else []
    uncovered = []
    for r in carve:
        if not r["no_map"]:
            continue
        runs = [(r["addr"], r["addr"] + r["size"])]
        for d in reserved_desc:
            runs = subtract(runs, (d["base"], d["base"] + d["size"]))
        if runs:
            uncovered.append(r["name"])
            errors.append(f"DT no-map '{r['name']}' {r['addr']:#x}+{r['size']:#x} not covered by a reserved UEFI "
                          f"descriptor: {[(hex(a), hex(b - a)) for a, b in runs]}")

    # The ABL window: kernel image (the UEFI FD, gzip) + DTB + ramdisk (the UniXNU payload volume).
    if payload_bytes is not None:
        fd_bytes = next((d["size"] for d in memmap if d["name"] == "UEFI FD"), 0x300000)
        need = 0x80000 + fd_bytes + 0x200000 + payload_bytes  # kernel at +0x80000 (Android 14 ABL), DTB slack 2 MiB
        if need > ABL_WINDOW[2]:
            errors.append(f"boot image needs {need:#x} bytes, ABL window is {ABL_WINDOW[2]:#x}")

    # Predict DarwinBoot's choice: the first free run that holds owned_memory_size (UniXNU-pipa board.toml).
    free = [(a, a + s) for a, s in banks]
    for d in dram_desc:
        free = subtract(free, (d["base"], d["base"] + d["size"]))
    for r in carve:
        free = subtract(free, (r["addr"], r["addr"] + r["size"]))
    top = max(a + s for a, s in banks)
    free = subtract(free, (top - top_reserve, top))
    free = [(a, b) for a, b in free if b - a >= PAGE]
    predicted = None
    if owned:
        for a, b in free:
            if b - a >= owned:
                predicted = {"base": f"{a:#x}", "end": f"{a + owned:#x}", "headroom": f"{b - a - owned:#x}"}
                if b - a - owned < 0x8000000:
                    warnings.append(f"XNU window {a:#x}+{owned:#x} leaves only {b - a - owned:#x} free in its run "
                                    f"(firmware top reserve assumed {top_reserve:#x})")
                break
        else:
            biggest = max((b - a for a, b in free), default=0)
            errors.append(f"no free run holds owned_memory_size {owned:#x}; largest is {biggest:#x} "
                          f"(firmware top reserve assumed {top_reserve:#x})")
    return {
        "errors": errors, "warnings": warnings,
        "banks": [[f"{a:#x}", f"{s:#x}"] for a, s in banks],
        "uefi_descriptors": len(memmap), "dt_carveouts": len(carve), "uncovered_no_map": uncovered,
        "free_runs": [[f"{a:#x}", f"{b - a:#x}"] for a, b in free],
        "predicted_xnu_window": predicted,
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--memmap", required=True)
    ap.add_argument("--dtb")
    ap.add_argument("--facts")
    ap.add_argument("--board")
    ap.add_argument("--firmware-top-reserve", type=lambda v: int(v, 0), default=0x10000000)
    ap.add_argument("--json")
    args = ap.parse_args(argv)
    with open(args.memmap, encoding="utf-8") as f:
        memmap = parse_memmap(f.read())
    if not memmap:
        print("check_memory: no descriptors parsed", file=sys.stderr)
        return 1
    tree = _fdt.load(args.dtb) if args.dtb else None
    if args.facts:
        banks = unitfacts.banks(unitfacts.load(args.facts))
    elif tree:
        banks = _fdt.memory_banks(tree)
    else:
        print("check_memory: need --facts or --dtb for the banks", file=sys.stderr)
        return 1
    owned = payload = None
    if args.board:
        with open(args.board, "rb") as f:
            board = tomllib.load(f)
        owned = int(board["payload"]["adt"]["owned_memory_size"], 0)
        payload = int(board["payload"]["size_mib"]) * 2**20
    res = check(memmap, tree, banks, owned, payload, args.firmware_top_reserve)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=2)
            f.write("\n")
    for w in res["warnings"]:
        print(f"WARN  {w}")
    for e in res["errors"]:
        print(f"FAIL  {e}")
    print(f"{'FAIL' if res['errors'] else 'PASS'}  memory: {res['uefi_descriptors']} UEFI descriptors, "
          f"{res['dt_carveouts']} DT carve-outs, banks {res['banks']}, XNU window {res['predicted_xnu_window']}")
    return 1 if res["errors"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
