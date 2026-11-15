#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# The pipa kernel step on a macOS runner with Xcode, as far as the PUBLIC inputs reach. Each step's exit code goes to
# <out>/report/steps.tsv; the run ends with the first failing unixnu step and says which input was missing. Nothing
# derived from Apple software or proprietary firmware is copied to the report (only logs and SHA-256 values).
#   scripts/ci/kernel-attempt.sh <out dir>
set -uo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
out=${1:?out dir}
rep=$out/report
work=$out/work
mkdir -p "$rep"
: > "$rep/steps.tsv"
step() {  # step <name> <command...>; returns the command's status
  local name=$1; shift
  echo "::group::$name"
  "$@" > "$rep/$name.log" 2>&1
  local rc=$?
  tail -60 "$rep/$name.log"
  echo "::endgroup::"
  printf '%s\t%s\n' "$name" "$rc" >> "$rep/steps.tsv"
  [ $rc -eq 0 ] || echo "::error::step $name failed ($rc): $(grep -iE 'error|missing|require|traceback' "$rep/$name.log" | tail -n 3 | tr '\n' ' ')"
  return $rc
}
unixnu() { (cd "$work/UniXNU" && ./unixnu "$@" -D ../UniXNU-pipa); }
export UNIXNU_UEFI=$work/uefi-pipa
step bootstrap python3 "$ROOT/tools/bootstrap.py" --work "$work" || exit 1
python3 "$ROOT/tools/unitfacts.py" from-dtb "$UNIXNU_UEFI/Resources/DTBs/pipa.dtb" -o "$rep/unit-facts.stock.json"
step board python3 "$ROOT/tools/pipa_board.py" --upstream "$work/UniXNU-pipa/board.upstream.toml" --facts "$rep/unit-facts.stock.json" \
  --overlay "$ROOT/device/pipa-8g256/overlay.toml" -o "$work/UniXNU-pipa/board.toml" --report "$rep/board-report.json" || exit 1
step ci-firmware "$ROOT/scripts/ci/fetch-ci-firmware.sh" "$work/UniXNU-pipa/.cache/firmware" || exit 1
step fetch unixnu fetch || exit 1
step defconfig unixnu defconfig pipa_defconfig || exit 1
step tree unixnu tree || exit 1
tree=$work/UniXNU/out/pipa/tree
# The two README inputs that public sources can satisfy: the empty libsa header directory and the storage ABI audit.
mkdir -p "$tree/build/xnu/ios-obj/EXPORT_HDRS/libsa"
url=$(python3 -c "import tomllib,sys;print(tomllib.load(open(sys.argv[1],'rb'))['ipsw']['url'])" "$work/UniXNU-pipa/board.toml")
export UNIXNU_IPSW=$url
step ipsw unixnu ipsw fetch || exit 1
step storage-audit bash -c "cd '$tree' && python3 scripts/audit-storage-interface.py"
step inputs python3 "$ROOT/tools/check_inputs.py" --work "$work" --tree "$tree" --json "$rep/missing-inputs.json"
step kernel unixnu build kernel
rc=$?
find "$work/UniXNU/out/pipa" -name 'kernel.macho' -o -name '*.unstripped*' 2>/dev/null | while read -r f; do
  printf '%s  %s\n' "$(shasum -a 256 "$f" | cut -d' ' -f1)" "${f#$work/}"; done > "$rep/kernel-outputs.sha256"
find "$tree/build" -name '*.a' 2>/dev/null | sort | while read -r f; do
  printf '%s  %s\n' "$(shasum -a 256 "$f" | cut -d' ' -f1)" "${f#$tree/}"; done > "$rep/archives.sha256"
cat "$rep/steps.tsv"
exit $rc
