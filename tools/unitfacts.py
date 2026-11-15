#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Facts about ONE physical Xiaomi Pad 6, with where each came from.

The reference port (xVanTuring/UniXNU-pipa) was measured on a tablet upgraded to 16 GB with 128 GB storage. This project
targets an 8 GB / 256 GB unit, so memory banks and the userdata window must come from *this* unit. Every value carries a
provenance:

    measured   read from the target tablet (scripts/device/collect-unit-facts.sh over adb, or the UEFI log)
    stock-dtb  taken from the stock pipa DTB (uefi-pipa Resources/DTBs/pipa.dtb); ABL rewrites /memory at boot, so this
               is a strong hint for the 8 GB SKU but NOT proof for this unit
    missing    not known yet

Usage:
    python3 tools/unitfacts.py from-adb  collected.kv  -o device/pipa-8g256/unit-facts.json
    python3 tools/unitfacts.py from-dtb  pipa.dtb      -o /tmp/unit-facts.stock.json
    python3 tools/unitfacts.py show      device/pipa-8g256/unit-facts.json
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import fdt as _fdt  # noqa: E402

SCHEMA = 1
DRAM_BASE = 0x80000000
LBA_BYTES = 4096
EXPECTED_PRODUCT = "pipa"


def _hx(v: int) -> str:
    return f"{v:#x}"


def _int(v) -> int:
    return int(v, 0) if isinstance(v, str) else int(v)


def empty() -> dict:
    return {
        "schema": SCHEMA,
        "provenance": {"source": "missing", "collected_at": None},
        "device": {"product": None, "build_fingerprint": None, "serial_sha256": None},
        "memory": {"source": "missing", "mem_total_kib": None, "banks": []},
        "storage": {"source": "missing", "lba_bytes": None, "userdata": None, "disk_blocks": None,
                    "ufs_vendor": None, "ufs_model": None, "partitions": []},
        "panel": {"source": "missing", "name": None},
        "notes": [],
    }


def from_dtb(path: str) -> dict:
    facts = empty()
    tree = _fdt.load(path)
    banks = _fdt.memory_banks(tree)
    facts["provenance"] = {"source": "stock-dtb", "collected_at": _now(), "dtb": os.path.basename(path)}
    facts["device"]["product"] = "pipa"
    facts["memory"] = {"source": "stock-dtb", "mem_total_kib": None, "banks": [[_hx(a), _hx(s)] for a, s in banks]}
    facts["notes"].append("memory banks from the stock DTB; ABL fills /memory at boot, confirm on the unit")
    return facts


def from_adb_kv(path: str) -> dict:
    """Parse the key=value dump written by scripts/device/collect-unit-facts.sh."""
    kv: dict[str, str] = {}
    parts: list[dict] = []
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\r\n")
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            if k == "part":
                # part=<dev>|<name>|<start_512>|<size_512>
                dev, name, start, size = (v.split("|") + ["", "", "", ""])[:4]
                if start.isdigit() and size.isdigit():
                    parts.append({"dev": dev, "name": name, "start_512": int(start), "size_512": int(size)})
                continue
            kv[k] = v.strip()
    facts = empty()
    facts["provenance"] = {"source": "measured", "collected_at": kv.get("collected_at") or _now(),
                           "collector": kv.get("collector_version"), "root": kv.get("root") == "1"}
    facts["device"] = {"product": kv.get("ro.product.device") or kv.get("ro.product.vendor.device") or None,
                       "build_fingerprint": kv.get("ro.build.fingerprint"),
                       "serial_sha256": kv.get("serial_sha256")}
    mem_total = kv.get("mem_total_kib")
    banks = _parse_reg_hex(kv.get("dt_memory_reg", ""))
    facts["memory"] = {"source": "measured" if banks else ("measured-total-only" if mem_total else "missing"),
                       "mem_total_kib": int(mem_total) if mem_total and mem_total.isdigit() else None,
                       "banks": [[_hx(a), _hx(s)] for a, s in banks]}
    lba = int(kv["lun0_lba_bytes"]) if kv.get("lun0_lba_bytes", "").isdigit() else None
    ud = next((p for p in parts if p["name"] == "userdata"), None)
    storage = {"source": "missing", "lba_bytes": lba, "userdata": None,
               "disk_blocks": int(kv["lun0_size_512"]) // ((lba or 512) // 512) if kv.get("lun0_size_512", "").isdigit() else None,
               "ufs_vendor": kv.get("ufs_vendor"), "ufs_model": kv.get("ufs_model"),
               "partitions": parts}
    if ud and lba:
        per = lba // 512
        if ud["start_512"] % per or ud["size_512"] % per:
            facts["notes"].append("userdata start/size are not multiples of the logical block size")
        first = ud["start_512"] // per
        last = first + ud["size_512"] // per - 1
        storage["userdata"] = {"dev": ud["dev"], "first_lba": _hx(first), "last_lba": _hx(last)}
        storage["source"] = "measured"
    facts["storage"] = storage
    facts["panel"] = {"source": "measured" if kv.get("panel") else "missing", "name": kv.get("panel") or None}
    if kv.get("errors"):
        facts["notes"].append("collector could not read: " + kv["errors"])
    return facts


