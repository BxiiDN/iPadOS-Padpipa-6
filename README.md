# iPadOS-Padpipa-6

Port **iPadOS 17.7.11 asli** (XNU + userland Apple yang tidak dimodifikasi) untuk **Xiaomi Pad 6 (pipa, Snapdragon 870 / SM8250-AC, Adreno 650)** milik sendiri, varian **8 GB RAM / 256 GB**. Dibangun dari Windows 11 lewat WSL2.

> **Status jujur (2026-11-16):** belum ada satu pun ronde di tablet target. UEFI dan boot image tahap 1 sudah **dibangun dan divalidasi** dari checkout bersih. Kernel, payload, dan userdata menunggu toolchain di WSL2, IPSW, dan pengukuran tablet. Rinciannya per area ada di [STATUS.md](STATUS.md).

## Apa isi repo ini

Repo ini **bukan** salinan UniXNU atau HakiOS. Isinya lapisan untuk satu unit fisik di atas sumber yang dikunci:

- **Audit dan arsitektur**: [docs/AUDIT.md](docs/AUDIT.md) (HakiOS vs UniXNU, selisih dokumentasi, sumber Xiaomi/LineageOS) dan [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) (rantai boot, ARM64/PAC/page, pilihan GPU).
- **Kunci sumber**: [manifest/sources.lock.toml](manifest/sources.lock.toml) (commit, tanggal, lisensi, peran tiap sumber) dan [manifest/firmware.toml](manifest/firmware.toml) (firmware proprietary, asal, digest).
- **Konfigurasi pipa per unit**: `device/pipa-8g256/` dan `tools/pipa_board.py`. `board.toml` referensi berasal dari tablet **16 GB (di-upgrade) / 128 GB**, jadi `dram_size`, `owned_memory_size`, dan jendela userdata ditulis ulang dari fakta unit ini.
- **Gate otomatis**: `tools/checks/`, mendeteksi memory overlap, simbol hilang, firmware salah, board keliru, dan image tidak valid, plus 34 test regresi di `tests/`.
- **Pintu masuk Windows**: `scripts/windows/pipa.ps1` (adb/fastboot di Windows, build di WSL2) dan `scripts/wsl/build.sh`.
- **Log dan checksum sesi**: `logs/`.

## Mulai cepat (Windows 11)

```powershell
# 0. Prasyarat: bootloader pipa sudah unlocked, Android SDK Platform-Tools, WSL2 Ubuntu 24.04
git clone https://github.com/BxiiDN/iPadOS-Padpipa-6; cd iPadOS-Padpipa-6
.\scripts\windows\pipa.ps1 doctor

# 1. Ukur tablet INI (Android, USB debugging; read-only)
.\scripts\windows\pipa.ps1 collect        # bank memori, GPT 256 GB, panel -> device\pipa-8g256\unit-facts.json
.\scripts\windows\pipa.ps1 firmware       # salin firmware GPU/audio/Wi-Fi ke .cache, cetak SHA-256
.\scripts\windows\pipa.ps1 backup         # /sdcard + getvar all, sebelum penulisan apa pun

# 2. Build yang tidak butuh IPSW/toolchain: UEFI + boot image tahap 1 + semua gate
.\scripts\windows\pipa.ps1 build all

# 3. Ronde pertama: boot SEMENTARA (tidak menulis apa pun), harus sampai menu UniXNU
.\scripts\windows\pipa.ps1 boot out\pipa-8g256\boot-stage1.img

# 4. Kernel + payload (sekali: toolchain, berjam-jam)
.\scripts\windows\pipa.ps1 setup
wsl -d Ubuntu-24.04 -- bash -lc "export UNIXNU_IPSW=/mnt/c/ipsw/iPad_Pro_HFR_17.7.11_21H461_Restore.ipsw; scripts/wsl/build.sh kernel && scripts/wsl/build.sh payload"
```

Penulisan permanen satu-satunya, `flash-userdata`, menghapus data Android dan hanya berjalan jika GPT unit ini sudah diukur, board cocok, backup ada, dan frasa konfirmasi diketik. Lihat [docs/RECOVERY.md](docs/RECOVERY.md).

## Basis yang dipilih (ringkas)

| Lapisan | Pilihan |
|---|---|
| UEFI + loader | xVanTuring/uefi-pipa `1f6a1520` (Mu-Silicium pipaPkg + UniXNU + DarwinBoot) |
| Build driver + komponen generik | UniXNU/UniXNU `ae687009` |
| Device repo | xVanTuring/UniXNU-pipa `cdb3d627` + overlay unit ini |
| Kernel | XNU xnu-10063.141.1 (4 KiB page) |
| Userland | iPadOS 17.7.11 (21H461) iPad7,1, arm64 tanpa PAC, diunduh sendiri dari Apple |
| GPU | Adreno650 (kernel) + AdrenoMetal → Turnip (Mesa `85fda3b3`) |

HakiOS (`oosexgang/hakios-xnu-kernel`, XNU 8796 / iOS 16.5 iPhone X, tanpa SM8250) dipakai sebagai donor (hakios-metal, WLFW, ADSP), bukan basis. Alasannya ada di [docs/AUDIT.md](docs/AUDIT.md).

## Yang tidak ada di sini

Tidak ada file Apple, IPSW, kernelcache, atau firmware proprietary di Git (`check_firmware.py --scan-repo`). Layanan Apple (aktivasi, Apple ID, iCloud, App Store) tidak menjadi tujuan. Proyek riset independen, tidak berafiliasi dengan Apple, Xiaomi, atau Qualcomm. Lisensi tooling: MIT ([LICENSE](LICENSE)); sumber upstream memakai lisensinya sendiri ([NOTICE](NOTICE)).
