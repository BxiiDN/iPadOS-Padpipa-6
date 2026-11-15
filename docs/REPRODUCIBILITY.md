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

## Hasil lintas mesin (2026-11-16)

| Build | Mesin | FD A = B (`/tmp/pipa-fw/work`) | FD C (`/tmp/pipa-fw-alt/work`) | `boot-stage1.img` |
|---|---|---|---|---|
| lokal | sandbox Ubuntu 24.04, clang 18.1.3, Python 3.13 + **zlib-ng 1.3.1** | `8313aa34e68a151b…` | `3e2ccbf4983288da…` | `157b3b15b833ec29…` (berisi FD C, lihat catatan) |
| CI run [43771439646](https://github.com/BxiiDN/iPadOS-Padpipa-6/actions/runs/43771439646) job `firmware` | GitHub ubuntu-24.04, clang/lld dari apt, zlib sistem | `8313aa34e68a151b…` | `3e2ccbf4983288da…` | `60b498850f169a0b…` (berisi FD C) |

- **FD reproducible lintas mesin** untuk path yang sama: hash sama persis di kedua path.
- **`boot-stage1.img` belum**: header `mtime` gzip sudah 0 (`bootimg.py`), tetapi zlib-ng dan zlib klasik menghasilkan stream deflate berbeda dari input yang identik. `check_bootimg.py` kini mencetak `fd_sha256` (FD hasil dekompresi, tanpa shim) untuk membandingkan isi. Supaya image bit-identik, kompresor harus sama; kandidatnya adalah zlib klasik yang dikunci di build.

Catatan: di run ini `bootimg` memakai FD dari path C karena variabel `UNIXNU_UEFI` terbawa dari build C (bug skrip; `fd_sha256` = `3e2ccbf4…`). Sudah diperbaiki: image tahap 1 kini memakai FD path kanonis.
