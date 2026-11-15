# SPDX-License-Identifier: MIT
"""Regression tests for the gates. Each check must FAIL on the bad input it exists for, and pass on a good one.

    python3 -m unittest discover -s tests -v
Integration tests against the real pipa inputs run when PIPA_UEFI points at a uefi-pipa checkout
(and PIPA_BOARD at UniXNU-pipa's board.toml).
"""
from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "tools"), os.path.join(ROOT, "tools", "checks"), os.path.dirname(os.path.abspath(__file__))]

import fdt  # noqa: E402
import fdtbuild  # noqa: E402
import unitfacts  # noqa: E402
import pipa_board  # noqa: E402
import check_memory  # noqa: E402
import check_bootimg  # noqa: E402
import check_firmware  # noqa: E402
import check_symbols  # noqa: E402
import check_board  # noqa: E402
import sparse  # noqa: E402
import flash_gate  # noqa: E402
import check_inputs  # noqa: E402

MEMMAP_OK = """
static ARM_MEMORY_REGION_DESCRIPTOR_EX gDeviceMemoryDescriptorEx[] = {
  {"HYP",               0x80000000, 0x00600000, AddMem, SYS_MEM, SYS_MEM_CAP, Reserv, NS_DEVICE},
  // a comment {"Fake", 0x1, 0x1, ...}
  {"Display Reserved",  0x9C000000, 0x02400000, AddMem, MEM_RES, SYS_MEM_CAP, Reserv, WRITE_THROUGH_XN},
  {"UEFI FD",           0x9FC00000, 0x00300000, AddMem, SYS_MEM, SYS_MEM_CAP, BsData, WRITE_BACK},
  {"Kernel",            0xA0000000, 0x10000000, AddMem, MEM_RES, SYS_MEM_CAP, Reserv, WRITE_BACK_XN},
  {"Bank 1 Hole",       0xFFC00000, 0x00020000, AddMem, MEM_RES, UNCACHEABLE, Reserv, UNCACHED_UNBUFFERED_XN},
  {"GPU_CC",            0x02C90000, 0x0000A000, AddDev, MMAP_IO, UNCACHEABLE, MmIO,   NS_DEVICE},
};
"""
BANKS_8G = [(0x80000000, 0x3BB00000), (0xC0000000, 0x1C0000000)]
BANKS_16G = BANKS_8G + [(0x800000000, 0x200000000)]


SERIAL_HASH = "ab" * 32


def facts_with(banks, storage=None, source="measured"):
    f = unitfacts.empty()
    f["provenance"]["source"] = source
    f["device"]["product"] = "pipa"
    f["device"]["serial_sha256"] = SERIAL_HASH
    f["memory"] = {"source": source, "mem_total_kib": None, "banks": [[hex(a), hex(s)] for a, s in banks]}
    if storage:
        f["storage"] = storage
    return f


DISK_256_SECTORS = 499122176   # 255.55 GB, a 256 GB UFS LUN 0 in 512-byte sectors


