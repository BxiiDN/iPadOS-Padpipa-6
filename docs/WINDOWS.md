# Panduan Windows 11

Semua perintah dijalankan dari PowerShell di folder repo (path yang mengandung spasi didukung). `adb.exe` dan `fastboot.exe` berjalan di Windows ([Android SDK Platform-Tools](https://developer.android.com/tools/releases/platform-tools)); build berjalan di WSL2 Ubuntu 24.04.

## Di mana tiap bagian dibangun

| Bagian | Windows | WSL2 / Linux | GitHub Linux runner | macOS (Mac/runner) |
|---|---|---|---|---|
| Gate konfigurasi, test regresi | — | ya | job `config`, `host` | — |
| Test driver upstream (GMU butuh AArch64) | — | ya (x86: GMU di-skip) | `host` x86_64 + **ARM64** | — |
| UEFI FD + boot image tahap 1 | — | `build.sh firmware stage1` | job `firmware` (2 build + cek reprodusibilitas) | — |
| Kernel XNU + arsip pipa | — | toolchain Mach-O Linux UniXNU (`setup`, berjam-jam) | — | job `kernel` (Xcode 26.6), sebatas input publik |
| Payload, userdata | — | `build.sh payload/userdata` | — | idem |
| Data seed grow / skip-setup | — | — | — | **hanya macOS** (`hdiutil`) |
| adb/fastboot, backup, log | `pipa.ps1` | — | — | — |

## Urutan lengkap

```powershell
# 0. Sekali
.\scripts\windows\pipa.ps1 doctor
.\scripts\windows\pipa.ps1 setup                 # WSL2: paket + toolchain Mach-O (lama)

# 1. Tablet di Android, USB debugging ON, satu tablet terhubung (atau -Serial <serial>)
.\scripts\windows\pipa.ps1 collect               # -> device\pipa-8g256\unit-facts.json (terikat SHA-256 serial)
.\scripts\windows\pipa.ps1 firmware              # -> work\UniXNU-pipa\.cache\firmware + logs\firmware-<waktu>.json
.\scripts\windows\pipa.ps1 backup                # -> backup\<waktu>\ + manifest.json (diverifikasi ulang)

# 2. Build
.\scripts\windows\pipa.ps1 build all             # bootstrap, board, firmware, stage1, check
#    -> out\pipa-8g256\boot-stage1.img, SILICIUM_UEFI.fd, SHA256SUMS, check-*.json

# 3. Tablet di fastboot (adb reboot bootloader)
.\scripts\windows\pipa.ps1 backup-fastboot
.\scripts\windows\pipa.ps1 boot out\pipa-8g256\boot-stage1.img
```

### Ronde R1 — `boot-stage1.img` (BUKAN image iPadOS)

| | |
|---|---|
| Isi | shim 192 B + FD Mu-Silicium/UniXNU/DarwinBoot 3 MiB + `pipa.dtb`; **ramdisk kosong** |
| Checksum | `out\pipa-8g256\SHA256SUMS`; `pipa.ps1 boot` mencetak SHA-256 sebelum boot |
| Hasil yang diharapkan | log Mu-Silicium di layar, lalu menu UniXNU yang melaporkan *no operating system* |
| Bukan keberhasilan | kernel, root, SpringBoard: image ini tidak membawanya |
| Log | `pipa.ps1 log -Reader <log-reader.img>` → `logs\device\<waktu>\LOG.BIN` (di-hash ulang setelah disalin) |

### Ronde berikutnya

Kernel, root mount, SpringBoard, dan hardware diuji terpisah ([TESTING.md](TESTING.md)): R2 kernel (panic `Failed to mount root device` = berhasil sampai kernel), R3 survei UFS, R4 root + SpringBoard (butuh `flash-userdata`), R5 input, R6 GPU.

## Apa yang bisa ditulis image yang di-boot {#what-a-booted-image-can-write}

`fastboot boot` sendiri tidak menulis partisi. Kode yang di-boot tetap berjalan dengan akses penuh ke hardware, jadi yang diaudit adalah isinya:

| Image | Yang ditulis | Dasar |
|---|---|---|
| tahap 1 | **variabel UEFI di RAM** (`PcdEmuVariableNvModeEnable=TRUE` di SiliciumPkg), log di zona ramoops RAM `0xB0000000` | `uefi-pipa` `SiliciumPkg.dsc.inc`; driver vendor proprietary (UFS DXE dll.) tidak bisa diaudit di level kode |
| lengkap | + XNU: `sheng-data-persist=2` menulis halaman Data yang berubah ke *store window* setelah root image **di dalam userdata**; tidak menulis partisi lain | `board.toml` kernel_args, README UniXNU-pipa |
| lengkap di userdata Android biasa | root terverifikasi tidak cocok → tidak mount → tidak ada tulisan Data | `native-ufs-root=1` + VerifiedRoot |

## Perlindungan di skrip

| Risiko | Penanganan |
|---|---|
| dua tablet / tablet salah | setiap `adb`/`fastboot` memakai `-s <serial>`; ambigu, offline, unauthorized, bukan pipa, atau `ro.serialno` ≠ serial → ditolak |
| perintah gagal diam-diam | `Invoke-Native` memeriksa exit code tiap perintah; WSL dicek `$LASTEXITCODE` |
| firmware gagal ditarik, cache lama | tarik ke `.part`, cek exit + ukuran; gagal → file lama dipindah ke `*.stale` |
| fakta dari tablet lain | `unit-facts.json` menyimpan SHA-256 serial; `flash-userdata` mencocokkannya dengan tablet di fastboot |
| ukuran userdata berubah | `getvar partition-size:userdata` dan `logical-block-size` dibaca ulang dan harus sama persis dengan pengukuran |
| backup "ada folder" | `manifest.json` (jumlah file tablet vs lokal, ukuran, SHA-256, exit pull) dicek ulang `Test-Backup` |
| BOM/CRLF | file ditulis UTF-8 tanpa BOM; parser Python menerima BOM/CRLF |
| path dengan spasi / kutip | argumen ke bash di-single-quote (`ConvertTo-BashQuoted`); skrip WSL yang berisi `"` ditolak |

Backup **mencakup** `/sdcard` (DCIM, Download, Documents, dll.). **Tidak mencakup** data privat aplikasi, akun, Wi-Fi, pengaturan, dan `Android/data`/`obb` (Android 11+ tidak bisa dibaca via adb). Cadangkan itu lewat aplikasinya atau akun Xiaomi/Google.

## Firmware yang tidak ditarik `pipa.ps1 firmware`

- `a650_sqe.fw`: linux-firmware `qcom/a650_sqe.fw` (dari kernel.org/gitlab kernel-firmware), taruh di `work\UniXNU-pipa\.cache\firmware\linux-firmware\`.
- Touch: ada **dua varian panel** (`nt36532_tianma.bin`, `nt36532_csot.bin` di pipa-mainline). File `_tm` referensi = Tianma. Cek nama panel di `unit-facts.json` sebelum memilih.
