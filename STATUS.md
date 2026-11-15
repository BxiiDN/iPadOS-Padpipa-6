# Status (2026-11-16)

Target unit: **Xiaomi Pad 6 pipa, SM8250-AC, 8 GB, 256 GB**. Belum ada satu pun ronde di tablet ini, jadi kolom
`device-tested` masih kosong. Status upstream di unit referensi (16 GB/128 GB) dicantumkan terpisah dan tidak dihitung.

| Area | Status proyek ini | Bukti | Upstream (dilaporkan, unit referensi) |
|---|---|---|---|
| Audit & pemilihan arsitektur | `implemented` | [docs/AUDIT.md](docs/AUDIT.md), [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | — |
| Kunci sumber, checkout bersih | `build-tested` | `tools/bootstrap.py --verify`: 3/3 OK; `logs/build-bootstrap-*.log` | — |
| Board per unit (8 GB) | `build-tested` | `logs/build-board-*.log`, `out/…/board.diff`: hanya `dram_size`, `owned_memory_size`, `title` + penanda NOT-FOR-FLASH | — |
| Fakta unit (bank memori, GPT 256 GB, panel) | `blocked` | butuh tablet: `pipa.ps1 collect` | — |
| `unixnu fetch` / `defconfig` / `tree` | `build-tested` | `logs/unixnu-fetch.log`, `logs/unixnu-status-tree.log` (17 driver, 6 kit, 3 patch series ter-resolve) | — |
| UEFI FD (Mu-Silicium pipaPkg + UniXNU + DarwinBoot) | `build-tested` | `logs/unixnu-build-firmware.log`, FV terkompresi `0x196b38`/`0x300000` (53%), SHA-256 di [logs/SHA256SUMS](logs/SHA256SUMS) | menu UniXNU tampil |
| Reprodusibilitas bit FD | `blocked` | dua build bersih (direktori berbeda) → ukuran sama, SHA-256 berbeda ([logs/SHA256SUMS](logs/SHA256SUMS)); dugaan: path build/timestamp di build DEBUG EDK2. Langkah: build dua kali di path sama, `cmp` FV terdekompresi, lalu `SOURCE_DATE_EPOCH`/RELEASE | — |
| Boot image tahap 1 (tanpa payload) | `build-tested` | `check_bootimg.py --stage1` PASS (v1, page 2048, shim 192 B, FD 0x300000, DTB terlampir) | sampai menu UniXNU |
| Gate memori (overlap, carve-out, jendela XNU) | `build-tested` | `check_memory.py` PASS; prediksi base `0xffc20000` | — |
| Regresi gate | `build-tested` | 34/34 lulus (`logs/tests.log`) | — |
| Host test driver upstream (touch, battery, buttons, GPU power, gestures) | `build-tested` | `logs/host-tests-upstream.log`: 5/5 | — |
| Host test GMU (`A650GmuTests`) | `blocked` | `AdrenoHfi.c:5 #error … little-endian AArch64`; host x86_64. Jalankan di host ARM64 atau di bawah `qemu-aarch64` | lulus di Mac Apple Silicon maintainer |
| Kernel XNU + arsip driver | `blocked` (di sini) | butuh toolchain Linux UniXNU (LLVM ter-patch + cctools-port, `setup-toolchain.py`, berjam-jam) dan apt; sandbox ini tidak punya apt. Siap jalan di WSL2: `pipa.ps1 setup`, `pipa.ps1 build kernel` | 8 core, root UFS |
| Payload + boot image penuh | `blocked` | butuh kernel di atas + IPSW lokal (CDN Apple tidak terjangkau dari sandbox) + platform seed | sampai home screen |
| Userdata root image + flash | `blocked` (disengaja) | `flash_gate.py` menolak sampai GPT unit ini terukur | ditulis lewat `fastboot flash userdata` |
| Data seed / skip-setup | `blocked` | butuh macOS `hdiutil` (GitHub macOS runner atau Mac) | — |
| Display (GOP framebuffer) | `implemented` (upstream) | `drivers/GopFramebuffer` | jalan, tanpa vsync |
| Backlight KTZ8866 | `blocked` | belum ada driver | — |
| Touch NT36532 | `implemented` (upstream) | `PipaNovatekTouch`, firmware `_tm` menunggu nama panel unit | jalan |
| Tombol | `implemented` (upstream) | `package/Buttons.c` | jalan |
| GPU Adreno 650 + Metal | `implemented` (upstream) | `Adreno650`, `AdrenoMetal`, Mesa `85fda3b3` | 40–54 fps, sudut membulat salah di GMEM |
| Baterai | `implemented` (upstream) | `NativeBattery`; perlu diff dengan `qpnp-fg-gen4-pipa.c` | belum dijalankan |
| Wi-Fi / Bluetooth | `blocked` | belum diintegrasikan; donor UniXNU-j716f (SM8250+QCA6390, MHI/BLE device-verified) | tidak ada |
| Audio (ADSP + 4× AW882xx) | `blocked` | belum dimulai | tidak ada |
| Sensor (SSC/SLPI), kamera, video HW | `blocked` | belum dimulai | tidak ada |
| Sleep/wake | `blocked` | `ArmCpu` tidak mendukung sleep (upstream: auto-dim dimatikan) | tidak ada |

## Penghambat berikutnya, dengan perbaikannya

1. **Fakta unit**: `scripts/device/collect-unit-facts.sh`. Tanpa root, `/memory` DT biasanya tidak terbaca; GPT terbaca dari sysfs. Perbaikan: jalankan dengan su, atau baca peta memori dari log UEFI ronde R1.
2. **Toolchain kernel**: `UniXNU/scripts/linux/setup-toolchain.py` di WSL2 Ubuntu 24.04 (`pipa.ps1 setup`).
3. **IPSW**: unduh `iPad_Pro_HFR_17.7.11_21H461_Restore.ipsw` dari URL di `board.toml`, set `UNIXNU_IPSW`. Digest OS/SystemOS dicek oleh `unixnu`.
4. **`owned_memory_size`**: mulai 4 GiB; naikkan setelah peta memori UEFI unit ini terbaca (`check_memory.py --firmware-top-reserve <nilai nyata>`).
5. **Firmware**: `pipa.ps1 firmware`, lalu pin digest di `manifest/firmware.toml`; `a650_sqe.fw` dari linux-firmware.