def storage_256(first=0x293000, gib=220.0, disk=DISK_256_SECTORS, extra_parts=None):
    blocks = int(gib * 2**30 / 4096)
    last = first + blocks - 1
    parts = [{"dev": "sda1", "name": "ssd", "start_512": 6 * 8, "size_512": 2 * 8},
             {"dev": "sda33", "name": "metadata", "start_512": 0x200000 * 8, "size_512": 0x93000 * 8},
             {"dev": "sda34", "name": "userdata", "start_512": first * 8, "size_512": blocks * 8}] + (extra_parts or [])
    return {"source": "measured", "lba_bytes": 4096, "userdata": {"dev": "sda34", "first_lba": hex(first), "last_lba": hex(last)},
            "disk_sectors_512": disk, "disk_blocks": disk // 8, "ufs_vendor": None, "ufs_model": None, "partitions": parts}


def fat16(label="PIPAESP", size=1 << 20):
    vol = bytearray(size)
    struct.pack_into("<H", vol, 11, 512)
    struct.pack_into("<H", vol, 22, 32)        # sectors per FAT != 0 -> FAT12/16 layout
    vol[0x2B:0x2B + 11] = label.ljust(11).encode()
    vol[510:512] = b"\x55\xaa"
    return bytes(vol)


def kernel_with_shim_and_dtb(fd_size=0x1000):
    fd = bytearray(fd_size)
    fd[40:44] = b"_FVH"
    shim = b"\x00" * 192
    return check_bootimg.gzip_bytes(shim + bytes(fd)) + fdtbuild.pipa_like()


class FdtTests(unittest.TestCase):
    def test_banks_and_reserved(self):
        tree = fdt.parse(fdtbuild.pipa_like())
        self.assertEqual(fdt.memory_banks(tree), BANKS_8G)
        res = {r["name"]: r for r in fdt.reserved_regions(tree)}
        self.assertTrue(res["hyp_region@80000000"]["no_map"])
        self.assertFalse(res["cont_splash_region@9c000000"]["no_map"])

    def test_bad_magic(self):
        with self.assertRaises(fdt.FdtError):
            fdt.parse(b"\0" * 64)


class MemoryTests(unittest.TestCase):
    def run_check(self, memmap=MEMMAP_OK, banks=BANKS_8G, reserved=None, owned=0x100000000, payload=192 << 20, top=0x10000000):
        tree = fdt.parse(fdtbuild.pipa_like(banks=banks, reserved=reserved))
        return check_memory.check(check_memory.parse_memmap(memmap), tree, banks, owned, payload, top)

    def test_ok_and_window_after_bank1_hole(self):
        r = self.run_check()
        self.assertEqual(r["errors"], [])
        self.assertEqual(r["predicted_xnu_window"]["base"], "0xffc20000")

    def test_comment_lines_are_ignored(self):
        self.assertNotIn("Fake", [d["name"] for d in check_memory.parse_memmap(MEMMAP_OK)])

    def test_overlapping_descriptors(self):
        bad = MEMMAP_OK.replace('{"Kernel",            0xA0000000', '{"Kernel",            0x9FD00000')
        self.assertTrue(any("overlap" in e for e in self.run_check(memmap=bad)["errors"]))

    def test_uncovered_no_map_carveout(self):
        r = self.run_check(reserved={"pil_adsp_region@8bb00000": (0x8BB00000, 0x2500000, True)})
        self.assertTrue(any("not covered" in e for e in r["errors"]))

    def test_owned_too_large_for_8g(self):
        r = self.run_check(owned=0x200000000)
        self.assertTrue(any("no free run" in e for e in r["errors"]))

    def test_tight_window_warns(self):
        self.assertTrue(self.run_check(owned=0x170000000)["warnings"])

    def test_mmio_in_dram(self):
        bad = MEMMAP_OK.replace('{"GPU_CC",            0x02C90000', '{"GPU_CC",            0xC0000000')
        self.assertTrue(any("MMIO" in e for e in self.run_check(memmap=bad)["errors"]))

    def test_payload_too_big_for_abl_window(self):
        self.assertTrue(any("ABL window" in e for e in self.run_check(payload=300 << 20)["errors"]))


class BootImageTests(unittest.TestCase):
    def good(self, **kw):
        return check_bootimg.build(kw.pop("kernel", kernel_with_shim_and_dtb()), kw.pop("ramdisk", fat16()), **kw)

    def test_good_image(self):
        r = check_bootimg.check(self.good(), "PIPAESP", 192 << 20)
        self.assertEqual(r["errors"], [], r)
        self.assertEqual(r["info"]["shim_bytes"], 192)

    def test_wrong_page_size(self):
        r = check_bootimg.check(self.good(page=4096), "PIPAESP", 192 << 20)
        self.assertTrue(any("page_size" in e for e in r["errors"]))

    def test_header_v3_refused(self):
        r = check_bootimg.check(self.good(header_version=3), "PIPAESP", 192 << 20)
        self.assertTrue(r["errors"])

    def test_no_appended_dtb(self):
        k = check_bootimg.gzip_bytes(b"\0" * 40 + b"_FVH" + b"\0" * 100)
        r = check_bootimg.check(self.good(kernel=k), "PIPAESP", 192 << 20)
        self.assertTrue(any("DTB" in e for e in r["errors"]))

    def test_wrong_volume_label(self):
        r = check_bootimg.check(self.good(ramdisk=fat16("OTHERVOL")), "PIPAESP", 192 << 20)
        self.assertTrue(any("label" in e for e in r["errors"]))

    def test_truncated(self):
        r = check_bootimg.check(self.good()[:5000], "PIPAESP", 192 << 20)
        self.assertTrue(any("truncated" in e for e in r["errors"]))

    def test_stage1_empty_ramdisk(self):
        img = self.good(ramdisk=b"")
        self.assertTrue(check_bootimg.check(img, "PIPAESP", 192 << 20)["errors"])
        self.assertEqual(check_bootimg.check(img, "PIPAESP", 192 << 20, True)["errors"], [])


class FirmwareTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmp, "gpu"))
        with open(os.path.join(self.tmp, "gpu", "a650_gmu.bin"), "wb") as f:
            f.write(b"not the real firmware")

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def manifest(self, sha):
        return {"firmware": [{"name": "a650_gmu.bin", "cache_path": "gpu/a650_gmu.bin", "sha256": sha, "stages": ["gpu"]}]}

    def test_wrong_digest_fails(self):
        r = check_firmware.check_cache(self.manifest("0" * 64), self.tmp, "gpu")
        self.assertTrue(any("sha256" in e for e in r["errors"]))

    def test_unmeasured_warns(self):
        r = check_firmware.check_cache(self.manifest("UNMEASURED"), self.tmp, "gpu")
        self.assertEqual(r["errors"], [])
        self.assertTrue(r["warnings"])

    def test_missing_required_fails(self):
        m = {"firmware": [{"name": "a650_zap.elf", "cache_path": "gpu/a650_zap.elf", "sha256": "UNMEASURED", "stages": ["gpu"]}]}
        self.assertTrue(check_firmware.check_cache(m, self.tmp, "gpu")["errors"])

    def test_blob_in_repo_detected(self):
        repo = tempfile.mkdtemp()
        try:
            os.makedirs(os.path.join(repo, "firmware"))
            open(os.path.join(repo, "firmware", "a650_zap.mdt"), "wb").close()
            open(os.path.join(repo, "README.md"), "w").close()
            r = check_firmware.scan_repo(repo, self.manifest("UNMEASURED"))
            self.assertEqual(len(r["errors"]), 1)
        finally:
            shutil.rmtree(repo)


