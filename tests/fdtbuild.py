# SPDX-License-Identifier: MIT
"""Tiny DTB writer for test fixtures (no dtc needed)."""
from __future__ import annotations

import struct


def _cells(*vals: int) -> bytes:
    return b"".join(struct.pack(">I", v) for v in vals)


def reg64(*pairs: tuple[int, int]) -> bytes:
    out = b""
    for a, s in pairs:
        out += _cells(a >> 32, a & 0xFFFFFFFF, s >> 32, s & 0xFFFFFFFF)
    return out


def u32(v: int) -> bytes:
    return _cells(v)


def build(tree: dict) -> bytes:
    """tree = {"props": {name: bytes}, "children": {name: tree}}"""
    strings = bytearray()
    offsets: dict[str, int] = {}
    struct_blk = bytearray()

    def soff(name: str) -> int:
        if name not in offsets:
            offsets[name] = len(strings)
            strings.extend(name.encode() + b"\0")
        return offsets[name]

    def node(name: str, t: dict) -> None:
        struct_blk.extend(struct.pack(">I", 1))
        nm = name.encode() + b"\0"
        struct_blk.extend(nm + b"\0" * ((4 - len(nm) % 4) % 4))
        for k, v in t.get("props", {}).items():
            struct_blk.extend(struct.pack(">III", 3, len(v), soff(k)))
            struct_blk.extend(v + b"\0" * ((4 - len(v) % 4) % 4))
        for cn, ct in t.get("children", {}).items():
            node(cn, ct)
        struct_blk.extend(struct.pack(">I", 2))

    node("", tree)
    struct_blk.extend(struct.pack(">I", 9))
    rsv = b"\0" * 16
    off_rsv = 40
    off_struct = off_rsv + len(rsv)
    off_strings = off_struct + len(struct_blk)
    total = off_strings + len(strings)
    header = struct.pack(">10I", 0xD00DFEED, total, off_struct, off_strings, off_rsv, 17, 16, 0, len(strings), len(struct_blk))
    return header + rsv + bytes(struct_blk) + bytes(strings)


def pipa_like(banks=((0x80000000, 0x3BB00000), (0xC0000000, 0x1C0000000)), reserved=None) -> bytes:
    reserved = reserved if reserved is not None else {
        "hyp_region@80000000": (0x80000000, 0x600000, True),
        "cont_splash_region@9c000000": (0x9C000000, 0x2300000, False),
    }
    rm = {"props": {"#address-cells": u32(2), "#size-cells": u32(2), "ranges": b""}, "children": {}}
    for name, (a, s, nomap) in reserved.items():
        props = {"reg": reg64((a, s))}
        if nomap:
            props["no-map"] = b""
        rm["children"][name] = {"props": props}
    return build({"props": {"#address-cells": u32(2), "#size-cells": u32(2), "compatible": b"qcom,kona\0"},
                  "children": {"memory": {"props": {"device_type": b"memory\0", "reg": reg64(*banks)}},
                               "reserved-memory": rm}})
