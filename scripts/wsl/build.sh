#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Build steps inside WSL2 (Ubuntu 24.04) or any Linux host. Windows users call it through scripts/windows/pipa.ps1.
#
#   scripts/wsl/build.sh setup        one time: apt packages + UniXNU's Linux Mach-O toolchain (sudo, hours: builds LLVM)
#   scripts/wsl/build.sh bootstrap    pinned checkouts under work/ (tools/bootstrap.py)
#   scripts/wsl/build.sh board        board.toml for THIS unit from device/pipa-8g256/unit-facts.json (tools/pipa_board.py)
#   scripts/wsl/build.sh firmware     the UEFI FD (Mu-Silicium pipaPkg + UniXNU + DarwinBoot)
#   scripts/wsl/build.sh stage1       boot.img with the firmware only (UniXNU menu, no payload)
#   scripts/wsl/build.sh kernel       XNU + archives (needs the toolchain and the local IPSW: UNIXNU_IPSW)
#   scripts/wsl/build.sh payload      payload volume + boot.img (needs UNIXNU_UNIQUE_CHIP_ID or .cache/platform-seed)
#   scripts/wsl/build.sh userdata     userdata root image: REFUSED unless the unit's GPT was measured
#   scripts/wsl/build.sh check        every static gate (board, memory, firmware, boot image, no blobs in Git)
#   scripts/wsl/build.sh all          bootstrap board firmware stage1 check (what works without the IPSW/toolchain)
#
# Outputs: out/ (images, checksums), logs/build-<step>-<time>.log
set -euo pipefail
ROOT=$(cd "$(dirname "$0")/../.." && pwd)
WORK=${WORK:-$ROOT/work}
UNIT=${UNIT:-pipa-8g256}
FACTS=${FACTS:-$ROOT/device/$UNIT/unit-facts.json}
OVERLAY=$ROOT/device/$UNIT/overlay.toml
OUT=$ROOT/out/$UNIT
LOGS=$ROOT/logs
export UNIXNU_UEFI=$WORK/uefi-pipa
# EDK2 BaseTools orders PCD flag expressions through Python sets: fixed hashing makes AutoGen.c, and the FD, stable.
export PYTHONHASHSEED=0
# Path normalization that keeps file names and ASSERT locations (docs/REPRODUCIBILITY.md): clang maps the work root to
# \pipa in __FILE__ and debug info; lld-link stores only the PDB file name.
export CCC_OVERRIDE_OPTIONS="# +-ffile-prefix-map=$WORK=/pipa"
export _LINK_='/pdbaltpath:%_PDB% /Brepro'
# Pinned compressor for boot.img (unixnu bootimg.py gzip): classic zlib 1.3 as on Ubuntu 24.04 (zlib-ng differs).
PIPA_ZLIB=${PIPA_ZLIB:-1.3}
mkdir -p "$OUT" "$LOGS"
stamp=$(date -u +%Y%m%dT%H%M%SZ)

log_run() {  # log_run <step> <command...>
  local step=$1; shift
  local log=$LOGS/build-$step-$stamp.log
  echo "== $step ($(date -u +%FT%TZ)) -> $log"
  { echo "# $*"; echo "# host: $(uname -a)"; } > "$log"
  if "$@" >> "$log" 2>&1; then echo "   ok"; else echo "   FAILED (tail of $log):"; tail -20 "$log"; return 1; fi
}

unixnu() { (cd "$WORK/UniXNU" && ./unixnu "$@" -D "$WORK/UniXNU-pipa"); }

facts_or_stock() {
  if [ -f "$FACTS" ]; then echo "$FACTS"; return; fi
  echo "WARNING: $FACTS missing: using the stock DTB's memory banks (build only, never flash)" >&2
  python3 "$ROOT/tools/unitfacts.py" from-dtb "$UNIXNU_UEFI/Resources/DTBs/pipa.dtb" -o "$OUT/unit-facts.stock.json" >&2
  echo "$OUT/unit-facts.stock.json"
}