@unittest.skipUnless(shutil.which("clang") and (shutil.which("llvm-ar") or shutil.which("ar")), "clang/llvm-ar needed")
class SymbolTests(unittest.TestCase):
    def test_missing_symbol_detected(self):
        tmp = tempfile.mkdtemp()
        try:
            def obj(name, src):
                c, o = os.path.join(tmp, name + ".c"), os.path.join(tmp, name + ".o")
                with open(c, "w") as f:
                    f.write(src)
                subprocess.run(["clang", "--target=arm64-apple-ios17.0", "-ffreestanding", "-c", c, "-o", o], check=True)
                return o
            k = obj("kernel", "int kernel_export(void){return 1;}")
            d = obj("driver", "int kernel_export(void); int not_in_kernel(void); int drv(void){return kernel_export()+not_in_kernel();}")
            ar = shutil.which("llvm-ar") or "ar"
            lib = os.path.join(tmp, "libdrv.a")
            subprocess.run([ar, "rcs", lib, d], check=True)
            r = check_symbols.check(k, [lib], ["_kernel_export"], check_symbols.nm_tool())  # Mach-O C names carry a leading _
            self.assertEqual(r["required_missing"], [])
            self.assertIn("_not_in_kernel", r["missing"][lib])
            self.assertNotIn("_kernel_export", r["missing"][lib])
            r2 = check_symbols.check(k, [lib], [], check_symbols.nm_tool(), {"_not_in_kernel"})
            self.assertEqual(r2["errors"], [])
        finally:
            shutil.rmtree(tmp)


UPSTREAM_BOARD_SNIPPET = '''[board]
name = "pipa"
soc = "SM8250"
[ipsw]
url = "https://updates.cdn-apple.com/x.ipsw"
product = "iPad7,1"
version = "17.7.11"
build = "21H461"
chip_id = 0x8011
[ipsw.sha256]
"a.dmg" = "00"
[userdata]
first_lba = 0x293000
last_lba = 0x1d387fa
lba_bytes = 4096
[payload]
title = "pipa first boot"
dram_size = "0x980000000"
size_mib = 192
kernel_args = ["-v", "serial=3"]
[payload.adt]
owned_memory_size = "0x170000000"   # comment kept
cpu_regs = "0,0x100,0x200,0x300,0x400,0x500,0x600,0x700"
unique_chip_id = "required"
'''


