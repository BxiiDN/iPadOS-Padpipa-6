#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The owner key of the verified root (VerifiedRoot kit, kits/VerifiedRoot), created ONCE on the owner's machine.

    python3 tools/owner_key.py init                 # .cache/owner-key/: owner.key (0600), owner.pub, owner.anchor, owner.anchor.sha256
    python3 tools/owner_key.py show                 # prints the PUBLIC anchor's SHA-256 (the board.toml pin), never the key
    python3 tools/owner_key.py ci-test --dir DIR    # a throwaway CI key: its anchor is labelled "ci-test", never the owner's
    python3 tools/owner_key.py sign --image IMG --volume-uuid UUID --generation N --output DIR [--key-dir D]
    python3 tools/owner_key.py anchor --public PEM -o FILE

Anchor (VerifiedRoot verified_root.h VR_KEY_BYTES = 395, read by adapters/xnu_crypto.c rsa_make_pub):
    b"VROOTKEY" + RSA-3072 modulus (384 bytes, big endian, top bit set, odd) + exponent 65537 (01 00 01)
The kernel embeds only this anchor (build-verified-root-key.py). The private key never leaves .cache/owner-key: it is not
printed, logged, committed (.gitignore: /.cache/) or uploaded. `init` refuses to overwrite an existing key, so builds never
re-create it (a new key would orphan every signed root image).
"""
from __future__ import annotations

import argparse
import hashlib
import os
import re
import stat
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DIR = os.path.join(ROOT, ".cache", "owner-key")
MAGIC = b"VROOTKEY"
ANCHOR_BYTES = 395


class KeyError_(RuntimeError):
    pass


def _openssl(*args: str, capture: bool = True) -> str:
    r = subprocess.run(["openssl", *args], capture_output=capture, text=True)
    if r.returncode:
        raise KeyError_(f"openssl {args[0]} failed: {r.stderr.strip()[-300:]}")
    return r.stdout


def anchor_from_public(public_pem: str) -> bytes:
    text = _openssl("rsa", "-pubin", "-in", public_pem, "-text", "-noout")
    if not re.search(r"(?:Exponent|exponent): 65537\b", text):
        raise KeyError_("the public key's exponent is not 65537")
    line = _openssl("rsa", "-pubin", "-in", public_pem, "-modulus", "-noout")
    modulus = bytes.fromhex(line.strip().split("=", 1)[1])
    anchor = MAGIC + modulus + b"\x01\x00\x01"
    check_anchor(anchor)
    return anchor


def check_anchor(anchor: bytes) -> None:
    """Same acceptance as the kit's tools/manifest.py public_anchor: exact size, magic, 3072-bit odd modulus, e = 65537."""
    if len(anchor) != ANCHOR_BYTES:
        raise KeyError_(f"anchor is {len(anchor)} bytes, not {ANCHOR_BYTES}")
    if anchor[:8] != MAGIC:
        raise KeyError_("anchor magic is not VROOTKEY")
    modulus = anchor[8:392]
    if not modulus[0] & 0x80 or not modulus[-1] & 1:
        raise KeyError_("modulus is not a full-size odd 3072-bit value")
    if anchor[392:] != b"\x01\x00\x01":
        raise KeyError_("exponent is not 65537")


def anchor_sha256(anchor: bytes) -> str:
    return hashlib.sha256(anchor).hexdigest()


def _generate(directory: str, stem: str) -> dict:
    os.makedirs(directory, mode=0o700, exist_ok=True)
    os.chmod(directory, 0o700)
    key = os.path.join(directory, stem + ".key")
    pub = os.path.join(directory, stem + ".pub")
    if os.path.exists(key):
        raise KeyError_(f"{key} exists: refusing to replace a key (images signed with it would no longer verify)")
    old = os.umask(0o077)
    try:
        _openssl("genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:3072", "-pkeyopt", "rsa_keygen_pubexp:65537",
                 "-out", key)
    finally:
        os.umask(old)
    os.chmod(key, stat.S_IRUSR | stat.S_IWUSR)
    _openssl("rsa", "-in", key, "-pubout", "-out", pub)
    anchor = anchor_from_public(pub)
    with open(os.path.join(directory, stem + ".anchor"), "wb") as f:
        f.write(anchor)
    with open(os.path.join(directory, stem + ".anchor.sha256"), "w") as f:
        f.write(anchor_sha256(anchor) + "\n")
    return {"key": key, "public": pub, "anchor": os.path.join(directory, stem + ".anchor"), "sha256": anchor_sha256(anchor)}


