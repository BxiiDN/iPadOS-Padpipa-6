#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Missing-symbol gate for the kernel link: every undefined symbol in the driver archives must be defined by the
kernel or by another archive, and every symbol in --require must be defined somewhere.

Uses llvm-nm (or nm) so it reads Mach-O arm64 objects on a Linux/WSL2 host.

    python3 tools/checks/check_symbols.py --kernel build/xnu/.../kernel.unstripped \
        --archive out/pipa/tree/build/**/libAdreno650.a ... [--require tools/checks/required-symbols.txt]
"""
from __future__ import annotations

import argparse
import glob
import json
import shutil
import subprocess
import sys


def nm_tool() -> str:
    for t in ("llvm-nm", "llvm-nm-18", "nm"):
        if shutil.which(t):
            return t
    raise SystemExit("check_symbols: neither llvm-nm nor nm found")


def symbols(path: str, tool: str) -> tuple[set[str], set[str]]:
    out = subprocess.run([tool, "-g", "-P", path], capture_output=True, text=True)
    if out.returncode:
        raise RuntimeError(f"{tool} {path}: {out.stderr.strip()}")
    defined, undefined = set(), set()
    for line in out.stdout.splitlines():
        parts = line.split()
        if len(parts) < 2 or line.endswith(":"):
            continue
        name, kind = parts[0], parts[1]
        if kind == "U":
            undefined.add(name)
        elif kind in ("w", "v"):
            continue  # weak undefined: optional by design (e.g. the backlight hooks UniXNU-pipa leaves weak)
        else:
            defined.add(name)
    return defined, undefined


def check(kernel: str | None, archives: list[str], required: list[str], tool: str, allowed: set[str] | None = None) -> dict:
    defined: set[str] = set()
    undefined: dict[str, set[str]] = {}
    if kernel:
        d, _u = symbols(kernel, tool)
        defined |= d
    for a in archives:
        d, u = symbols(a, tool)
        defined |= d
        undefined[a] = u
    allowed = allowed or set()
    missing = {a: sorted(u - defined - allowed) for a, u in undefined.items() if u - defined - allowed}
    req_missing = sorted(s for s in required if s not in defined)
    errors = [f"{a}: {len(m)} undefined: {', '.join(m[:12])}{' ...' if len(m) > 12 else ''}" for a, m in missing.items()]
    errors += [f"required symbol not defined: {s}" for s in req_missing]
    return {"errors": errors, "warnings": [], "missing": missing, "required_missing": req_missing,
            "defined": len(defined), "archives": archives}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--kernel")
    ap.add_argument("--archive", action="append", default=[])
    ap.add_argument("--require")
    ap.add_argument("--allow", help="symbols resolved later (e.g. by kexts of the original kernelcache at prelink), one per line")
    ap.add_argument("--json")
    args = ap.parse_args(argv)
    archives = sorted({p for pat in args.archive for p in (glob.glob(pat, recursive=True) or [pat])})
    required = []
    if args.require:
        with open(args.require, encoding="utf-8") as f:
            required = [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    allowed: set[str] = set()
    if args.allow:
        with open(args.allow, encoding="utf-8") as f:
            allowed = {ln.strip() for ln in f if ln.strip() and not ln.startswith("#")}
    res = check(args.kernel, archives, required, nm_tool(), allowed)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=2)
            f.write("\n")
    for e in res["errors"]:
        print(f"FAIL  {e}")
    print(f"{'FAIL' if res['errors'] else 'PASS'}  symbols: {len(archives)} archives, {res['defined']} defined")
    return 1 if res["errors"] else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