class BoardTests(unittest.TestCase):
    overlay = {"owned_memory_size": "0x100000000", "title": "t"}

    def test_reference_16g_board_fails_on_8g_unit(self):
        r = check_board.check(UPSTREAM_BOARD_SNIPPET, facts_with(BANKS_8G))
        self.assertTrue(any("dram_size" in e for e in r["errors"]))

    def test_generated_board_passes_and_keeps_comments(self):
        text, rep = pipa_board.generate(UPSTREAM_BOARD_SNIPPET, facts_with(BANKS_8G), self.overlay)
        self.assertIn('owned_memory_size = "0x100000000"   # comment kept', text)
        self.assertIn('dram_size = "0x200000000"', text)
        self.assertFalse(rep["flash_allowed"])
        self.assertIn(pipa_board.NOT_FOR_FLASH, text)
        self.assertEqual(check_board.check(text, facts_with(BANKS_8G))["errors"], [])

    def test_16g_facts_refused_for_this_8g_target(self):
        # The reference tablet's 16 GB banks are not this unit's: the generator must not accept them.
        with self.assertRaises(pipa_board.BoardError):
            pipa_board.generate(UPSTREAM_BOARD_SNIPPET, facts_with(BANKS_16G), self.overlay)

    def test_measured_256g_gpt_enables_flash(self):
        facts = facts_with(BANKS_8G, storage_256())
        text, rep = pipa_board.generate(UPSTREAM_BOARD_SNIPPET, facts, self.overlay)
        self.assertTrue(rep["flash_allowed"])
        self.assertTrue(check_board.check(text, facts)["flash_allowed"])

    def test_128g_window_rejected_for_256g_unit(self):
        # The reference unit's 106.6 GiB userdata must not pass as a 256 GB unit's.
        self.assertTrue(unitfacts.problems(facts_with(BANKS_8G, storage_256(gib=106.6)), need_storage=True))

    def test_owned_bounds(self):
        with self.assertRaises(pipa_board.BoardError):
            pipa_board.generate(UPSTREAM_BOARD_SNIPPET, facts_with(BANKS_8G), {"owned_memory_size": "0x100001000", "title": "t"})

    def test_kernel_args_limit(self):
        long_args = UPSTREAM_BOARD_SNIPPET.replace('["-v", "serial=3"]', '["' + "x" * 1001 + '"]')
        with self.assertRaises(pipa_board.BoardError):
            pipa_board.generate(long_args, facts_with(BANKS_8G), self.overlay)

    def test_wrong_product_refused(self):
        f = facts_with(BANKS_8G)
        f["device"]["product"] = "liuqin"
        with self.assertRaises(pipa_board.BoardError):
            pipa_board.generate(UPSTREAM_BOARD_SNIPPET, f, self.overlay)


