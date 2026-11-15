#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Check out every base source at its pinned commit under work/ (a clean, reproducible tree).

    python3 tools/bootstrap.py [--work work] [--only UniXNU,UniXNU-pipa,uefi-pipa] [--verify]

--verify only checks that existing checkouts are at the pinned commits (exit 1 otherwise).
Layout (what the unixnu driver expects, UniXNU-pipa README "Stage 1 to 3"):
    work/UniXNU        work/UniXNU-pipa        work/uefi-pipa
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import tomllib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BASE = ("UniXNU", "UniXNU-pipa", "uefi-pipa")


def git(*args: str, cwd: str | None = None, check: bool = True) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if check and r.returncode:
        raise SystemExit(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout.strip()


def checkout(name: str, src: dict, work: str) -> None:
    path = os.path.join(work, name)
    commit = src["commit"]
    if not os.path.isdir(os.path.join(path, ".git")):
        os.makedirs(path, exist_ok=True)
        git("init", "-q", path)
        git("remote", "add", "origin", src["url"], cwd=path)
    print(f"== {name}: {src['url']} @ {commit[:12]}")
    git("fetch", "-q", "--depth", "1", "origin", commit, cwd=path)
    git("-c", "advice.detachedHead=false", "checkout", "-q", "--force", commit, cwd=path)
    head = git("rev-parse", "HEAD", cwd=path)
    if head != commit:
        raise SystemExit(f"{name}: HEAD {head} != pinned {commit}")
    if name == "UniXNU-pipa":
        # The device repository's driver forks are gitlinks; their commits are the pins in sources.lock.toml.
        git("submodule", "update", "--init", "--depth", "1", cwd=path)
        for sub, want in src.get("drivers", {}).items():
            got = git("rev-parse", "HEAD", cwd=os.path.join(path, sub))
            if got != want:
                raise SystemExit(f"{name}/{sub}: {got} != pinned {want}")
        # Keep upstream's board file next to the generated one (tools/pipa_board.py writes board.toml).
        up = os.path.join(path, "board.upstream.toml")
        if not os.path.exists(up):
            with open(os.path.join(path, "board.toml"), "rb") as f, open(up, "wb") as g:
                g.write(f.read())


def verify(name: str, src: dict, work: str) -> bool:
    path = os.path.join(work, name)
    try:
        head = git("rev-parse", "HEAD", cwd=path)
    except SystemExit:
        print(f"MISSING  {name} ({path})")
        return False
    ok = head == src["commit"]
    print(f"{'OK     ' if ok else 'DIFFERS'}  {name} {head[:12]} (pinned {src['commit'][:12]})")
    return ok


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--work", default=os.path.join(ROOT, "work"))
    ap.add_argument("--only")
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args(argv)
    with open(os.path.join(ROOT, "manifest", "sources.lock.toml"), "rb") as f:
        lock = tomllib.load(f)["source"]
    names = args.only.split(",") if args.only else list(BASE)
    os.makedirs(args.work, exist_ok=True)
    if args.verify:
        return 0 if all(verify(n, lock[n], args.work) for n in names) else 1
    for n in names:
        checkout(n, lock[n], args.work)
    print("bootstrap done; next: scripts/wsl/build.sh board")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
