# Arsitektur yang dipilih

## Satu pasangan yang konsisten

| Lapisan | Pilihan | Versi/commit | Alasan |
|---|---|---|---|
| Firmware perangkat | XBL/ABL stok Xiaomi (tidak disentuh) | — | `fastboot boot` memuat image ke RAM; tidak ada yang ditulis |
| UEFI | **uefi-pipa** (Mu-Silicium `pipaPkg` + UniXNU, UniXNUDxe, ShengBootMemoryDxe, DarwinBoot) | `1f6a1520` | satu-satunya implementasi yang sudah membawa pipaPkg **dan** loader Darwin. hakios-uefi tidak ditumpuk |
| Loader | DarwinBoot (di dalam FV) via menu UniXNU | UniXNU `ae687009` | dipakai unit referensi sampai home screen |
| Kernel | XNU **xnu-10063.141.1** (`d8b80295`) + patch UniXNU + driver pipa | via `unixnu.lock` | generasi kernel iOS 17; cocok dengan kernelcache 21H461 yang di-prelink |
| Kext Apple | dari kernelcache IPSW yang sama (prelink, 31 root bundle di `board.toml`) | 21H461 | ABI kernel/kext harus satu rilis |
| Userland | **iPadOS 17.7.11 (21H461), iPad7,1 / j120ap**, tidak dimodifikasi | IPSW Apple CDN | lihat ARM64 di bawah |
| Profil OS | `ipados-17.7.11-21H461` | UniXNU `profiles/` | profil yang dipakai semua record pipa |
| Device repo | **xVanTuring/UniXNU-pipa** + overlay per unit dari proyek ini | `cdb3d627` | satu-satunya fork pipa dengan bukti perangkat (dilaporkan) |

HakiOS **tidak** dipilih sebagai basis: XNU 8796 + userland iOS 16.5 iPhone X tidak bisa dicampur dengan kernelcache/kext 17.7.11. HakiOS juga tidak punya lapisan SM8250, dan userland-nya iPhone, bukan iPadOS. HakiOS tetap dipakai sebagai donor, lihat [AUDIT.md §7](AUDIT.md).

## ARM64 vs ARM64e, PAC, ukuran page

- **iPad7,1 = A10X (T8011)**: userland `arm64` biasa **tanpa** pointer authentication. Snapdragon 870 (Cortex-A77/A55, ARMv8.2-A) tidak punya PAC (fitur ARMv8.3). Karena itu dipilih IPSW A10X, bukan iPad dengan A12+ (`arm64e`). Mengubah flag compiler tidak bisa membuat binary arm64e berjalan tanpa PAC: instruksi `PACIASP`/`AUTIASP` jatuh ke NOP-space, tetapi `BRAA`/`LDRAA` tidak.
- **Page:** XNU dibangun dengan page **4 KiB** ("source 4K XNU", kit `ArmSmmu4K`). Segmen Mach-O iOS diselaraskan 16 KiB, kelipatan 4 KiB, sehingga bisa dipetakan. Hal sebaliknya (binary 4K di kernel 16K) yang tidak bisa. Ini dilaporkan berjalan di unit referensi, belum diverifikasi di unit Abian.
- **dyld/shared cache:** berasal dari IPSW yang sama dengan kernelcache, tanpa campuran rilis.

## Rantai boot

```
XBL → ABL (stok, bootloader unlocked)
  └─ fastboot boot boot.img          (header v1, page 2048, base 0x10000000; TIDAK ditulis ke partisi)
       kernel  = shim 192 B + SILICIUM_UEFI.fd (3 MiB, gzip) + pipa.dtb terlampir
       ramdisk = volume FAT "PIPAESP" ≤ 192 MiB (config UniXNU, kernelcache, ADT, trust cache, Data seed)
     ABL memuat kernel+ramdisk di jendela 0xA0000000+0x10000000
  └─ UEFI (FD 0x9FC00000) → ShengBootMemoryDxe menerbitkan ramdisk sebagai block device
  └─ Menu UniXNU → DarwinBoot: pilih run memori bebas pertama ≥ owned_memory_size, bangun ADT, ExitBootServices
  └─ XNU (4 KiB) → driver pipa → PipaUfs mount root APFS dari jendela userdata → launchd → SpringBoard
```

Log: firmware dan kernel menulis ke zona konsol ramoops stok (`0xB0000000`, 4 MiB). Kernel me-restart ke fastboot dengan warm reset (log tetap utuh). Log dibaca lewat image pembaca (`fastboot boot`) yang menampilkan disk USB `PIPALOG`. Di Windows: `pipa.ps1 log`.

## Nilai per unit {#per-unit-values}

Hanya empat nilai yang diubah `tools/pipa_board.py` dari `board.toml` upstream. Selainnya identik byte-per-byte:

| Kunci | Referensi (16 GB/128 GB) | Unit ini | Sumber |
|---|---|---|---|
| `[payload] dram_size` | `0x980000000` | `0x200000000` (akhir bank terakhir − `0x80000000`) | `unit-facts.json` (diukur) atau DTB stok (hanya untuk build) |
| `[payload.adt] owned_memory_size` | `0x170000000` (5,75 GiB) | `0x100000000` (4 GiB) untuk ronde awal | `overlay.toml`. `check_memory.py`: 5,75 GiB di 8 GB hanya menyisakan ~4 MiB (asumsi firmware memakai 256 MiB di puncak bank) |
| `[userdata] first_lba/last_lba` | `0x293000..0x1d387fa` | **diukur dari GPT unit ini** | sampai diukur, ditandai `NOT-FOR-FLASH` dan semua jalur flash menolak |
| `[payload] title` | — | nama proyek | — |

Prediksi jendela XNU (`check_memory.py`, DTB stok): base `0xffc20000`, sama dengan pengamatan unit referensi untuk 5,75 GiB. Dengan 4 GiB, sisa ruang di run itu ≈ 1,8 GiB.

## GPU {#gpu}

| Jalur | Status | Kecocokan ABI dengan 17.7.11 | Keputusan |
|---|---|---|---|
| **AdrenoMetal (Metal → Vulkan/Turnip)** di atas driver kernel `Adreno650` | dilaporkan jalan di pipa: lock screen dan home screen lewat Metal, 40–54 fps saat UI bergerak; sudut membulat salah di pass GMEM | dibangun untuk 17.7.11 | **dipakai** |
| hakios-metal (model perintah Metal native) | 110–115 fps di Adreno 642L (redwood), iOS 16.5 | ABI iOS 16.5; perlu port | dievaluasi ulang setelah jalur pertama stabil |

Membedakan akselerasi dari fallback: log kernel `gpu stack:`, baris `LIVE busy` (counter GMU), `metal table:` dan `framebuffer:`. Tanpa publish file plugin, UI dirender CPU (fallback). [TESTING.md](TESTING.md) menjelaskan cara membuktikannya.

## Driver Linux → XNU

Driver Linux tidak dimuat. Logikanya diadaptasi ke IOKit/kernel XNU: register, urutan power, dan tabel diambil dari sumber Linux v6.6 dan vendor (dengan atribusi di header file). Interrupt lewat GICv3 `ArmCpu`, DMA lewat SMMU `ArmSmmu4K`. Locking dan lifecycle mengikuti IOService. Pola ini sudah dipakai upstream (`A650Gmu.c` ← `a6xx_gmu.c`, `NativeBattery` ← `qpnp-fg-gen4.c`). Proyek ini mempertahankannya untuk driver baru (Wi-Fi, audio, backlight).
