#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# CI-ONLY firmware for build tests. These are THIRD-PARTY copies, not the owner's tablet's files:
#   linux-firmware (redistributable, LICENSE.qcom): qcom/a650_sqe.fw, qcom/a650_gmu.bin
#   pipa-mainline/xiaomi-pipa-firmware (proprietary, extracted from a pipa by that project): a650_zap.mbn, nt36532_tianma.bin
# Nothing built with them is uploaded. Digests are written to $1/CI-FIRMWARE.sha256 so a later comparison with the owner's
# own files (pipa.ps1 firmware) shows whether they are the same.
set -euo pipefail
cache=${1:?usage: fetch-ci-firmware.sh <cache dir>}
LINUX_FIRMWARE_TAG=${LINUX_FIRMWARE_TAG:-20250509}
PIPA_FW_COMMIT=${PIPA_FW_COMMIT:-842d35beffeda8c6d1b0e611b335543bf0e6b41e}
sha256() { if command -v sha256sum >/dev/null; then sha256sum "$@"; else shasum -a 256 "$@"; fi; }
get() {  # get <url> <dest>
  mkdir -p "$(dirname "$2")"
  rm -f "$2.part"
  curl -fsSL --retry 3 --retry-delay 5 -o "$2.part" "$1" || { echo "::error::download failed: $1"; rm -f "$2.part"; exit 1; }
  [ -s "$2.part" ] || { echo "::error::empty download: $1"; exit 1; }
  mv "$2.part" "$2"
}
lf=https://gitlab.com/kernel-firmware/linux-firmware/-/raw/$LINUX_FIRMWARE_TAG/qcom
pf=https://raw.githubusercontent.com/pipa-mainline/xiaomi-pipa-firmware/$PIPA_FW_COMMIT/lib/firmware
get "$lf/a650_sqe.fw" "$cache/linux-firmware/a650_sqe.fw"
get "$lf/a650_gmu.bin" "$cache/gpu/a650_gmu.bin"
get "$pf/sm8250/xiaomi/pipa/a650_zap.mbn" "$cache/gpu/a650_zap.elf"
# The reference unit's panel pairs with the _tm (Tianma) image; a CSOT panel needs nt36532_csot.bin instead.
get "$pf/novatek/nt36532_tianma.bin" "$cache/touch/novatek_nt36532_m82_fw_tm.bin"
# The ELF magic must be there (a zap .mbn is a squashed ELF with its hash segment).
[ "$(head -c4 "$cache/gpu/a650_zap.elf" | od -An -tx1 | tr -d ' ')" = "7f454c46" ] || { echo "::error::a650_zap.mbn is not an ELF"; exit 1; }
(cd "$cache" && find . -type f ! -name CI-FIRMWARE.sha256 -print0 | sort -z | xargs -0 shasum -a 256 2>/dev/null || find . -type f ! -name CI-FIRMWARE.sha256 -print0 | sort -z | xargs -0 sha256sum) > "$cache/CI-FIRMWARE.sha256"
{ echo "# linux-firmware $LINUX_FIRMWARE_TAG, pipa-mainline/xiaomi-pipa-firmware $PIPA_FW_COMMIT"; cat "$cache/CI-FIRMWARE.sha256"; }
