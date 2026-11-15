#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Last gate before the ONLY permanent write this project performs: `fastboot flash userdata <image>`.

Passes only if: the unit's facts are measured (memory and GPT), the generated board.toml matches them (check_board:
flash_allowed), and the image fits the measured userdata window. Exit 0 = allowed.

    python3 tools/flash_gate.py --unit pipa-8g256 --image out/.../userdata-root.sparse.img
"""
from __future__ import annotations

import argparse
import os
import struct
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "checks"))
import unitfacts  # noqa: E402
import check_board  # noqa: E402

ROOT = os.path.dirname(HERE)
SPARSE_MAGIC = 0xED26FF3A


def image_bytes(path: str) -> int:
    """Expanded size: Android sparse images carry it in their header (blk_sz * total_blks)."""
    with open(path, "rb") as f:
        head = f.read(28)
    if len(head) >= 28 and struct.unpack_from("<I", head, 0)[0] == SPARSE_MAGIC:
        blk_sz, total_blks = struct.unpack_from("<II", head, 12)
        return blk_sz * total_blks
    return os.path.getsize(path)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--unit", default="pipa-8g256")
    ap.add_argument("--image", required=True)
    ap.add_argument("--board", default=os.path.join(ROOT, "work", "UniXNU-pipa", "board.toml"))
    args = ap.parse_args(argv)
    facts = unitfacts.load(os.path.join(ROOT, "device", args.unit, "unit-facts.json"))
    reasons = unitfacts.problems(facts, need_storage=True)
    if facts["provenance"].get("source") != "measured":
        reasons.append("unit facts are not from the tablet (provenance.source != measured)")
    with open(args.board, encoding="utf-8") as f:
        res = check_board.check(f.read(), facts)
    reasons += res["errors"]
    if not res["flash_allowed"]:
        reasons.append("board.toml userdata window is not the measured one")
    if not reasons:
        ud = facts["storage"]["userdata"]
        window = (int(ud["last_lba"], 0) - int(ud["first_lba"], 0) + 1) * facts["storage"]["lba_bytes"]
        size = image_bytes(args.image)
        if size > window:
            reasons.append(f"image expands to {size} bytes, userdata window is {window}")
    for r in reasons:
        print(f"REFUSED  {r}")
    if reasons:
        return 3
    print("ALLOWED  userdata image fits the measured window of this unit")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
