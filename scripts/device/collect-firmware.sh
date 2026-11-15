#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Copy the proprietary firmware the first image needs FROM THE OWNER'S OWN TABLET (booted into Android) into
# .cache/firmware/, read-only over adb, and print SHA-256 digests to pin in manifest/firmware.toml.
# Nothing is written to the tablet. Run from WSL2 or any host with adb; on Windows use scripts/windows/pipa.ps1 firmware.
#
#   scripts/device/collect-firmware.sh [cache-dir]          (default: .cache/firmware)
#
# Not covered here: the Novatek touch image (inside the stock kernel's built-in table: extract it from boot.img's kernel
# with the vendor tool of your choice) and linux-firmware's a650_sqe.fw (download qcom/a650_sqe.fw from git.kernel.org).
set -euo pipefail
cache=${1:-.cache/firmware}
adb=${ADB:-adb}
"$adb" get-state >/dev/null 2>&1 || { echo "no adb device in Android mode" >&2; exit 2; }
product=$("$adb" shell getprop ro.product.device | tr -d '\r')
[ "$product" = "pipa" ] || { echo "device is '$product', not pipa" >&2; exit 2; }

pull() {  # pull <device path> <cache subpath>
  local src=$1 dst=$cache/$2
  mkdir -p "$(dirname "$dst")"
  if "$adb" pull "$src" "$dst" >/dev/null 2>&1; then
    printf '%s  %s  <- %s\n' "$(sha256sum "$dst" | cut -d' ' -f1)" "$2" "$src"
  else
    echo "MISSING  $2  <- $src (try: adb shell su -c 'cat $src' > $dst)" >&2
  fi
}
for f in a650_gmu.bin a650_zap.elf a650_zap.mdt a650_zap.b00 a650_zap.b01 a650_zap.b02; do
  pull "/vendor/firmware/$f" "gpu/$f"
done
for f in aw882xx_acf.bin; do pull "/vendor/firmware/$f" "audio/$f"; done
for f in amss.bin m3.bin regdb.bin bdwlan.bin; do pull "/vendor/firmware/$f" "wifi/$f"; done
echo "fingerprint: $("$adb" shell getprop ro.build.fingerprint | tr -d '\r')"
echo "Pin these digests in manifest/firmware.toml, then: python3 tools/checks/check_firmware.py --manifest manifest/firmware.toml --cache $cache"