def load(directory: str = DEFAULT_DIR, stem: str = "owner") -> dict:
    anchor_path = os.path.join(directory, stem + ".anchor")
    if not os.path.isfile(anchor_path):
        raise KeyError_(f"no {stem} key in {directory}: run 'tools/owner_key.py init' once")
    with open(anchor_path, "rb") as f:
        anchor = f.read()
    check_anchor(anchor)
    key = os.path.join(directory, stem + ".key")
    if os.path.exists(key) and os.stat(key).st_mode & 0o077:
        raise KeyError_(f"{key} is readable by others: chmod 600 it")
    return {"key": key, "public": os.path.join(directory, stem + ".pub"), "anchor": anchor_path, "sha256": anchor_sha256(anchor)}


def sign(image: str, volume_uuid: str, generation: int, output: str, key_dir: str, stem: str, kit: str) -> dict:
    """Sign a root image with the kit's own signer (kits/VerifiedRoot/tools/manifest.py make)."""
    k = load(key_dir, stem)
    sys.path.insert(0, os.path.join(kit, "tools"))
    import importlib
    manifest = importlib.import_module("manifest")
    from pathlib import Path
    import uuid
    if manifest.public_anchor(Path(k["public"])) != open(k["anchor"], "rb").read():
        raise KeyError_("this tool's anchor differs from the kit's public_anchor(): refusing to sign")
    with open(image, "rb") as stream:
        return manifest.make(stream, os.path.getsize(image), Path(k["key"]), Path(k["public"]),
                             uuid.UUID(volume_uuid), generation, Path(output))


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("init").add_argument("--dir", default=DEFAULT_DIR)
    sub.add_parser("show").add_argument("--dir", default=DEFAULT_DIR)
    p = sub.add_parser("ci-test")
    p.add_argument("--dir", required=True)
    p = sub.add_parser("anchor")
    p.add_argument("--public", required=True)
    p.add_argument("-o", "--output", required=True)
    p = sub.add_parser("sign")
    for a in ("--image", "--volume-uuid", "--output"):
        p.add_argument(a, required=True)
    p.add_argument("--generation", type=int, required=True)
    p.add_argument("--key-dir", default=DEFAULT_DIR)
    p.add_argument("--stem", default="owner")
    p.add_argument("--kit", default=os.environ.get("PIPA_VERIFIED_ROOT_KIT", os.path.join(ROOT, "work/UniXNU/kits/VerifiedRoot")))
    args = ap.parse_args(argv)
    try:
        if args.cmd == "init":
            if os.path.abspath(args.dir).startswith(os.path.join(ROOT, "")) and not os.path.abspath(args.dir).startswith(os.path.join(ROOT, ".cache")):
                raise KeyError_("the owner key must live under .cache/ (ignored by Git) or outside the repository")
            k = _generate(args.dir, "owner")
            print(f"owner key created in {args.dir} (private key not shown). Anchor SHA-256 (the board pin): {k['sha256']}")
        elif args.cmd == "show":
            print(load(args.dir)["sha256"])
        elif args.cmd == "ci-test":
            k = _generate(args.dir, "ci-test")
            print(f"CI TEST key (not the owner's; images signed with it must never be flashed): {k['sha256']}")
        elif args.cmd == "anchor":
            a = anchor_from_public(args.public)
            with open(args.output, "wb") as f:
                f.write(a)
            print(anchor_sha256(a))
        elif args.cmd == "sign":
            rec = sign(args.image, args.volume_uuid, args.generation, args.output, args.key_dir, args.stem, args.kit)
            print(f"signed {args.image}: {rec['block_count']} blocks, anchor {rec['trusted_key_sha256']}")
    except KeyError_ as e:
        print(f"owner_key: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
