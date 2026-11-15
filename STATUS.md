# Status (2026-11-16, sesi 2)

Target: **Xiaomi Pad 6 pipa, SM8250-AC, 8 GB, 256 GB**. Basis: UniXNU-pipa + iPadOS 17.7.11 (21H461).

## Repository GitHub (diperiksa lewat API, bukan dari laporan)

| | Status sebenarnya |
|---|---|
| PR [#1](https://github.com/BxiiDN/iPadOS-Padpipa-6/pull/1) | **open, `merged: false`**. `merge_commit_sha` hanyalah commit uji merge buatan GitHub, bukan bukti merge. Kalimat sesi 1 "masuk ke `main` lewat PR #1" keliru jika dibaca sebagai sudah di-merge |
| `main` | `c964584`: hanya baseline (LICENSE, .gitignore, README stub) |
| `pipa-8g256-bringup` | branch kerja; semua pekerjaan ada di sini |
| CI sesi 1 (`1611d7f`, run 43769005497 / 43769029407) | hanya **gate konfigurasi + test regresi** (34 test). Tidak membangun firmware, kernel, atau iPadOS |

## CI sesi 2 (workflow `pipa build`, job terpisah)

| Job | Isi | Hasil |
|---|---|---|
| `config` | gate board/memori/blob, laporan input kernel | lulus |
| `host` ubuntu-24.04 | test regresi + test driver upstream (GMU: SKIP dengan alasan) + KTZ8866 | lulus |
| `host` ubuntu-24.04-**arm** | idem, **A650GmuTests dijalankan** | lulus (`PASS A650GmuTests`). Run pertama hijau padahal GMU gagal compile, karena `\| tee` tanpa pipefail; sudah diperbaiki |
| `windows` (windows-2025) | parse PS 5.1 + Pester di PS 5.1 dan PS 7 | lulus setelah dua perbaikan (parse `$sn:`, array/`[long]`) |
| `firmware` | 3 build bersih + image tahap 1 | lihat [REPRODUCIBILITY.md](docs/REPRODUCIBILITY.md) |
| `kernel` (macos-26, Xcode 26.6) | sumber terkunci, firmware CI, IPSW via HTTP range | **gagal di arsip ke-6**, penyebabnya di bawah |

## Matriks status

`implemented` = source/konfigurasi ada · `build-tested` = compile/pack/test lulus dari checkout bersih, ada log · `device-tested` = jalan di **tablet ini** · `blocked` = tertahan, penyebab disebut.

**Belum ada satu pun baris `device-tested`.** Hasil tablet referensi xVanTuring (16 GB/128 GB) tidak dihitung.

| Area | Status | Bukti / penyebab |
|---|---|---|
| Gate board, memori, firmware, boot image, simbol, IPSW, sparse, flash | `build-tested` | 56 test, job `config`/`host` |
| Skrip Windows (serial, exit code, identitas, backup, BOM, spasi) | `build-tested` | Pester di PS 5.1 + 7 (job `windows`); belum dijalankan dengan tablet nyata |
| Fakta unit (bank, GPT 256 GB, panel) | `blocked` | butuh tablet: `pipa.ps1 collect` |
| UEFI FD + `boot-stage1.img` | `build-tested` | lokal + job `firmware`. Image **tahap 1 = menu UniXNU saja, bukan iPadOS** |
| Reprodusibilitas FD | `build-tested` untuk path yang sama | `PYTHONHASHSEED=0`: A = B (`8313aa34…` di `/tmp/pipa-fw/work`). Path lain berbeda karena path absolut di ASSERT/PDB (sengaja dipertahankan) |
| Alokasi RAM | `implemented` | XNU diberi **4 GiB** (`owned_memory_size 0x100000000`) dari bank 7,93 GiB. `dram_size 0x200000000` adalah rentang alamat, bukan RAM terpakai. Naik hanya setelah peta memori UEFI unit ini terbaca |
| IPSW 21H461 | `build-tested` | job kernel: member dibaca dari CDN Apple; `check_ipsw.py` (model, build, versi, SHA-256) untuk file lokal |
| XNU compile (Xcode) | `build-tested` (compile) | job kernel; link bootstrap pass menunggu simbol driver |
| Arsip corecrypto ×2, ArmDTPlatform, ArmCpu, SoftwareAES | `build-tested` | job kernel |
| Arsip `PipaUfs --sm8250` dan seterusnya | `blocked` | komponen dan flag tidak ada di UniXNU publik mana pun ([AUDIT.md §8](docs/AUDIT.md)) |
| `build-verified-root-key.py` + anchor owner | `blocked` | skrip tidak dipublikasikan; anchor `70a5…` milik owner lain; perlu kunci RSA-3072 milik Abian |
| Arsip display (`build-gop-legacy-display.py`) | `blocked` | butuh tree UniXNU-qemu + observasi HVF dari Mac Apple silicon |
| Payload, boot image lengkap, root image | `blocked` | menunggu kernel |
| Data seed grow / skip-setup | `blocked` | butuh macOS `hdiutil`; runner macOS tersedia (terbukti), menunggu payload |
| CPU, UFS, touch, tombol, Adreno 650 + Metal | `implemented` (upstream) | dilaporkan jalan di unit referensi; belum di unit ini |
| Backlight KTZ8866 | `implemented` + host-tested | `drivers/backlight-ktz8866`, tidak pernah menulis arus/OVP. Ke kernel: `blocked`, belum ada master GENI I2C |
| Baterai (fg-gen4 pipa) | `implemented` (upstream) | MiCode `CONFIG_QPNP_FG_GEN4_PIPA=y`; perlu diff dengan `qpnp-fg-gen4-pipa.c` |
| Wi-Fi / Bluetooth (QCA6390) | `blocked` | donor j716f `bf2d0f32`: pin cocok dengan DTB pipa, tetapi klaim device-verified sudah ditarik dari README HEAD donor; belum dipindahkan |
| Audio (ADSP + 4× AW882xx), sensor (SSC/SLPI), kamera, video HW, thermal, sleep/wake | `blocked` | belum dimulai; sumber di [HARDWARE.md](docs/HARDWARE.md) |
| GPU: artefak GMEM/rounded corners, frame pacing, leak, recovery hang | `blocked` | butuh tablet; upstream melaporkan sudut salah di GMEM dan pacing 1–2 refresh |

## Penghambat, dengan penyebab spesifik

1. **Kernel pipa tidak bisa direproduksi dari sumber publik**: `PipaUfs`/`--sm8250`, `build-verified-root-key.py`, anchor owner, dan referensi display HVF. Jalan keluar: minta xVanTuring mempublikasikan UniXNU lokalnya, atau port ulang ke `ShengUfs` + kunci owner baru + tree referensi buatan sendiri di Mac.
2. **Tablet**: fakta unit, firmware milik sendiri, backup, dan ronde R1–R8 ([TESTING.md](docs/TESTING.md)).
3. **Artifact CI tidak bisa diunduh dari sandbox ini** (blob storage diblokir proxy). Hasil diambil dari log job.
