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
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "checks"))
import unitfacts  # noqa: E402
import sparse  # noqa: E402
import check_board  # noqa: E402

ROOT = os.path.dirname(HERE)


def image_problems(path: str, window: int, lba: int) -> tuple[list[str], dict | None]:
    """The image fastboot would write: every sparse chunk is walked; the expanded size must fit the window and be a
    whole number of logical blocks."""
    try:
        inf = sparse.info(path)
    except sparse.SparseError as e:
        return [f"invalid sparse image: {e}"], None
    out = []
    if inf["expanded"] == 0:
        out.append("image is empty")
    if inf["expanded"] % lba:
        out.append(f"expanded size {inf['expanded']} is not a multiple of the {lba}-byte block")
    if inf["sparse"] and inf["blk_sz"] % lba:
        out.append(f"sparse block size {inf['blk_sz']} is not a multiple of {lba}")
    if inf["expanded"] > window:
        out.append(f"image expands to {inf['expanded']} bytes, userdata window is {window}")
    return out, inf


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
        board_text = f.read()
    res = check_board.check(board_text, facts)
    if "--ci-test-key" in board_text:
        reasons.append("board.toml pins a CI TEST key: its kernel and root image must never be written to a tablet")
    reasons += res["errors"]
    if not res["flash_allowed"]:
        reasons.append("board.toml userdata window is not the measured one")
    if not reasons:
        ud = facts["storage"]["userdata"]
        lba = facts["storage"]["lba_bytes"]
        window = (int(ud["last_lba"], 0) - int(ud["first_lba"], 0) + 1) * lba
        img_reasons, inf = image_problems(args.image, window, lba)
        reasons += img_reasons
        if inf:
            print(f"image: {'sparse' if inf['sparse'] else 'raw'}, expands to {inf['expanded']} bytes "
                  f"({inf['expanded'] / 2**30:.2f} GiB) of a {window / 2**30:.2f} GiB window")
    for r in reasons:
        print(f"REFUSED  {r}")
    if reasons:
        return 3
    print("ALLOWED  userdata image fits the measured window of this unit")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
