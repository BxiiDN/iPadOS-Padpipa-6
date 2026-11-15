#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# UEFI FD reproducibility: build A and B in the same work path (B after deleting Build/), then C in a second path, all
# from the pinned sources with PYTHONHASHSEED=0 (see docs/REPRODUCIBILITY.md). Writes <out>/report/: hashes, toolchain,
# pins, and for any difference the list of differing FFS files. The FD itself is NOT copied to the report: it embeds the
# proprietary Device-Binaries UEFI drivers.
#   scripts/ci/firmware-repro.sh <out dir>
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
out=${1:?out dir}
rep=$out/report
mkdir -p "$rep"
export PYTHONHASHSEED=0
fd_rel=Build/pipaPkg/DEBUG_CLANGPDB/FV/SILICIUM_UEFI.fd
{ uname -a; clang --version | head -n1; ld.lld --version; lld-link --version 2>/dev/null || true; nasm -v; python3 --version; python3 -c "import zlib; print('zlib', zlib.ZLIB_RUNTIME_VERSION)"; } > "$rep/toolchain.txt" 2>&1
cp "$ROOT/manifest/sources.lock.toml" "$rep/"

build() {  # build <work> <label>
  local w=$1 label=$2
  export UNIXNU_UEFI=$w/uefi-pipa
  rm -rf "$UNIXNU_UEFI/Build"
  (cd "$w/UniXNU" && ./unixnu fetch -D ../UniXNU-pipa && ./unixnu defconfig pipa_defconfig -D ../UniXNU-pipa &&
     ./unixnu build firmware -D ../UniXNU-pipa) > "$rep/firmware-$label.log" 2>&1 ||
    { echo "::error::firmware build $label failed"; tail -40 "$rep/firmware-$label.log"; exit 1; }
  sha256sum "$UNIXNU_UEFI/$fd_rel" | sed "s|$UNIXNU_UEFI/||; s|\$| ($label)|" >> "$rep/fd-sha256.txt"
  (cd "$UNIXNU_UEFI/Build/pipaPkg/DEBUG_CLANGPDB/FV/Ffs" && find . -name '*.ffs' | sort | xargs sha256sum) > "$rep/ffs-$label.txt"
}
# The canonical path: the same on every machine, so a hash can be compared across hosts (docs/REPRODUCIBILITY.md).
P1=${PIPA_FW_PATH:-/tmp/pipa-fw/work}
P2=${PIPA_FW_ALT_PATH:-/tmp/pipa-fw-alt/work}
python3 "$ROOT/tools/bootstrap.py" --work "$P1"
build "$P1" A
build "$P1" B
python3 "$ROOT/tools/bootstrap.py" --work "$P2"
build "$P2" C
cut -d' ' -f1 "$rep/fd-sha256.txt" | sort -u > "$rep/distinct.txt"
for l in B C; do diff "$rep/ffs-A.txt" "$rep/ffs-$l.txt" > "$rep/ffs-diff-A-$l.txt" || true; done
# The stage-1 image from the canonical-path FD (UEFI + UniXNU menu only: NOT an iPadOS image).
export UNIXNU_UEFI=$P1/uefi-pipa
# Rebuild A's FD in place: build C replaced the environment, not P1's Build/.
(cd "$P1/UniXNU" && ./unixnu bootimg -D ../UniXNU-pipa --dtb "$P1/uefi-pipa/Resources/DTBs/pipa.dtb" --ramdisk none) > "$rep/bootimg-stage1.log" 2>&1
python3 "$ROOT/tools/checks/check_bootimg.py" "$P1/UniXNU/out/pipa/boot/boot.img" --stage1 --json "$rep/check-boot-stage1.json"
cp "$P1/UniXNU/out/pipa/boot/boot.json" "$rep/boot-stage1.json"
cat "$rep/toolchain.txt"; cat "$rep/boot-stage1.json"   # in the job log: the artifact is not reachable from every host
cat "$rep/fd-sha256.txt"
a=$(sed -n 1p "$rep/fd-sha256.txt" | cut -d' ' -f1); b=$(sed -n 2p "$rep/fd-sha256.txt" | cut -d' ' -f1); c=$(sed -n 3p "$rep/fd-sha256.txt" | cut -d' ' -f1)
if [ "$a" != "$b" ]; then echo "::error::two builds in the same path differ: NOT reproducible (ffs-diff-A-B.txt)"; exit 1; fi
echo "REPRODUCIBLE in $P1 (A = B = $a)"
if [ "$a" = "$c" ]; then echo "path-independent: C in $P2 is identical too"
else echo "::warning::C in $P2 differs ($(wc -l < "$rep/ffs-diff-A-C.txt") diff lines): absolute paths in DEBUG asserts and PDB names (docs/REPRODUCIBILITY.md)"; fi
