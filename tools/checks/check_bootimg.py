#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Validate a pipa boot image before `fastboot boot` (it is never flashed by this project's scripts without consent).

Expected (uefi-pipa Resources/Configs/pipa.toml + UniXNU-pipa board.toml):
  Android boot image header v1, page size 2048, base 0x10000000 (kernel +0x8000, tags +0x100, ramdisk +0x01000000),
  kernel = the Mu-Silicium FD gzip-compressed with the DTB appended, ramdisk = the UniXNU payload volume: a FAT
  volume labelled PIPAESP of at most [payload] size_mib.

    python3 tools/checks/check_bootimg.py out/pipa/boot/boot.img [--volume PIPAESP] [--max-ramdisk-mib 192] [--json r.json]
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import struct
import sys
import zlib

MAGIC = b"ANDROID!"
EXPECT = {"header_version": 1, "page_size": 2048, "base": 0x10000000, "kernel_offset": 0x8000, "tags_offset": 0x100,
          "ramdisk_offset": 0x01000000}


def _pages(n: int, page: int) -> int:
    return (n + page - 1) // page


def parse_header(blob: bytes) -> dict:
    if blob[:8] != MAGIC:
        raise ValueError("not an Android boot image (magic)")
    (kernel_size, kernel_addr, ramdisk_size, ramdisk_addr, second_size, second_addr, tags_addr, page_size,
     header_version, os_version) = struct.unpack_from("<10I", blob, 8)
    h = {"kernel_size": kernel_size, "kernel_addr": kernel_addr, "ramdisk_size": ramdisk_size,
         "ramdisk_addr": ramdisk_addr, "second_size": second_size, "second_addr": second_addr, "tags_addr": tags_addr,
         "page_size": page_size, "header_version": header_version, "os_version": os_version,
         "name": blob[48:64].rstrip(b"\0").decode("ascii", "replace"),
         "cmdline": blob[64:576].rstrip(b"\0").decode("ascii", "replace"),
         "id": blob[576:608]}
    if header_version >= 3:
        raise ValueError(f"header v{header_version} is not the v0..v2 layout pipa's firmware image uses")
    if header_version >= 1:
        h["recovery_dtbo_size"], h["recovery_dtbo_offset"], h["header_size"] = struct.unpack_from("<IQI", blob, 1632)
    return h


def split(blob: bytes, h: dict) -> dict:
    page = h["page_size"]
    off = page  # header occupies one page
    parts = {}
    for name, size in (("kernel", h["kernel_size"]), ("ramdisk", h["ramdisk_size"]), ("second", h["second_size"])):
        parts[name] = blob[off:off + size]
        off += _pages(size, page) * page
    if h["header_version"] >= 1 and h.get("recovery_dtbo_size"):
        parts["recovery_dtbo"] = blob[off:off + h["recovery_dtbo_size"]]
        off += _pages(h["recovery_dtbo_size"], page) * page
    parts["_end"] = off
    return parts


def mkbootimg_id(parts: dict, h: dict) -> bytes:
    """SHA-1 id as AOSP mkbootimg computes it (v0/v1)."""
    s = hashlib.sha1()
    for name in ("kernel", "ramdisk", "second"):
        s.update(parts[name])
        s.update(struct.pack("<I", len(parts[name])))
    if h["header_version"] >= 1:
        s.update(parts.get("recovery_dtbo", b""))
        s.update(struct.pack("<I", len(parts.get("recovery_dtbo", b""))))
    return s.digest()


def gzip_payload_and_tail(kernel: bytes) -> tuple[bytes, bytes]:
    d = zlib.decompressobj(16 + zlib.MAX_WBITS)
    out = d.decompress(kernel)
    out += d.flush()
    if not d.eof:
        raise ValueError("kernel gzip stream is truncated")
    return out, d.unused_data


def fat_label(vol: bytes) -> str | None:
    if len(vol) < 512 or vol[510:512] != b"\x55\xaa":
        return None
    bps = struct.unpack_from("<H", vol, 11)[0]
    if bps not in (512, 1024, 2048, 4096):
        return None
    fat32 = struct.unpack_from("<H", vol, 22)[0] == 0  # sectors per FAT (16-bit) is 0 on FAT32
    off = 0x47 if fat32 else 0x2B
    return vol[off:off + 11].decode("ascii", "replace").rstrip()


