#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Upstream pipa driver host tests (UniXNU-pipa package/*Tests.c). The GMU test needs a little-endian AArch64 host
# (AdrenoHfi.c #error); on x86_64 it is reported as SKIPPED with that reason, never as passed.
#   scripts/ci/host-tests.sh <work dir with UniXNU and UniXNU-pipa>
set -uo pipefail
work=${1:?work dir}
pkg=$work/UniXNU-pipa/package
kit=$work/UniXNU/kits/AdrenoFirmware
cc=${CC:-cc}
fail=0
echo "# host $(uname -sm), $($cc --version | head -n1)"
echo "# UniXNU-pipa $(git -C "$work/UniXNU-pipa" rev-parse --short HEAD), AdrenoFirmware $(git -C "$kit" rev-parse --short HEAD 2>/dev/null || echo missing)"
tmp=$(mktemp -d)
for t in TouchBoardTests NativeBatteryTests ButtonsTests GpuPowerBoardTests GesturesTests; do
  if $cc -std=c11 -Wall -Wextra -Werror -I "$pkg" "$pkg/$t.c" -o "$tmp/$t" && "$tmp/$t"; then echo "PASS  $t"
  else echo "FAIL  $t"; fail=1; fi
done
if [ "$(uname -m)" = aarch64 ] || [ "$(uname -m)" = arm64 ]; then
  if $cc -std=c11 -Wall -Wextra -Werror -I "$kit" -I "$pkg" "$pkg/A650Gmu.c" "$pkg/A650GmuTests.c" \
       "$kit/AdrenoFirmware.c" "$kit/AdrenoHfi.c" "$kit/AdrenoHfiStartup.c" "$kit/AdrenoHfiVotes.c" -o "$tmp/a650" && "$tmp/a650"; then
    echo "PASS  A650GmuTests (synthetic GMU image)"
  else echo "FAIL  A650GmuTests"; fail=1; fi
else
  echo "SKIP  A650GmuTests: AdrenoHfi.c requires a little-endian AArch64 host (this is $(uname -m))"
fi
rm -rf "$tmp"
exit $fail