class UnitFactsTests(unittest.TestCase):
    def kv(self, lines, *, bom=False, crlf=False):
        sep = "\r\n" if crlf else "\n"
        with tempfile.NamedTemporaryFile("wb", suffix=".kv", delete=False) as f:
            f.write((b"\xef\xbb\xbf" if bom else b"") + sep.join(lines).encode())
        try:
            return unitfacts.from_adb_kv(f.name)
        finally:
            os.unlink(f.name)

    def base_lines(self):
        reg = fdtbuild.reg64(*BANKS_8G).hex()
        return ["ro.product.device=pipa", "serial_sha256=" + SERIAL_HASH, "adb_serial_sha256=" + SERIAL_HASH,
                "dt_memory_reg=" + reg, "lun0_lba_bytes=4096", f"lun0_size_512={DISK_256_SECTORS}",
                f"part=sda34|userdata|{0x293000 * 8}|{int(220 * 2**30 / 512)}"]

    def test_bom_and_crlf_from_windows(self):
        # Windows PowerShell 5.1 Out-File -Encoding utf8 writes a BOM; the first key must still parse.
        lines = ["ro.product.device=pipa"] + self.base_lines()[1:]
        for f in (self.kv(lines, bom=True), self.kv(lines, crlf=True), self.kv(lines, bom=True, crlf=True)):
            self.assertEqual(f["device"]["product"], "pipa")
            self.assertEqual(unitfacts.banks(f), BANKS_8G)

    def test_identity_mismatch(self):
        lines = [l for l in self.base_lines() if not l.startswith("adb_serial")] + ["adb_serial_sha256=" + "cd" * 32]
        self.assertTrue(any("ro.serialno" in p for p in unitfacts.problems(self.kv(lines), need_storage=False)))

    def test_measured_without_serial_refused(self):
        lines = [l for l in self.base_lines() if not l.startswith(("serial_sha256", "adb_serial"))]
        self.assertTrue(any("serial hash" in p for p in unitfacts.problems(self.kv(lines), need_storage=False)))

    def test_from_adb_kv(self):
        reg = fdtbuild.reg64(*BANKS_8G).hex()
        lines = ["collector_version=1", "root=1", "ro.product.device=pipa", "mem_total_kib=7660000", "serial_sha256=" + SERIAL_HASH,
                 "dt_memory_reg=" + " ".join(reg[i:i + 2] for i in range(0, len(reg), 2)),
                 "lun0_lba_bytes=4096", "lun0_size_512=499122176",
                 f"part=sda33|metadata|{0x200000 * 8}|{0x93000 * 8}",
                 f"part=sda34|userdata|{0x293000 * 8}|{int(220 * 2**30 / 512)}", "errors="]
        with tempfile.NamedTemporaryFile("w", suffix=".kv", delete=False) as f:
            f.write("\n".join(lines))
        try:
            facts = unitfacts.from_adb_kv(f.name)
        finally:
            os.unlink(f.name)
        self.assertEqual(unitfacts.banks(facts), BANKS_8G)
        self.assertEqual(unitfacts.dram_size(facts), 0x200000000)
        self.assertEqual(facts["storage"]["userdata"]["first_lba"], "0x293000")
        self.assertEqual(unitfacts.problems(facts, need_storage=True), [])

    def test_memtotal_inconsistent(self):
        f = facts_with(BANKS_16G)
        f["memory"]["mem_total_kib"] = 7660000   # an 8 GB MemTotal against 16 GB of banks
        self.assertTrue(unitfacts.problems(f, need_storage=False))


class StorageTests(unittest.TestCase):
    def prob(self, st):
        return unitfacts.problems(facts_with(BANKS_8G, st), need_storage=True)

    def test_good_256g(self):
        self.assertEqual(self.prob(storage_256()), [])

    def test_128g_disk_refused(self):
        self.assertTrue(any("256 GB" in p for p in self.prob(storage_256(disk=249737216))))

    def test_partition_past_disk_end(self):
        st = storage_256(gib=239.0)
        self.assertTrue(any("ends past the disk" in p for p in self.prob(st)))

    def test_misaligned_partition(self):
        st = storage_256(extra_parts=[{"dev": "sda2", "name": "x", "start_512": 100 * 8 + 1, "size_512": 8}])
        self.assertTrue(any("not aligned" in p for p in self.prob(st)))

    def test_overlap(self):
        st = storage_256(extra_parts=[{"dev": "sda32", "name": "y", "start_512": 0x290000 * 8, "size_512": 0x10000 * 8}])
        self.assertTrue(any("overlap" in p for p in self.prob(st)))

    def test_window_differs_from_gpt_entry(self):
        st = storage_256()
        st["userdata"]["last_lba"] = hex(int(st["userdata"]["last_lba"], 16) - 1)
        self.assertTrue(any("own GPT entry" in p for p in self.prob(st)))

    def test_missing_partition_table(self):
        st = storage_256()
        st["partitions"] = []
        self.assertTrue(any("partition table" in p for p in self.prob(st)))

    def test_8g_ram_bounds(self):
        self.assertTrue(any("not an 8 GB" in p for p in unitfacts.problems(facts_with([(0x80000000, 0x3BB00000)]), need_storage=False)))


