# Reprodusibilitas firmware (UEFI FD)

## Temuan (2026-11-16)

| Build | Path | `PYTHONHASHSEED` | SHA-256 FD |
|---|---|---|---|
| sesi 1, build pertama | `/home/claude/src` | acak | `2d6adf84…` |
| sesi 1, checkout bersih | `/home/claude/work-clean` | acak | `def45428…` |
| ulang, path sama | `/home/claude/work-clean` | acak | `476aacd2…` (≠ `def45428`) |
| C | `/home/claude/work-clean` | **0** | `8042049e64a5f7e7…` |
| D (Build/ dihapus, build ulang) | `/home/claude/work-clean` | **0** | `8042049e64a5f7e7…` (= C) |
| E | `/home/claude/src` | **0** | `08ca0703…` (≠ C) |

Host: Ubuntu 24.04 x86_64, clang/lld 18.1.3, nasm, Python 3.13; UniXNU `ae687009`, UniXNU-pipa `cdb3d627`, uefi-pipa `1f6a1520` (submodule terkunci di `manifest/sources.lock.toml`), mu_basecore `cfb93724`.

## Penyebab 1: urutan set Python di BaseTools (sudah diperbaiki)

Hanya **8 byte** di `FVMAIN.Fv` yang berbeda antara dua build di path yang sama: GUID CodeView `RSDS` milik **PcdDxe**. GUID PDB lld diturunkan dari isi PDB; PDB berubah karena `AutoGen.c` PcdDxe berubah:

```
- offsetof(DXE_PCD_DATABASE, Uninit.PcdTestKeyUsed_…) | PCD_TYPE_DATA | PCD_DATUM_TYPE_UINT8_BOOLEAN,
+ offsetof(DXE_PCD_DATABASE, Uninit.PcdTestKeyUsed_…) | PCD_DATUM_TYPE_UINT8_BOOLEAN | PCD_TYPE_DATA,
```

Nilainya sama, tetapi teksnya tidak: BaseTools menyusun flag dari *set* Python, yang urutannya ikut hash randomization. Checksum sumber di debug info berubah, sehingga PDB dan GUID ikut berubah. **Perbaikan:** `PYTHONHASHSEED=0` saat build (`scripts/wsl/build.sh`, `scripts/ci/firmware-repro.sh`). Tidak ada diagnostik yang dihapus.

`STACK_COOKIE_VALUE` di `AutoGen.h` juga acak per build, tetapi binary yang dihasilkan identik (dibuktikan oleh C = D), jadi nilai itu tidak masuk ke FD.

## Penyebab 2: path absolut (masih ada; disengaja dipertahankan)

Build E (path lain) berbeda di banyak modul. Isi yang berbeda: `__FILE__` pada pesan `ASSERT` build DEBUG (mis. `/…/mu_basecore-89034cbb/MdePkg/Library/BaseLib/SafeString.c`) dan path PDB di RSDS. Keduanya diagnostik: pesan ASSERT di layar/log menunjuk file sumbernya. Keduanya tidak dibuang hanya untuk menyamakan hash.

**Status:** reproducible untuk **input, toolchain, dan path build yang sama**. CI membangun di path kanonis `/tmp/pipa-fw/work` agar hash bisa dibandingkan antar mesin. **Belum** path-independent. Langkah berikutnya: `-ffile-prefix-map=<root>=/pipa` (clang) dan `/pdbaltpath:%_PDB%` (lld-link) lewat `tools_def`, yang mempertahankan nama file tetapi membuang prefix mesin.

## Cara memverifikasi

```sh
scripts/ci/firmware-repro.sh /tmp/fwcheck     # A dan B di /tmp/pipa-fw/work, C di /tmp/pipa-fw-alt/work
cat /tmp/fwcheck/report/fd-sha256.txt
```

Job `firmware` di CI menjalankan perintah yang sama dan gagal jika A ≠ B.
