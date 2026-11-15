#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Turn the reference board.toml (xVanTuring/UniXNU-pipa, a 16 GB / 128 GB tablet) into the board.toml of THIS unit.

Only the values that depend on the physical unit are changed; every other line (IPSW pins, kernel archives, kernel
arguments, ADT tool) stays byte-for-byte as upstream so that `git diff` shows exactly what this project changes.

    python3 tools/pipa_board.py --upstream work/UniXNU-pipa/board.toml \
        --facts device/pipa-8g256/unit-facts.json --overlay device/pipa-8g256/overlay.toml \
        -o work/UniXNU-pipa/board.toml.new --report build/board-report.json

What changes and why (see docs/ARCHITECTURE.md, "Per-unit values"):
  [payload]     dram_size          end of the last measured bank - 0x80000000 (16 GB unit: 0x980000000)
  [payload.adt] owned_memory_size  from overlay.toml (default 4 GiB for the first rounds on an 8 GB unit)
  [payload]     title              names this project
  [userdata]    first_lba/last_lba ONLY from a measured GPT; otherwise left as upstream and marked NOT-FOR-FLASH
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tomllib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import unitfacts  # noqa: E402

DARWINBOOT_CMDLINE_LIMIT = 1000  # bytes, UniXNU-pipa board.toml comment on kernel_args ("DarwinBoot's limit")
NOT_FOR_FLASH = "# NOT-FOR-FLASH: userdata window below is the 128 GB reference unit's; measure this unit's GPT first."


class BoardError(ValueError):
    pass


def _section_span(text: str, section: str) -> tuple[int, int]:
    m = re.search(rf"^\[{re.escape(section)}\]\s*$", text, re.M)
    if not m:
        raise BoardError(f"section [{section}] not found")
    nxt = re.search(r"^\[[^\]]+\]\s*$", text[m.end():], re.M)
    return m.end(), (m.end() + nxt.start()) if nxt else len(text)


def set_key(text: str, section: str, key: str, literal: str) -> tuple[str, str | None]:
    """Replace `key = <value>` inside [section], keeping any trailing comment. Returns (text, old literal)."""
    start, end = _section_span(text, section)
    body = text[start:end]
    pat = re.compile(rf"^(?P<pre>{re.escape(key)}\s*=\s*)(?P<val>\"[^\"]*\"|[^\s#]+)(?P<post>[^\n]*)$", re.M)
    m = pat.search(body)
    if not m:
        raise BoardError(f"[{section}] {key} not found")
    old = m.group("val")
    body = body[:m.start()] + m.group("pre") + literal + m.group("post") + body[m.end():]
    return text[:start] + body + text[end:], old


def insert_comment_before(text: str, section: str, comment: str) -> str:
    m = re.search(rf"^\[{re.escape(section)}\]\s*$", text, re.M)
    if not m:
        raise BoardError(f"section [{section}] not found")
    if comment in text:
        return text
    return text[:m.start()] + comment + "\n" + text[m.start():]


def load_overlay(path: str | None) -> dict:
    defaults = {"owned_memory_size": "0x100000000", "title": "iPadOS-Padpipa-6: Xiaomi Pad 6 8 GB / 256 GB"}
    if not path:
        return defaults
    with open(path, "rb") as f:
        data = tomllib.load(f)
    defaults.update({k: v for k, v in data.get("board", {}).items()})
    return defaults


def generate(upstream_text: str, facts: dict, overlay: dict) -> tuple[str, dict]:
    report: dict = {"changes": [], "warnings": [], "flash_allowed": False}
    pr = unitfacts.problems(facts, need_storage=False)
    if pr:
        raise BoardError("unit facts not usable for a build: " + "; ".join(pr))
    text = upstream_text
    up = tomllib.loads(upstream_text)

    dram = unitfacts.dram_size(facts)
    text, old = set_key(text, "payload", "dram_size", f'"{dram:#x}"')
    report["changes"].append({"key": "payload.dram_size", "old": old, "new": f"{dram:#x}",
                              "source": facts["memory"]["source"]})

    owned = int(str(overlay["owned_memory_size"]), 0)
    if not 0x10000000 <= owned <= 0x200000000 or owned % 0x200000:
        # Same bounds as UniXNU-pipa scripts/make-pipa-adt.py (--owned-memory-size).
        raise BoardError(f"owned_memory_size {owned:#x} outside 0x10000000..0x200000000 or not 2 MiB aligned")
    if owned > dram:
        raise BoardError(f"owned_memory_size {owned:#x} larger than dram_size {dram:#x}")
    text, old = set_key(text, "payload.adt", "owned_memory_size", f'"{owned:#x}"')
    report["changes"].append({"key": "payload.adt.owned_memory_size", "old": old, "new": f"{owned:#x}",
                              "source": "overlay.toml"})

    text, old = set_key(text, "payload", "title", json.dumps(overlay["title"]))
    report["changes"].append({"key": "payload.title", "old": old, "new": overlay["title"], "source": "overlay.toml"})

    st_problems = unitfacts.problems(facts, need_storage=True)
    if not st_problems:
        ud = facts["storage"]["userdata"]
        for key in ("first_lba", "last_lba"):
            val = int(ud[key], 0)
            text, old = set_key(text, "userdata", key, f"{val:#x}")
            report["changes"].append({"key": f"userdata.{key}", "old": old, "new": f"{val:#x}", "source": "measured"})
        report["flash_allowed"] = True
    else:
        text = insert_comment_before(text, "userdata", NOT_FOR_FLASH)
        report["warnings"].extend(st_problems)

    args = up.get("payload", {}).get("kernel_args", [])
    cmdline = " ".join(args)
    report["kernel_args_bytes"] = len(cmdline.encode())
    if len(cmdline.encode()) > DARWINBOOT_CMDLINE_LIMIT:
        raise BoardError(f"kernel_args are {len(cmdline.encode())} bytes, over DarwinBoot's {DARWINBOOT_CMDLINE_LIMIT}")
    tomllib.loads(text)  # must still parse
    report["dram_size"] = f"{dram:#x}"
    report["owned_memory_size"] = f"{owned:#x}"
    report["facts_provenance"] = facts.get("provenance")
    return text, report


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--upstream", required=True)
    ap.add_argument("--facts", required=True)
    ap.add_argument("--overlay")
    ap.add_argument("-o", "--output", required=True)
    ap.add_argument("--report")
    args = ap.parse_args(argv)
    with open(args.upstream, encoding="utf-8") as f:
        upstream = f.read()
    try:
        text, report = generate(upstream, unitfacts.load(args.facts), load_overlay(args.overlay))
    except BoardError as e:
        print(f"pipa_board: {e}", file=sys.stderr)
        return 1
    with open(args.output, "w", encoding="utf-8") as f:
        f.write(text)
    if args.report:
        os.makedirs(os.path.dirname(os.path.abspath(args.report)), exist_ok=True)
        with open(args.report, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2)
            f.write("\n")
    for c in report["changes"]:
        print(f"  {c['key']:34s} {c['old']} -> {c['new']}  ({c['source']})")
    for w in report["warnings"]:
        print(f"  WARNING: {w}")
    print(f"  flash/userdata allowed: {report['flash_allowed']}; kernel_args {report['kernel_args_bytes']} bytes")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