class SparseTests(unittest.TestCase):
    def write(self, blob):
        f = tempfile.NamedTemporaryFile(delete=False)
        f.write(blob)
        f.close()
        self.addCleanup(os.unlink, f.name)
        return f.name

    def test_expanded_size(self):
        img = self.write(sparse.build([(sparse.RAW, 2, b"\0" * 8192), (sparse.DONT_CARE, 1000, b""), (sparse.FILL, 3, b"\0\0\0\0")]))
        i = sparse.info(img)
        self.assertEqual(i["expanded"], 1005 * 4096)
        self.assertEqual(flash_gate.image_problems(img, 1005 * 4096, 4096)[0], [])
        self.assertTrue(flash_gate.image_problems(img, 1004 * 4096, 4096)[0])

    def test_truncated(self):
        blob = sparse.build([(sparse.RAW, 2, b"\0" * 8192)])
        with self.assertRaises(sparse.SparseError):
            sparse.info(self.write(blob[:-100]))

    def test_header_block_count_lies(self):
        blob = bytearray(sparse.build([(sparse.DONT_CARE, 10, b"")]))
        struct.pack_into("<I", blob, 16, 11)
        with self.assertRaises(sparse.SparseError):
            sparse.info(self.write(bytes(blob)))

    def test_raw_not_block_multiple(self):
        p, _ = flash_gate.image_problems(self.write(b"\1" * 5000), 1 << 20, 4096)
        self.assertTrue(any("multiple" in x for x in p))


class MemoryReportTests(unittest.TestCase):
    def test_span_is_not_ram(self):
        tree = fdt.parse(fdtbuild.pipa_like())
        r = check_memory.check(check_memory.parse_memmap(MEMMAP_OK), tree, BANKS_8G, 0x100000000, 192 << 20, 0x10000000)
        m = r["memory"]
        self.assertEqual(m["address_span_bytes"], 0x200000000)
        self.assertEqual(m["bank_bytes"], 0x3BB00000 + 0x1C0000000)
        self.assertGreater(m["hole_in_span_bytes"], 0)
        self.assertEqual(m["owned_bytes"], 0x100000000)
        self.assertLess(m["owned_fraction_of_banks"], 0.6)


class KernelInputsTests(unittest.TestCase):
    def test_missing_builder_is_reported(self):
        work = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, work)
        for d in ("UniXNU/scripts", "UniXNU-pipa/scripts"):
            os.makedirs(os.path.join(work, d))
        open(os.path.join(work, "UniXNU/scripts/build-arm-driver.py"), "w").close()
        with open(os.path.join(work, "UniXNU-pipa/board.toml"), "w") as f:
            f.write('[kernel]\narchives = ["build-arm-driver.py ArmCpu", "build-verified-root-key.py --pin 70a5"]\n')
        r = check_inputs.check(work, None)
        self.assertIn("build-verified-root-key.py --pin 70a5", r["missing"])
        self.assertNotIn("build-arm-driver.py ArmCpu", r["missing"])


@unittest.skipUnless(os.environ.get("PIPA_UEFI"), "set PIPA_UEFI to a uefi-pipa checkout for the integration test")
class PipaIntegrationTests(unittest.TestCase):
    def test_real_memory_map(self):
        u = os.environ["PIPA_UEFI"]
        with open(os.path.join(u, "Platforms/Xiaomi/pipaPkg/Library/MemoryMapLib/MemoryMapLib.c")) as f:
            mm = check_memory.parse_memmap(f.read())
        tree = fdt.load(os.path.join(u, "Resources/DTBs/pipa.dtb"))
        banks = fdt.memory_banks(tree)
        self.assertEqual(banks, BANKS_8G, "the stock pipa DTB describes the 8 GB layout")
        r = check_memory.check(mm, tree, banks, 0x100000000, 192 << 20, 0x10000000)
        self.assertEqual(r["errors"], [])
        self.assertEqual(r["predicted_xnu_window"]["base"], "0xffc20000")

    @unittest.skipUnless(os.environ.get("PIPA_BOARD"), "PIPA_BOARD: UniXNU-pipa board.toml")
    def test_real_board(self):
        with open(os.environ["PIPA_BOARD"]) as f:
            up = f.read()
        facts = unitfacts.from_dtb(os.path.join(os.environ["PIPA_UEFI"], "Resources/DTBs/pipa.dtb"))
        self.assertTrue(check_board.check(up, facts)["errors"], "the 16 GB reference board must fail on 8 GB")
        text, rep = pipa_board.generate(up, facts, pipa_board.load_overlay(os.path.join(ROOT, "device/pipa-8g256/overlay.toml")))
        self.assertEqual(check_board.check(text, facts)["errors"], [])
        self.assertLessEqual(rep["kernel_args_bytes"], 1000)


if __name__ == "__main__":
    unittest.main()
