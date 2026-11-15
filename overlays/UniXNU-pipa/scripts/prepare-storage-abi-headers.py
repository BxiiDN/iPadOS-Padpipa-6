#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The static half of UniXNU's scripts/audit-storage-interface.py, as a separate archive step (iPadOS-Padpipa-6).

audit-storage-interface.py first lays out build/storage-abi/include from the PUBLIC Darwin 23 IOStorageFamily source
(refer/IOStorageFamily at e45fbe30, pinned by unixnu.lock) plus the SDK's TargetConditionals.h, then qualifies the ABI
against a LIVE observation of a running kernel (build/darwinboot-storage-native-metadata/gdb-stop.json) and a prelinked
candidate (build/xnu-prelink/native-apfs-load-positive.macho). The producers of those two inputs are not public.

PipaUfs (NativeUfs.cpp) compiles against build/storage-abi/include only; it does not read interface-audit.json. This step
writes exactly the same headers, byte for byte, with the same source pin, and records their digests. It writes NO
interface-audit.json: the live-qualified audit (used by build-virtio-mmio-bindings.py) stays blocked until a real
observation exists. Nothing here is a substitute for that observation.
"""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
source = ROOT / 'refer/IOStorageFamily'
revision = subprocess.check_output(['git', '-C', source, 'rev-parse', 'HEAD'], text=True).strip()
if revision != 'e45fbe30a7879e0b16e26dddb78538f1b00e0bff':
    raise SystemExit('Unexpected public Darwin 23 IOStorageFamily source')
out = ROOT / 'build/storage-abi'
headers = out / 'include/IOKit/storage'
headers.mkdir(parents=True, exist_ok=True)
copied = {}
for path in sorted(source.glob('*.h')):
    shutil.copyfile(path, headers / path.name)
    copied[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
if not copied:
    raise SystemExit('No IOStorageFamily headers at the pinned revision')
sdk = Path(subprocess.check_output(['xcrun', '--sdk', 'macosx', '--show-sdk-path'], text=True).strip())
conditions = sdk / 'usr/include/TargetConditionals.h'
shutil.copyfile(conditions, out / 'include/TargetConditionals.h')
(out / 'headers.json').write_text(json.dumps(dict(
    public_source_revision=revision, headers=copied,
    target_conditionals_sha256=hashlib.sha256(conditions.read_bytes()).hexdigest(),
    live_abi_qualified=False, interface_audit_written=False), indent=2) + '\n')
print(f'storage ABI headers: {len(copied)} IOStorageFamily headers at {revision[:12]} (no live audit; interface-audit.json not written)')