step_setup() {
  sudo apt-get update
  sudo apt-get install -y git python3 python3-venv mtools device-tree-compiler nasm \
    acpica-tools uuid-dev build-essential
  [ -d "$WORK/UniXNU" ] || step_bootstrap
  sudo python3 "$WORK/UniXNU/scripts/linux/setup-toolchain.py"
}
step_bootstrap() { log_run bootstrap python3 "$ROOT/tools/bootstrap.py" --work "$WORK"; }
step_board() {
  local facts; facts=$(facts_or_stock)
  log_run board python3 "$ROOT/tools/pipa_board.py" --upstream "$WORK/UniXNU-pipa/board.upstream.toml" \
    --facts "$facts" --overlay "$OVERLAY" -o "$WORK/UniXNU-pipa/board.toml" --report "$OUT/board-report.json"
  git -C "$WORK/UniXNU-pipa" diff --no-color -- board.toml > "$OUT/board.diff" || true
  log_run board-check python3 "$ROOT/tools/checks/check_board.py" --board "$WORK/UniXNU-pipa/board.toml" --facts "$facts" \
    --json "$OUT/check-board.json"
}
step_firmware() {
  log_run fetch unixnu fetch
  log_run defconfig unixnu defconfig pipa_defconfig
  log_run firmware unixnu build firmware
  cp "$UNIXNU_UEFI/Build/pipaPkg/DEBUG_CLANGPDB/FV/SILICIUM_UEFI.fd" "$OUT/SILICIUM_UEFI.fd"
}
check_zlib() {
  local z; z=$(python3 -c 'import zlib; print(zlib.ZLIB_RUNTIME_VERSION)')
  [ "$z" = "$PIPA_ZLIB" ] || { echo "REFUSED: python3 zlib is $z, pinned $PIPA_ZLIB (set PIPA_ZLIB=$z to build anyway; the image will differ)"; exit 2; }
}
step_stage1() {
  check_zlib
  log_run bootimg-stage1 unixnu bootimg --dtb "$UNIXNU_UEFI/Resources/DTBs/pipa.dtb" --ramdisk none
  cp "$WORK/UniXNU/out/pipa/boot/boot.img" "$OUT/boot-stage1.img"
  cp "$WORK/UniXNU/out/pipa/boot/boot.json" "$OUT/boot-stage1.json"
  log_run bootimg-check python3 "$ROOT/tools/checks/check_bootimg.py" "$OUT/boot-stage1.img" --stage1 --json "$OUT/check-boot-stage1.json"
}
export_kernel_env() {
  export PIPA_OWNER_ANCHOR=${PIPA_OWNER_ANCHOR:-$ROOT/.cache/owner-key/owner.anchor}
  [ -f "$PIPA_OWNER_ANCHOR" ] || { echo "no owner anchor: run 'python3 tools/owner_key.py init' once (the private key stays in .cache/owner-key)"; exit 2; }
  eval "$(python3 -c "import tomllib,sys;u=tomllib.load(open(sys.argv[1],'rb'))['userdata'];print(f'export PIPA_UFS_USERDATA_FIRST={u[\"first_lba\"]:#x} PIPA_UFS_USERDATA_LAST={u[\"last_lba\"]:#x}')" "$WORK/UniXNU-pipa/board.toml")"
}
use_qemu_observations() {
  # Live ABI observations from scripts/mac/qemu-abi-observations.sh (never written by hand).
  local o=${PIPA_QEMU_OBSERVATIONS:-}
  [ -n "$o" ] || return 0
  [ -f "$o/observations.json" ] || { echo "PIPA_QEMU_OBSERVATIONS=$o has no observations.json"; exit 2; }
  python3 "$ROOT/tools/check_observations.py" "$o"
  mkdir -p "$WORK/UniXNU/out/pipa/tree/build/storage-abi"
  cp "$o/interface-audit.json" "$WORK/UniXNU/out/pipa/tree/build/storage-abi/interface-audit.json"
  export PIPA_DISPLAY_REFERENCE=$o/qemu-tree
}
step_kernel() {
  export_kernel_env
  use_qemu_observations
  : "${UNIXNU_IPSW:?set UNIXNU_IPSW to your local iPad_Pro_HFR_17.7.11_21H461_Restore.ipsw or the official URL}"
  export UNIXNU_IPSW
  case $UNIXNU_IPSW in
    https://updates.cdn-apple.com/*) echo "IPSW: official URL (members read by HTTP range; unixnu checks the pinned digests)";;
    http*) echo "REFUSED: only Apple's update CDN or a local file"; exit 2;;
    *) log_run ipsw-check python3 "$ROOT/tools/check_ipsw.py" --board "$WORK/UniXNU-pipa/board.toml" --ipsw "$UNIXNU_IPSW";;
  esac
  log_run kernel-inputs python3 "$ROOT/tools/check_inputs.py" --work "$WORK" --tree "$WORK/UniXNU/out/pipa/tree" --json "$OUT/missing-inputs.json"
  log_run ipsw unixnu ipsw fetch
  log_run kernel unixnu build kernel
  log_run firmware-check python3 "$ROOT/tools/checks/check_firmware.py" --manifest "$ROOT/manifest/firmware.toml" \
    --cache "$WORK/UniXNU-pipa/.cache/firmware" --stage gpu --json "$OUT/check-firmware.json"
  local tree=$WORK/UniXNU/out/pipa/tree
  # The kernel the prelink step reads (UniXNU-pipa board.toml [kernel.prelink] kernel).
  log_run symbols python3 "$ROOT/tools/checks/check_symbols.py" \
    --kernel "$tree/build/xnu/ios-obj/DEVELOPMENT_ARM64_BCM2837/mach.development.bcm2837.unstripped.noctf" \
    --archive "$tree/build/**/*.a" --json "$OUT/check-symbols.json"
}
step_payload() {
  local seed=${UNIXNU_UNIQUE_CHIP_ID:-$(cat "$ROOT/.cache/platform-seed" 2>/dev/null || true)}
  [ -n "$seed" ] || { echo "set UNIXNU_UNIQUE_CHIP_ID (16 hex digits, e.g. openssl rand -hex 8) or .cache/platform-seed"; exit 2; }
  log_run payload unixnu build payload --unique-chip-id "$seed"
  log_run bootimg unixnu bootimg --dtb "$UNIXNU_UEFI/Resources/DTBs/pipa.dtb"
  cp "$WORK/UniXNU/out/pipa/boot/boot.img" "$OUT/boot.img"
  log_run bootimg-check python3 "$ROOT/tools/checks/check_bootimg.py" "$OUT/boot.img" --json "$OUT/check-boot.json"
}
step_userdata() {
  python3 - "$FACTS" <<'EOF' || { echo "REFUSED: measure this unit's GPT first (pipa.ps1 collect)"; exit 3; }
import sys; sys.path.insert(0, "tools"); import unitfacts
p = unitfacts.problems(unitfacts.load(sys.argv[1]), need_storage=True)
print("\n".join(p)); sys.exit(1 if p else 0)
EOF
  log_run userdata unixnu build userdata
}
step_check() {
  local facts; facts=$(facts_or_stock)
  log_run check-board python3 "$ROOT/tools/checks/check_board.py" --board "$WORK/UniXNU-pipa/board.toml" --facts "$facts"
  log_run check-memory python3 "$ROOT/tools/checks/check_memory.py" \
    --memmap "$UNIXNU_UEFI/Platforms/Xiaomi/pipaPkg/Library/MemoryMapLib/MemoryMapLib.c" \
    --dtb "$UNIXNU_UEFI/Resources/DTBs/pipa.dtb" --facts "$facts" --board "$WORK/UniXNU-pipa/board.toml" --json "$OUT/check-memory.json"
  log_run check-blobs python3 "$ROOT/tools/checks/check_firmware.py" --manifest "$ROOT/manifest/firmware.toml" --scan-repo "$ROOT"
  [ -f "$OUT/boot-stage1.img" ] && log_run check-stage1 python3 "$ROOT/tools/checks/check_bootimg.py" "$OUT/boot-stage1.img" --stage1
  [ -f "$OUT/boot.img" ] && log_run check-boot python3 "$ROOT/tools/checks/check_bootimg.py" "$OUT/boot.img"
  (cd "$OUT" && sha256sum ./*.img ./*.fd 2>/dev/null > SHA256SUMS || true)
  echo "checksums: $OUT/SHA256SUMS"
}

case "${1:-}" in
  setup) step_setup ;;
  bootstrap) step_bootstrap ;;
  board) step_board ;;
  firmware) step_firmware ;;
  stage1) step_stage1 ;;
  kernel) step_kernel ;;
  payload) step_payload ;;
  userdata) step_userdata ;;
  check) step_check ;;
  all) step_bootstrap; step_board; step_firmware; step_stage1; step_check ;;
  *) sed -n '3,16p' "$0"; exit 2 ;;
esac
