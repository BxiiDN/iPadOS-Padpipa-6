#!/system/bin/sh
# SPDX-License-Identifier: MIT
# Runs ON the tablet under Android (adb shell sh -s < collect-unit-facts.sh). READ-ONLY: it writes nothing to the tablet
# and changes no setting. Prints key=value lines that tools/unitfacts.py from-adb turns into unit-facts.json.
#
# Without root some values cannot be read (Android's SELinux policy); the script says which in errors=. With Magisk or
# another su, run: adb shell su -c 'sh -s' < collect-unit-facts.sh
COLLECTOR_VERSION=1
errors=""
note() { errors="$errors $1"; }

echo "# iPadOS-Padpipa-6 unit facts, collector v$COLLECTOR_VERSION"
echo "collector_version=$COLLECTOR_VERSION"
echo "collected_at=$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null)"
[ "$(id -u)" = "0" ] && echo "root=1" || echo "root=0"

for p in ro.product.device ro.product.vendor.device ro.product.model ro.build.fingerprint ro.boot.hwc ro.boot.hwversion \
         ro.boot.slot_suffix ro.boot.bootdevice ro.board.platform; do
  echo "$p=$(getprop $p)"
done
# The serial identifies the tablet; only its hash is kept.
s=$(getprop ro.serialno)
[ -n "$s" ] && echo "serial_sha256=$(printf %s "$s" | sha256sum 2>/dev/null | cut -d' ' -f1)"

# Memory: MemTotal is always readable; the DT /memory reg (what ABL wrote) usually needs root.
echo "mem_total_kib=$(awk '/^MemTotal:/ {print $2}' /proc/meminfo)"
reg=""
for f in /sys/firmware/devicetree/base/memory/reg /proc/device-tree/memory/reg; do
  if [ -r "$f" ]; then reg=$(od -An -tx1 -v "$f" 2>/dev/null | tr -d ' \n'); [ -n "$reg" ] && break; fi
done
[ -n "$reg" ] && echo "dt_memory_reg=$reg" || note "dt_memory_reg"
for f in /sys/firmware/devicetree/base/memory/ddr_device_type; do
  [ -r "$f" ] && echo "ddr_device_type=$(od -An -tx1 -v "$f" | tr -d ' \n')"
done

# Storage: UFS LUN 0 (sda) geometry and every partition's start/size in 512-byte sectors (sysfs, world-readable on most
# builds), plus the by-name links to know which sdaN is userdata.
if [ -r /sys/block/sda/queue/logical_block_size ]; then
  echo "lun0_lba_bytes=$(cat /sys/block/sda/queue/logical_block_size)"
  echo "lun0_size_512=$(cat /sys/block/sda/size)"
else
  note "sda_queue"
fi
for f in vendor model rev; do
  [ -r /sys/block/sda/device/$f ] && echo "ufs_$f=$(cat /sys/block/sda/device/$f | tr -s ' ')"
done
byname=""
for d in /dev/block/by-name /dev/block/bootdevice/by-name /dev/block/platform/soc/1d84000.ufshc/by-name; do
  [ -d "$d" ] && { byname=$d; break; }
done
for part in /sys/block/sd?/sd??*; do
  [ -r "$part/start" ] || continue
  dev=${part##*/}
  name=""
  if [ -n "$byname" ]; then
    for l in "$byname"/*; do
      t=$(readlink "$l" 2>/dev/null)
      [ "${t##*/}" = "$dev" ] && { name=${l##*/}; break; }
    done
  fi
  [ -z "$name" ] && [ -r "$part/uevent" ] && name=$(sed -n 's/^PARTNAME=//p' "$part/uevent")
  echo "part=$dev|$name|$(cat $part/start)|$(cat $part/size)"
done

# Panel and touch: the panel name selects the touch firmware image (_tm for maker 0x36 on the reference unit).
panel=""
[ -r /proc/cmdline ] && panel=$(tr ' ' '\n' < /proc/cmdline | sed -n 's/^msm_drm.dsi_display0=//p' | cut -d: -f1)
[ -z "$panel" ] && panel=$(dumpsys SurfaceFlinger 2>/dev/null | sed -n 's/.*\(mdss_dsi_[A-Za-z0-9_]*\).*/\1/p' | head -n1)
[ -n "$panel" ] && echo "panel=$panel" || note "panel"
for f in /sys/devices/virtual/touch/touch_dev/panel_vendor /sys/class/touch/touch_dev/panel_vendor; do
  [ -r "$f" ] && echo "touch_panel_vendor=$(cat $f)"
done

# GPU (chip id is checked by UniXNU-pipa's GpuProbe: 0x06050002)
[ -r /sys/class/kgsl/kgsl-3d0/gpu_model ] && echo "gpu_model=$(cat /sys/class/kgsl/kgsl-3d0/gpu_model)"

echo "errors=$errors"
