# Pengujian

Empat status, tidak dicampur:

| Status | Artinya | Bukti yang diterima |
|---|---|---|
| `implemented` | source/konfigurasi ada | path file |
| `build-tested` | compile/link/pack/test host lulus dari checkout bersih | log di `logs/` + checksum |
| `device-tested` | dijalankan di **tablet Abian** dan hasilnya tercatat | log ramoops (`pipa.ps1 log`), foto/video, angka |
| `blocked` | tidak bisa lanjut | file, fungsi, penyebab, langkah berikutnya |

Simulasi, CI, atau klaim upstream tidak pernah menjadi `device-tested`.

## Gate otomatis (setiap build, setiap PR)

| Gate | Mendeteksi | Perintah |
|---|---|---|
| `check_board.py` | board lain, IPSW selain 21H461, `dram_size` 16 GB di unit 8 GB, kernel args > 1000 byte, userdata tidak diukur tanpa penanda NOT-FOR-FLASH | `build.sh check` |
| `check_memory.py` | descriptor UEFI tumpang tindih, carve-out no-map tak ter-cover, MMIO di DRAM, boot image > jendela ABL, `owned_memory_size` tidak muat | `build.sh check` |
| `check_bootimg.py` | header ≠ v1/page 2048/base, kernel bukan gzip, tanpa DTB terlampir, FD > 3 MiB, ramdisk bukan FAT `PIPAESP`, image terpotong | otomatis sebelum `pipa.ps1 boot` |
| `check_firmware.py` | digest firmware salah, firmware wajib hilang, blob proprietary/Apple ter-commit | `build.sh kernel`, CI |
| `check_symbols.py` | simbol undefined di arsip driver yang tidak didefinisikan kernel | `build.sh kernel` |
| `flash_gate.py` | flash tanpa GPT terukur, sparse image rusak (setiap chunk diperiksa), ukuran ekspansi > jendela atau bukan kelipatan 4096 |
| `check_ipsw.py` | IPSW versi/build/model lain atau image root yang diubah |
| `check_inputs.py` | input kernel yang tidak tersedia (builder, komponen, kunci owner, referensi display, firmware) |
| `PipaLib.Tests.ps1` | serial ambigu/salah, exit code, cache firmware basi, backup palsu, BOM, path dengan spasi | otomatis sebelum `flash-userdata` |
| `tests/test_checks.py` | regresi pada gate itu sendiri (56 kasus Python, termasuk integrasi dengan data pipa asli; Pester untuk skrip Windows) | `python3 -m unittest discover -s tests` |

## Protokol ronde di perangkat

Catat setiap ronde di `logs/device-rounds.log` (ditulis otomatis oleh `pipa.ps1 boot`) dan simpan log ramoops di `logs/device/<waktu>/`.

| # | Ronde | Image | Lulus jika | Catat |
|---|---|---|---|---|
| R0 | fakta unit | — | `unitfacts.py show` → "usable for build/boot: yes" | bank memori, GPT, panel |
| R1 | UEFI + menu | `boot-stage1.img` | log Mu-Silicium tampil, lalu menu UniXNU ("no operating system") | foto layar, waktu ke menu |
| R2 | kernel tanpa root | payload tanpa argumen `native-ufs-root=1` | bar entry hijau/biru, panic `Failed to mount root device` | baris panic, TCR/SCTLR |
| R3 | UFS survey | `native-ufs-probe=16` | daftar LUN, kapasitas cocok dengan 256 GB | log `ufs:` |
| R4 | root + SpringBoard | setelah `flash-userdata` | lock screen | durasi boot, crash per proses |
| R5 | input | `pipa-touch=5`, `pipa-buttons=1` | swipe membuka kunci, tombol mengunci/bangun | sumbu, laporan/detik |
| R6 | GPU | `pipa-gpu=12` + addon | `metal table:` ada; `framebuffer:` sama dengan render CPU; fps saat page swipe | fps, `busy`, suhu |
| R7 | stres | 10× boot berulang, 30 menit page swipe | tanpa panic/hang | crash, RAM (`process:`), suhu |
| R8 | baterai | `pipa-battery=2` (hanya baca) | % dan arus dekat dengan Android | baris `battery:` vs Android |

**Membedakan render GPU dari fallback:** GPU dianggap aktif jika ada `NativeAdreno … published`, baris `metal table:` dengan draw > 0, counter `LIVE busy` > 0, dan sampel `framebuffer:` cocok. Tanpa publish file plugin, UI dirender CPU: angka `busy` ≈ 0 dan tidak ada `metal table:`. Framebuffer menyala saja tidak membuktikan akselerasi.

Jangan memaksa frekuensi maksimum terus-menerus untuk benchmark. `pipa-cpufreq=1` dan GPU 670 MHz adalah default upstream untuk bring-up. Ukur suhu dan bandingkan dengan level lebih rendah (`pipa-gpu-perf=<1..7>`).
