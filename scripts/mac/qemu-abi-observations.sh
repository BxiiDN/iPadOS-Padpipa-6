#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# The two LIVE observations the pipa kernel needs, produced the way UniXNU-qemu does it (README of 97b75b1f):
#   storage ABI   UniXNU-qemu scripts/build-storage-abi.py   -> build/storage-abi/interface-audit.json
#                 (boots the qemu_defconfig kernel in QEMU once under UniXNU's gdb-stop.py and runs audit-storage-interface.py)
#   display ABI   UniXNU-qemu scripts/build-display-abi.py   -> the PIPA_DISPLAY_REFERENCE tree
#                 (build/xnu-prelink/native-owner-mobile-graphics-candidate.macho + build/darwinboot-owner-hvf-*/gdb-stop.json)
# Needs macOS with Xcode and Homebrew QEMU. --accel hvf needs Apple silicon with Hypervisor.framework
# (sysctl kern.hv_support = 1); --accel tcg runs anywhere but is NOT treated as equivalent: the accelerator is recorded in
# observations.json and an "hvf"-named observation produced under TCG is refused, never renamed.
#
#   scripts/mac/qemu-abi-observations.sh --accel hvf --work /path/work [--out /path/obs]
# Then, for the pipa build:  PIPA_DISPLAY_REFERENCE=<out>/qemu-tree  and copy <out>/interface-audit.json into the pipa tree
# (scripts/wsl/build.sh does both when PIPA_QEMU_OBSERVATIONS=<out> is set). Nothing in this script writes a value by hand.
# Status: written from the UniXNU-qemu README and the consumers' checks; NOT run yet (no Mac in the CI used so far).
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
accel="" work="" out=""
while [ $# -gt 0 ]; do case $1 in --accel) accel=$2; shift 2;; --work) work=$2; shift 2;; --out) out=$2; shift 2;; *) echo "unknown $1"; exit 2;; esac; done
[ "$(uname -s)" = Darwin ] || { echo "macOS only (Xcode kernel step, QEMU with gdb stub)"; exit 2; }
case $accel in
  hvf) [ "$(sysctl -n kern.hv_support 2>/dev/null)" = 1 ] || { echo "no Hypervisor.framework here; use --accel tcg explicitly"; exit 2; };;
  tcg) echo "TCG: slower, and not equivalent to HVF; the accelerator is recorded with the results";;
  *) echo "--accel hvf|tcg required"; exit 2;;
esac
work=${work:-$ROOT/work-qemu}; out=${out:-$ROOT/out/qemu-observations}
mkdir -p "$work" "$out"
QEMU_DEVICE_COMMIT=97b75b1f63c6b7e895cd7646029db741d5fe5488
command -v qemu-system-aarch64 >/dev/null || brew install qemu
python3 "$ROOT/tools/bootstrap.py" --work "$work" --only UniXNU
if [ ! -d "$work/UniXNU-qemu/.git" ]; then
  git init -q "$work/UniXNU-qemu"; git -C "$work/UniXNU-qemu" remote add origin https://github.com/xVanTuring/UniXNU-qemu
fi
git -C "$work/UniXNU-qemu" fetch -q --depth 1 origin "$QEMU_DEVICE_COMMIT"
git -C "$work/UniXNU-qemu" checkout -q --force "$QEMU_DEVICE_COMMIT"
git -C "$work/UniXNU-qemu" submodule update --init --depth 1
cd "$work/UniXNU"
export UNIXNU_QEMU_ACCEL=$accel
./unixnu fetch -D ../UniXNU-qemu
./unixnu defconfig qemu_defconfig -D ../UniXNU-qemu
./unixnu build kernel -D ../UniXNU-qemu
tree=$work/UniXNU/out/qemu/tree
(cd "$tree" && python3 scripts/build-storage-abi.py)
(cd "$tree" && python3 scripts/build-display-abi.py)
audit=$tree/build/storage-abi/interface-audit.json
cand=$tree/build/xnu-prelink/native-owner-mobile-graphics-candidate.macho
obs=$tree/build/darwinboot-owner-hvf-mobile-graphics-legacy-class/gdb-stop.json
for f in "$audit" "$cand" "$obs"; do [ -s "$f" ] || { echo "missing output $f"; exit 1; }; done
# The display observation's directory says "hvf": refuse one taken under TCG instead of passing it off as HVF.
[ "$accel" = hvf ] || { echo "REFUSED: $obs was produced with --accel $accel; the pipa display builder expects an HVF observation"; exit 3; }
cp "$audit" "$out/interface-audit.json"
rm -rf "$out/qemu-tree"; mkdir -p "$out/qemu-tree/build"
cp -R "$tree/build/xnu-prelink" "$tree/build/darwinboot-owner-hvf-mobile-graphics-legacy-class" "$out/qemu-tree/build/"
python3 - "$out" "$accel" "$QEMU_DEVICE_COMMIT" <<'EOF'
import hashlib, json, os, sys, platform
out, accel, commit = sys.argv[1:]
files = {}
for root, _d, names in os.walk(out):
    for n in names:
        if n != "observations.json":
            p = os.path.join(root, n)
            files[os.path.relpath(p, out)] = hashlib.sha256(open(p, "rb").read()).hexdigest()
json.dump({"accel": accel, "uniXNU_qemu_commit": commit, "host": platform.platform(), "machine": platform.machine(),
           "files": files}, open(os.path.join(out, "observations.json"), "w"), indent=2)
print(f"observations ({accel}) in {out}: {len(files)} files")
EOF
