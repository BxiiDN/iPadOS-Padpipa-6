#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Minimal, dependency-free Flattened Device Tree (DTB) reader.

Used by the validators so that the checks run on a bare Windows/WSL2/CI host without dtc. Supports the
DTB v17 layout (header, memory reservation block, structure block, strings block) as described in the
Devicetree Specification v0.4, section 5.

    python3 tools/fdt.py file.dtb /reserved-memory        # print a node and its children's reg
"""
from __future__ import annotations

import struct
import sys
from dataclasses import dataclass, field

FDT_MAGIC = 0xD00DFEED
FDT_BEGIN_NODE, FDT_END_NODE, FDT_PROP, FDT_NOP, FDT_END = 1, 2, 3, 4, 9


class FdtError(ValueError):
    pass


@dataclass
class Node:
    name: str
    props: dict[str, bytes] = field(default_factory=dict)
    children: list["Node"] = field(default_factory=list)
    parent: "Node | None" = None

    # --- property helpers -------------------------------------------------------------------------
    def u32(self, prop: str, default: int | None = None) -> int | None:
        raw = self.props.get(prop)
        if raw is None or len(raw) < 4:
            return default
        return struct.unpack(">I", raw[:4])[0]

    def cells(self, prop: str) -> list[int]:
        raw = self.props.get(prop, b"")
        return list(struct.unpack(f">{len(raw) // 4}I", raw[: len(raw) // 4 * 4]))

    def string(self, prop: str) -> str | None:
        raw = self.props.get(prop)
        return None if raw is None else raw.rstrip(b"\0").split(b"\0")[0].decode("utf-8", "replace")

    def strings(self, prop: str) -> list[str]:
        raw = self.props.get(prop)
        return [] if raw is None else [s.decode("utf-8", "replace") for s in raw.rstrip(b"\0").split(b"\0")]

    @property
    def path(self) -> str:
        parts: list[str] = []
        node: Node | None = self
        while node is not None and node.parent is not None:
            parts.append(node.name)
            node = node.parent
        return "/" + "/".join(reversed(parts))

    def address_cells(self) -> int:
        """#address-cells that applies to this node's reg (taken from the parent)."""
        return (self.parent.u32("#address-cells", 2) if self.parent else 2) or 0

    def size_cells(self) -> int:
        return (self.parent.u32("#size-cells", 1) if self.parent else 1) or 0

    def reg(self) -> list[tuple[int, int]]:
        """reg as (address, size) pairs, using the parent's #address-cells/#size-cells."""
        ac, sc = self.address_cells(), self.size_cells()
        if ac == 0:
            return []
        cells = self.cells("reg")
        step = ac + sc
        out = []
        for i in range(0, len(cells) - step + 1, step):
            addr = 0
            for c in cells[i : i + ac]:
                addr = (addr << 32) | c
            size = 0
            for c in cells[i + ac : i + step]:
                size = (size << 32) | c
            out.append((addr, size))
        return out

    def child(self, name: str) -> "Node | None":
        for c in self.children:
            if c.name == name or c.name.split("@")[0] == name:
                return c
        return None

    def find(self, path: str) -> "Node | None":
        node: Node | None = self
        for part in [p for p in path.split("/") if p]:
            node = node.child(part) if node else None
        return node

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()


@dataclass
class Fdt:
    root: Node
    version: int
    boot_cpuid: int
    mem_reserve: list[tuple[int, int]]

    def find(self, path: str) -> Node | None:
        return self.root.find(path)


def parse(blob: bytes) -> Fdt:
    if len(blob) < 40:
        raise FdtError("file too short for an FDT header")
    (magic, totalsize, off_struct, off_strings, off_rsvmap, version, _last_comp, boot_cpuid,
     size_strings, size_struct) = struct.unpack(">10I", blob[:40])
    if magic != FDT_MAGIC:
        raise FdtError(f"bad magic {magic:#x} (expected {FDT_MAGIC:#x})")
    if totalsize > len(blob):
        raise FdtError(f"header totalsize {totalsize} > file size {len(blob)}")
    if version < 16:
        raise FdtError(f"unsupported FDT version {version}")

    rsv: list[tuple[int, int]] = []
    pos = off_rsvmap
    while True:
        addr, size = struct.unpack(">QQ", blob[pos : pos + 16])
        pos += 16
        if addr == 0 and size == 0:
            break
        rsv.append((addr, size))

    strings = blob[off_strings : off_strings + size_strings]

    def string_at(off: int) -> str:
        end = strings.index(b"\0", off)
        return strings[off:end].decode()

    pos = off_struct
    end_struct = off_struct + size_struct
    stack: list[Node] = []
    root: Node | None = None
    while pos < end_struct:
        (token,) = struct.unpack(">I", blob[pos : pos + 4])
        pos += 4
        if token == FDT_BEGIN_NODE:
            end = blob.index(b"\0", pos)
            name = blob[pos:end].decode("utf-8", "replace")
            pos = (end + 4) & ~3
            node = Node(name=name, parent=stack[-1] if stack else None)
            if stack:
                stack[-1].children.append(node)
            else:
                root = node
            stack.append(node)
        elif token == FDT_END_NODE:
            if not stack:
                raise FdtError("unbalanced FDT_END_NODE")
            stack.pop()
        elif token == FDT_PROP:
            length, nameoff = struct.unpack(">II", blob[pos : pos + 8])
            pos += 8
            value = blob[pos : pos + length]
            pos = (pos + length + 3) & ~3
            if not stack:
                raise FdtError("property outside a node")
            stack[-1].props[string_at(nameoff)] = value
        elif token == FDT_NOP:
            continue
        elif token == FDT_END:
            break
        else:
            raise FdtError(f"unknown token {token:#x} at {pos - 4:#x}")
    if root is None:
        raise FdtError("no root node")
    return Fdt(root=root, version=version, boot_cpuid=boot_cpuid, mem_reserve=rsv)


def load(path: str) -> Fdt:
    with open(path, "rb") as f:
        return parse(f.read())


def memory_banks(fdt: Fdt) -> list[tuple[int, int]]:
    banks: list[tuple[int, int]] = []
    for node in fdt.root.children:
        if node.string("device_type") == "memory" or node.name.split("@")[0] == "memory":
            banks.extend(r for r in node.reg() if r[1])
    return sorted(banks)


def reserved_regions(fdt: Fdt) -> list[dict]:
    """Static /reserved-memory children with a reg (dynamic 'size'-only pools are reported with addr None)."""
    out = []
    rm = fdt.find("/reserved-memory")
    if rm is None:
        return out
    for child in rm.children:
        regs = child.reg()
        nomap = "no-map" in child.props
        if regs:
            for addr, size in regs:
                out.append({"name": child.name, "addr": addr, "size": size, "no_map": nomap})
        elif "size" in child.props:
            out.append({"name": child.name, "addr": None, "size": None, "no_map": nomap})
    return out


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    fdt = load(argv[1])
    path = argv[2] if len(argv) > 2 else "/"
    node = fdt.find(path)
    if node is None:
        print(f"{path}: not found", file=sys.stderr)
        return 1
    print(f"{node.path}  compatible={node.strings('compatible')} reg={[(hex(a), hex(s)) for a, s in node.reg()]}")
    for c in node.children:
        print(f"  {c.name:40s} reg={[(hex(a), hex(s)) for a, s in c.reg()]} {'no-map' if 'no-map' in c.props else ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