def _parse_reg_hex(text: str) -> list[tuple[int, int]]:
    """dt_memory_reg is the raw /memory reg as hex (od -An -tx1 output, spaces allowed), 2 address + 2 size cells."""
    digits = "".join(ch for ch in text if ch in "0123456789abcdefABCDEF")
    if not digits or len(digits) % 32:
        return []
    raw = bytes.fromhex(digits)
    out = []
    for i in range(0, len(raw), 16):
        addr = int.from_bytes(raw[i:i + 8], "big")
        size = int.from_bytes(raw[i + 8:i + 16], "big")
        if size:
            out.append((addr, size))
    return out


def _now() -> str:
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def load(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        facts = json.load(f)
    if facts.get("schema") != SCHEMA:
        raise ValueError(f"{path}: schema {facts.get('schema')} != {SCHEMA}")
    return facts


def banks(facts: dict) -> list[tuple[int, int]]:
    return sorted((_int(a), _int(s)) for a, s in facts["memory"].get("banks", []))


def dram_size(facts: dict) -> int:
    """XNU takes one range: from dram-base to the end of the last bank (UniXNU-pipa board.toml)."""
    b = banks(facts)
    if not b:
        raise ValueError("no memory banks in the unit facts")
    return max(a + s for a, s in b) - DRAM_BASE


def problems(facts: dict, *, need_storage: bool) -> list[str]:
    """Reasons these facts are not enough; empty list = usable."""
    out: list[str] = []
    prod = facts["device"].get("product")
    if prod not in (None, EXPECTED_PRODUCT):
        out.append(f"device product is {prod!r}, not {EXPECTED_PRODUCT!r}")
    b = banks(facts)
    if not b:
        out.append("memory banks missing")
    else:
        if b[0][0] != DRAM_BASE:
            out.append(f"first bank starts at {b[0][0]:#x}, expected {DRAM_BASE:#x}")
        for (a1, s1), (a2, _s2) in zip(b, b[1:]):
            if a1 + s1 > a2:
                out.append(f"memory banks overlap at {a2:#x}")
        total = sum(s for _a, s in b)
        mt = facts["memory"].get("mem_total_kib")
        if mt and not (0.80 * total <= mt * 1024 <= total):
            out.append(f"MemTotal {mt} KiB is inconsistent with banks totalling {total:#x} bytes")
    if need_storage:
        st = facts.get("storage") or {}
        if st.get("source") != "measured" or not st.get("userdata"):
            out.append("userdata window not measured on this unit (storage.source != measured)")
        elif st.get("lba_bytes") != LBA_BYTES:
            out.append(f"logical block size {st.get('lba_bytes')} != {LBA_BYTES}")
        else:
            first, last = _int(st["userdata"]["first_lba"]), _int(st["userdata"]["last_lba"])
            if not 0 < first < last:
                out.append("userdata first_lba/last_lba are not increasing")
            gib = (last - first + 1) * LBA_BYTES / 2**30
            if not 150 <= gib <= 240:
                out.append(f"userdata is {gib:.1f} GiB, outside what a 256 GB pipa can have (150..240 GiB)")
    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("from-adb", "from-dtb"):
        p = sub.add_parser(name)
        p.add_argument("input")
        p.add_argument("-o", "--output", required=True)
    p = sub.add_parser("show")
    p.add_argument("input")
    args = ap.parse_args(argv)
    if args.cmd == "show":
        facts = load(args.input)
        print(json.dumps(facts, indent=2))
        for need in (False, True):
            pr = problems(facts, need_storage=need)
            print(f"usable for {'flash/userdata' if need else 'build/boot'}: {'yes' if not pr else 'NO: ' + '; '.join(pr)}")
        return 0
    facts = from_adb_kv(args.input) if args.cmd == "from-adb" else from_dtb(args.input)
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(facts, f, indent=2)
        f.write("\n")
    print(f"wrote {args.output} (memory: {facts['memory']['source']}, storage: {facts['storage']['source']})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