def check(blob: bytes, volume: str, max_ramdisk: int, allow_empty_ramdisk: bool = False) -> dict:
    errors, warnings, info = [], [], {}
    try:
        h = parse_header(blob)
    except ValueError as e:
        return {"errors": [str(e)], "warnings": [], "info": {}}
    info.update({k: (hex(v) if isinstance(v, int) else v) for k, v in h.items() if k != "id"})
    if h["header_version"] != EXPECT["header_version"]:
        errors.append(f"header_version {h['header_version']} != {EXPECT['header_version']}")
    if h["page_size"] != EXPECT["page_size"]:
        errors.append(f"page_size {h['page_size']} != {EXPECT['page_size']}")
    for field, off in (("kernel_addr", "kernel_offset"), ("tags_addr", "tags_offset"), ("ramdisk_addr", "ramdisk_offset")):
        if field == "ramdisk_addr" and h["ramdisk_size"] == 0:
            continue  # no ramdisk: the address is not used
        want = EXPECT["base"] + EXPECT[off]
        if h[field] != want:
            errors.append(f"{field} {h[field]:#x} != {want:#x}")
    parts = split(blob, h)
    if parts["_end"] > len(blob):
        errors.append(f"image truncated: sections need {parts['_end']} bytes, file has {len(blob)}")
        return {"errors": errors, "warnings": warnings, "info": info}
    if h["id"][:20] != mkbootimg_id(parts, h):
        warnings.append("header id is not the mkbootimg SHA-1 of the sections (tool other than mkbootimg?)")
    if not parts["kernel"].startswith(b"\x1f\x8b"):
        errors.append("kernel is not gzip (pipa.toml kernel_compression = gzip)")
    else:
        try:
            fd, tail = gzip_payload_and_tail(parts["kernel"])
            # pipa.toml [boot_shim] requires_kernel_header: a small shim precedes the FD. The FD starts 40 bytes before
            # the first firmware-volume signature "_FVH" (EFI_FIRMWARE_VOLUME_HEADER.Signature is at offset 40).
            fvh = fd.find(b"_FVH")
            shim = fvh - 40 if fvh >= 40 else 0
            info["shim_bytes"] = shim
            info["fd_bytes"] = len(fd) - shim
            if fvh < 40:
                errors.append("no EFI firmware volume (_FVH) in the decompressed kernel")
            elif shim > 0x1000:
                errors.append(f"{shim} bytes before the FD: more than a boot shim")
            if b"\xd0\x0d\xfe\xed" not in tail[:16]:
                errors.append("no DTB appended after the gzip kernel (pipa.toml append_dtb = true)")
            else:
                info["appended_dtb_bytes"] = len(tail)
            if len(fd) - shim > 0x300000:
                errors.append(f"UEFI FD is {len(fd) - shim:#x} bytes, larger than the 0x300000 FD descriptor")
        except (ValueError, zlib.error) as e:
            errors.append(f"kernel gzip: {e}")
    rd = parts["ramdisk"]
    if not rd:
        if allow_empty_ramdisk:
            warnings.append("empty ramdisk: stage-1 image (UEFI and the UniXNU menu only, no payload)")
        else:
            errors.append("empty ramdisk: the UniXNU payload volume is missing")
    else:
        label = fat_label(rd)
        info["ramdisk_label"] = label
        if label is None:
            errors.append("ramdisk is not a FAT volume")
        elif label != volume:
            errors.append(f"ramdisk volume label {label!r} != {volume!r}")
        if len(rd) > max_ramdisk:
            errors.append(f"ramdisk {len(rd):#x} bytes > {max_ramdisk:#x}")
    info["sha256"] = hashlib.sha256(blob).hexdigest()
    info["bytes"] = len(blob)
    return {"errors": errors, "warnings": warnings, "info": info}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("image")
    ap.add_argument("--volume", default="PIPAESP")
    ap.add_argument("--max-ramdisk-mib", type=int, default=192)
    ap.add_argument("--stage1", action="store_true", help="accept an image without payload (--ramdisk none)")
    ap.add_argument("--json")
    args = ap.parse_args(argv)
    with open(args.image, "rb") as f:
        blob = f.read()
    res = check(blob, args.volume, args.max_ramdisk_mib * 2**20, args.stage1)
    if args.json:
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(res, f, indent=2)
            f.write("\n")
    for w in res["warnings"]:
        print(f"WARN  {w}")
    for e in res["errors"]:
        print(f"FAIL  {e}")
    print(f"{'FAIL' if res['errors'] else 'PASS'}  bootimg {args.image} sha256={res['info'].get('sha256', '?')}")
    return 1 if res["errors"] else 0


# Used by tests to build fixtures.
def build(kernel: bytes, ramdisk: bytes, *, header_version=1, page=2048, base=0x10000000, cmdline=b"") -> bytes:
    h = bytearray(page)
    h[:8] = MAGIC
    struct.pack_into("<10I", h, 8, len(kernel), base + 0x8000, len(ramdisk), base + 0x01000000, 0, base + 0x00f00000,
                     base + 0x100, page, header_version, 0)
    h[64:64 + len(cmdline)] = cmdline
    parts = {"kernel": kernel, "ramdisk": ramdisk, "second": b"", "recovery_dtbo": b""}
    if header_version >= 1:
        struct.pack_into("<IQI", h, 1632, 0, 0, 1648)
    h[576:596] = mkbootimg_id(parts, {"header_version": header_version})
    out = io.BytesIO()
    out.write(bytes(h))
    for blob in (kernel, ramdisk):
        out.write(blob)
        out.write(b"\0" * (_pages(len(blob), page) * page - len(blob)))
    return out.getvalue()


def gzip_bytes(data: bytes) -> bytes:
    return gzip.compress(data, mtime=0)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
