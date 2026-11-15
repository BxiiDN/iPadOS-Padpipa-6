# SPDX-License-Identifier: MIT
"""Verified root chain, end to end with real RSA-3072 (OpenSSL) and the VerifiedRoot kit's own C parser and signer:
owner key -> 395-byte anchor -> signed envelope -> vr_open/vr_verify_block. Every tamper must be refused.

Needs: openssl CLI + headers, a C compiler, and the kit: PIPA_VERIFIED_ROOT_KIT=<UniXNU>/kits/VerifiedRoot.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import uuid

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import owner_key  # noqa: E402

KIT = os.environ.get("PIPA_VERIFIED_ROOT_KIT", "")
VR_FORMAT, VR_KEY, VR_SIGNATURE, VR_HASH_TABLE, VR_BLOCK = 1, 2, 3, 4, 5


@unittest.skipUnless(KIT and os.path.isfile(os.path.join(KIT, "src/verified_root.c")) and shutil.which("openssl")
                     and os.path.isfile("/usr/include/openssl/rsa.h"), "needs PIPA_VERIFIED_ROOT_KIT, openssl and its headers")
class VerifiedRootChain(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.cli = os.path.join(cls.tmp, "vr_cli")
        cc = shutil.which("cc") or shutil.which("clang")
        subprocess.run([cc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", os.path.join(KIT, "include"),
                        os.path.join(ROOT, "tests/verified_root/vr_cli.c"), os.path.join(KIT, "src/verified_root.c"),
                        os.path.join(KIT, "tests/openssl_provider.c"), "-lcrypto", "-o", cls.cli], check=True)
        cls.owner = owner_key._generate(os.path.join(cls.tmp, "keys"), "owner")
        cls.other = owner_key._generate(os.path.join(cls.tmp, "keys"), "ci-test")
        cls.image = os.path.join(cls.tmp, "root.img")
        with open(cls.image, "wb") as f:
            f.write(os.urandom(4096 * 5 + 100))          # a partial last block, as a real image can end
        cls.uuid = str(uuid.uuid4())
        cls.signed = os.path.join(cls.tmp, "signed")
        owner_key.sign(cls.image, cls.uuid, 7, cls.signed, os.path.join(cls.tmp, "keys"), "owner", KIT)
        cls.manifest = os.path.join(cls.signed, "manifest.bin")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.tmp)

    def run_cli(self, manifest=None, anchor=None, image=None, generation=7):
        r = subprocess.run([self.cli, manifest or self.manifest, anchor or self.owner["anchor"], image or self.image, str(generation)],
                           capture_output=True, text=True)
        return r.returncode, r.stdout

    def copy_with(self, path, offset, xor=0x01):
        data = bytearray(open(path, "rb").read())
        data[offset] ^= xor
        out = os.path.join(self.tmp, f"t-{os.path.basename(path)}-{offset}")
        with open(out, "wb") as f:
            f.write(data)
        return out

    def test_owner_signed_image_verifies(self):
        rc, out = self.run_cli()
        self.assertEqual(rc, 0, out)
        self.assertIn("ok 6 blocks", out)

    def test_anchor_matches_the_kit(self):
        sys.path.insert(0, os.path.join(KIT, "tools"))
        import manifest
        from pathlib import Path
        self.assertEqual(manifest.public_anchor(Path(self.owner["public"])), open(self.owner["anchor"], "rb").read())
        self.assertEqual(len(open(self.owner["anchor"], "rb").read()), 395)

    def test_wrong_signature_refused(self):
        rc, _ = self.run_cli(manifest=self.copy_with(self.manifest, 160 + 10))   # inside the RSA signature
        self.assertEqual(rc, VR_SIGNATURE)

    def test_changed_image_refused(self):
        rc, out = self.run_cli(image=self.copy_with(self.image, 4096 * 3 + 7))
        self.assertEqual(rc, VR_BLOCK)
        self.assertIn("block 3", out)

    def test_other_key_refused(self):
        rc, _ = self.run_cli(anchor=self.other["anchor"])
        self.assertEqual(rc, VR_KEY)

    def test_hash_table_tamper_refused(self):
        rc, _ = self.run_cli(manifest=self.copy_with(self.manifest, 160 + 384 + 5))
        self.assertIn(rc, (VR_SIGNATURE, VR_HASH_TABLE))    # the table digest is in the signed header

    def test_rollback_refused(self):
        rc, _ = self.run_cli(generation=8)
        self.assertEqual(rc, VR_FORMAT)

    def test_init_refuses_to_replace_a_key(self):
        with self.assertRaises(owner_key.KeyError_):
            owner_key._generate(os.path.join(self.tmp, "keys"), "owner")

    def test_private_key_is_private_and_never_in_the_anchor(self):
        self.assertEqual(os.stat(self.owner["key"]).st_mode & 0o777, 0o600)
        priv = open(self.owner["key"]).read()
        self.assertIn("PRIVATE KEY", priv)
        for f in ("anchor", "public"):
            self.assertNotIn(b"PRIVATE", open(self.owner[f], "rb").read())

    def test_bad_anchor_rejected(self):
        a = bytearray(open(self.owner["anchor"], "rb").read())
        for mutate in (lambda b: b[:394], lambda b: b"XROOTKEY" + b[8:], lambda b: b[:392] + b"\x00\x00\x03"):
            with self.assertRaises(owner_key.KeyError_):
                owner_key.check_anchor(bytes(mutate(bytes(a))))


if __name__ == "__main__":
    unittest.main()
