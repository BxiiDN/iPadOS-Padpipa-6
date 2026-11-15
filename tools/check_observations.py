#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Accept QEMU ABI observations (scripts/mac/qemu-abi-observations.sh) only if every file still has its recorded SHA-256
and the accelerator was HVF. Usage: check_observations.py <dir>"""
import hashlib, json, os, sys
o = sys.argv[1]
m = json.load(open(os.path.join(o, "observations.json")))
bad = [f for f, h in m["files"].items()
       if not os.path.isfile(os.path.join(o, f)) or hashlib.sha256(open(os.path.join(o, f), "rb").read()).hexdigest() != h]
if bad or m.get("accel") != "hvf" or "interface-audit.json" not in m["files"]:
    sys.exit(f"observations refused: changed/missing {bad}, accel {m.get('accel')}")
print(f"observations accepted: {len(m['files'])} files, accel {m['accel']}, UniXNU-qemu {m.get('uniXNU_qemu_commit', '?')[:12]}")
