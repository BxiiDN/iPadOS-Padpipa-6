# Audit sumber (2026-11-16)

Semua commit di bawah dikunci di [`manifest/sources.lock.toml`](../manifest/sources.lock.toml). Yang diperiksa: kode, riwayat commit, README, dokumentasi UniXNU, DTB stok, dan defconfig vendor. Tidak ada yang diambil dari ingatan.

## 1. Lokasi aktif HakiOS dan perubahan nama

| Repository | Status saat audit | Bukti |
|---|---|---|
| `oosexgang/hakios-xnu-kernel` | **aktif**, HEAD `63fc2b46` (2026-11-06). `hackios-xnu-kernel` mengarah ke repo yang sama (redirect, HEAD identik) | `git ls-remote` keduanya → `63fc2b46…` |
| `oosexgang/hakios-os` | **belum ada.** README menyebutnya sebagai nama mendatang | `git ls-remote` → tidak ditemukan |
| `oosexgang/hackios-xnu-userland` | **penunjuk saja**: "Moved into the main HakiOS repository", isinya di `userland/` repo kernel | HEAD `2573c4a8`, README |
| `oosexgang/hakios-uefi` | aktif, `687fa6c6` (2026-10-27): overlay branding/boot path untuk Mu-Silicium | isi repo: `apply.sh`, `hakios.patch`, `branding/` |

**Kecocokan versi HakiOS:** `VERSION` → `XNU = xnu-8796.121.2`, `DARWIN = 22.5.0`. `sysimage/unpack.sh` meminta userland **16.5 (20F66, iPhone X)**. `devices/manifest.conf` hanya berisi `redwood` (POCO X5 Pro, SC7280) dan `qemu`. Tidak ada SM8250, tidak ada iPadOS.

## 2. Selisih status UniXNU-pipa: dokumentasi vs README

Brief mencatat dokumentasi menyebut "gagal mount root" sedangkan README melaporkan sampai UI + GPU. Hasil pencocokan:

| Sumber | Isi | Commit yang dirujuk | Tanggal |
|---|---|---|---|
| `UniXNU/docs/devices/pipa.md` | "stops at `Failed to mount root device @IOKitBSDInit.cpp:984`" | README di `c28476e` | ditulis dari baris pembuka README |
| `UniXNU/devices.toml` (`pipa`) | "Hardware XNU boot; root mount fails" | `uefi-pipa@1f6a1520` | — |
| Baris pertama README UniXNU-pipa | "(2026-10-23) … XNU starts and stops where it needs storage" | `cdb3d627` | basi, tidak diperbarui |
| Isi README UniXNU-pipa, "Stage 4 to 7" | iPadOS 17.7.11 sampai home screen, 8 core, root dari UFS, touch, tombol, Adreno 650 via GMU, Metal→Vulkan (Turnip) 40–54 fps; tanpa audio/jaringan | `cdb3d627` | 2026-10-24 s.d. 26 |
| Riwayat commit | `fe2dc50` UFS read check (10-23 21:57) → `36276c4` "iPadOS root from UFS and user space up to SpringBoard" (10-23 22:25) → `476067e`…`2d8b1cb` GMU, GX, perintah pertama (10-24) → `f5f8412` "APRIV on the Adreno 650; the UI renders through Metal" (10-24 18:53) → `5d36a0a` battery, gestures (10-25) | — | — |

**Kesimpulan:** halaman dokumentasi dihasilkan dari baris pembuka README yang tidak diperbarui. Kode dan riwayat commit mendukung isi README (root UFS → SpringBoard → Metal). Itu klaim **maintainer dan tabletnya sendiri**. Log mentah ronde perangkat tidak ada di repo (`.cache/`, `out/` di luar Git), jadi bagi proyek ini statusnya "dilaporkan upstream", bukan "terbukti di unit Abian".

## 3. Kecocokan perangkat referensi dengan unit target

| | Unit referensi (xVanTuring) | Unit target (Abian) | Akibat |
|---|---|---|---|
| RAM | **16 GB (di-upgrade)**: 3 bank, bank ke-3 di `0x800000000` | 8 GB | `dram_size 0x980000000` salah untuk 8 GB → `0x200000000` |
| Storage | 128 GB: userdata `sda34` LBA `0x293000..0x1d387fa` (106,6 GiB) | 256 GB | jendela userdata **wajib diukur** dari GPT unit ini |
| Panel/touch | panel maker `0x36` → `novatek_nt36532_m82_fw_tm.bin` | belum diukur | firmware touch dipilih setelah nama panel terbaca |

DTB stok pipa (`uefi-pipa/Resources/DTBs/pipa.dtb`) berisi `/memory` = `0x80000000+0x3bb00000, 0xc0000000+0x1c0000000`, yaitu tata letak 8 GB tanpa bank ketiga. Ini cocok dengan dua bank pertama unit 16 GB. ABL menulis ulang `/memory` saat boot, jadi nilainya tetap harus dibaca dari unit Abian (`pipa.ps1 collect`).

Kode driver tidak meng-hardcode 16 GB (dicek: `grep 0x980000000|0x800000000` di `package/` dan `scripts/`). Nilainya hanya ada di `board.toml`, satu-satunya file yang diubah proyek ini (`tools/pipa_board.py`).

## 4. Fork lama milik akun ini: `BxiiDN/UniXNU-pipa`

`55fa7da3` (branch `pipa`) adalah tree TB-J716F yang dikonversi ke pipa. Status sendiri di record UniXNU: "nothing in this fork has been booted on a Xiaomi Pad 6". Yang dipakai dari sini: gagasan guard yang gagal untuk 8 GB/256 GB sampai unit diukur. Yang **tidak** dipakai: digest firmware di `proprietary-files.txt`, karena itu milik TB-J716F (Lenovo). Zap shader ditandatangani per OEM, jadi digest Lenovo tidak berlaku untuk pipa.

## 5. Pertanyaan hardware yang dijawab sumber Xiaomi/LineageOS

| Pertanyaan | Jawaban | Bukti |
|---|---|---|
| Gauge baterai: PM8150B fg-gen4 atau bq27z561 ganda? (DTB punya keduanya) | **fg-gen4 (versi pipa)**. bq27z561 dual tidak aktif | MiCode `pipa-t-oss@77dc8e22` `arch/arm64/configs/vendor/pipa_user_defconfig`: `CONFIG_QPNP_FG_GEN4_PIPA=y`, `#CONFIG_DUAL_FUEL_GAUGE_BQ27Z561 is not set`. Driver `qpnp-fg-gen4-pipa.c` berbeda dari generik; `NativeBattery` UniXNU-pipa diturunkan dari `qpnp-fg-gen4.c` generik, perlu dibandingkan |
| Wi-Fi/BT | QCA6390 via CNSS (PCIe), BT `CONFIG_BT_SLIM_QCA6390` | defconfig + DTB `qcom,cnss-qca6390` (reg `0xb0000000` di node itu adalah **IOVA SMMU**, bukan DRAM) |
| Audio | LPASS bolero + WCD938x + **4× Awinic AW882xx** (I2C `0x34–0x37`), ADSP | DTB `aw882xx_smartpa@34..37` status ok; LineageOS `proprietary-files.txt`: `vendor/firmware/aw882xx_acf.bin`, `misound_res_spk4ch.bin` |
| Backlight | KTZ8866 I2C `0x11` | DTB + `CONFIG_BACKLIGHT_KTZ8866=y` |
| Touch | Novatek `NVT-ts-spi` (NT36532) | DTB `novatek@0` |
| Sensor (accel/gyro/cahaya) | di balik SSC/SLPI (`qcom,msm-ssc-sensors`), bukan I2C langsung ke AP | DTB; butuh firmware SLPI + protokol QMI/SSC |
| Charger | SMB5 (pipa) + charge pump bq2597x + SMB1390 | MiCode `smb5-lib-pipa.c`, `bq2597x_charger_pipa.c` |
| Haptic | `aw8697_haptic@5A` **disabled** | DTB |
| USB-C | FSA4480 (audio switch), PS5169 redriver (di defconfig dimatikan) | DTB + defconfig |

## 6. Mesa, Freedreno, Turnip

UniXNU mengunci Mesa di `85fda3b3` (`scripts/data/adreno-compiler-inputs.json`, upstream `gitlab.freedesktop.org/mesa/mesa`) dengan 10 patch di `patches/mesa/` (`turnip-darwin-kmd.patch` dll.). Turnip berjalan di userspace iPadOS lewat plugin Metal `AdrenoMetal` yang menerjemahkan Metal ke Vulkan. Driver kernel `Adreno650` menyediakan submit, ring, GMU, dan SMMU. Bandingan jalur Metal ada di [ARCHITECTURE.md](ARCHITECTURE.md#gpu).

## 7. Donor yang dievaluasi

| Donor | Untuk apa | Status di donor | Catatan |
|---|---|---|---|
| UniXNU-j716f (`bf2d0f32`, Lenovo TB-J716F: SM8250 + QCA6390) | Wi-Fi, Bluetooth | **device-verified**: MHI Mission Mode, en0/wifid jalan, BT UART6 3,2 Mbps + bluetoothd menerima BLE advertising. Belum: asosiasi 802.11 | SoC dan chip identik → donor terbaik. Pin pipa (WLAN_EN GPIO20, BT_EN GPIO21, PERST GPIO79) perlu diverifikasi terhadap DTB pipa |
| HakiOS `hakios-metal` | GPU, jalur Metal native | 110–115 fps swipe di Adreno 642L (vs 50–57 Metal-on-Vulkan di HW yang sama) | ABI-nya untuk Metal iOS 16.5; perlu port ke ABI 17.7.11 |
| HakiOS `drivers/wifi/hakios.wlfw.c` | pertukaran WLFW QMI | stand-in untuk WCN6750 | rujukan urutan pesan ath11k |
| HakiOS `drivers/audio/hakios.adsp.c` | start ADSP (PAS) | langkah 1 audio di redwood | alamat milik redwood, harus diganti dengan nilai pipa |

## 8. Audit ulang 2026-11-16 (sesi 2)

### Input build kernel yang tidak dipublikasikan

Run macOS CI [`43771439646`](https://github.com/BxiiDN/iPadOS-Padpipa-6/actions/runs/43771439646) (Xcode 26.6, sumber terkunci) membuktikan urutan berikut: XNU **ter-compile**; arsip corecrypto ×2, ArmDTPlatform, ArmCpu, dan SoftwareAES **terbangun**; arsip ke-6 gagal. `tools/check_inputs.py` kini mendeteksi semua penyebabnya sebelum build:

| Input yang diminta `board.toml` / builder UniXNU-pipa `cdb3d627` | Ada di sumber publik? | Bukti |
|---|---|---|
| `build-arm-driver.py PipaUfs --sm8250` | **tidak**: `PipaUfs` dan `--sm8250` tidak ada di `components.toml`/`build-arm-driver.py` UniXNU `ae687009` maupun main `f7a263dd` (pilihan yang ada: `ShengUfs`, `NativeUfs`, …) | log CI: `invalid choice: 'PipaUfs'` |
| `build-verified-root-key.py --pin 70a5…` | **tidak**: tidak ada di UniXNU (`ae687009`, main), UniXNU-pipa, UniXNU-tb128fu `a9c3863d` | `git ls-tree` ketiganya |
| `build/verified-root-os/trusted-key.bin` (anchor `VROOTKEY` + modulus RSA-3072, 395 byte) | kunci milik owner tb128fu | README UniXNU-pipa, `kits/VerifiedRoot/tools/manifest.py` |
| `PIPA_DISPLAY_REFERENCE`: tree UniXNU-qemu + `gdb-stop.json` dari run DarwinBoot di **Hypervisor.framework** | butuh Mac Apple silicon dengan HVF; runner GitHub tanpa virtualisasi bersarang | `build-gop-legacy-display.py` baris 35–43 |
| `build/storage-abi/interface-audit.json` | generator publik ada (`audit-storage-interface.py`), tetapi gagal di tree ini karena file yang diharapkannya tidak ada | log CI `storage-audit` |
| firmware GPU/touch | ada pengganti publik untuk CI (linux-firmware `20250509`, pipa-mainline `842d35be`), **bukan** salinan dari tablet ini | `scripts/ci/fetch-ci-firmware.sh` |

Kesimpulan: kernel pipa seperti yang dikonfigurasi upstream **tidak bisa direproduksi dari sumber publik**. Ada dua jalan keluar, dan keduanya butuh kerja di luar repo ini: (a) maintainer mempublikasikan UniXNU lokal beserta skripnya; atau (b) port ulang ke komponen publik (`ShengUfs` dengan nilai SM8250 dari fork `PipaUfs`, kunci owner baru milik Abian dari `kits/VerifiedRoot/tools/manifest.py`, dan tree referensi display yang dibangun di Mac sendiri).

### Donor UniXNU-j716f

| | Hasil |
|---|---|
| Repo aktif | `Denis0x00/UniXNU-j716f`, HEAD `c91d5cd3` (2026-11-14) |
| Record UniXNU (`bf2d0f32`, 2026-11-09) | README saat itu: Wi-Fi & BT "Device-verified" (MHI Mission Mode, BLE) |
| **HEAD sekarang** | ditulis ulang: README menyatakan bring-up berhenti sebelum root lookup dan **tidak** membuktikan UFS, root, SpringBoard, touch, atau grafis. File Wi-Fi/BT (`WifiProbe.cpp`, `MhiBoot.c`, `BluetoothProbe.cpp`, …) **tidak ada lagi** di HEAD |
| Chipset/transport | QCA6390, PCIe0 (PARF `0x1c00000`, PHY `0x1c06000`, DBI `0x60000000`) + BT GENI UART QUPv3_0 SE6 |
| Pin di kode donor `bf2d0f32` | WLAN_EN 20, PERST# 79, CLKREQ 80, SW_CTRL 124, BT_EN 21, UART 16–19. Komentar header menyebut GPIO 80/81/82/94 dan `gcc-sm8550.c`: **basi**, bekas SM8550 (sheng) |
| Pin pipa (DTB stok) | WLAN_EN **20**, BT_EN **21**, SW_CTRL **124**, PERST# **79**, WAKE **81**, HS UART aktif `0x998000` (SE6): **sama** dengan konstanta donor |
| Keputusan | donor hanya dari `bf2d0f32` (dikunci); klaim device-verified donor dicatat sebagai klaim maintainer yang kemudian ditarik dari README HEAD. Firmware dan BDF wajib dari tablet ini |

### Varian panel

pipa-mainline (`842d35be`) membawa dua firmware touch, `nt36532_tianma.bin` dan `nt36532_csot.bin`. Driver backlight Xiaomi memilih arus LED penuh berdasarkan GPIO panel-id 30: CSOT `0xb1` (22,8 mA) atau BOE `0xc1` (24,4 mA). Unit referensi memakai touch `_tm`. **Varian panel unit ini harus diukur** sebelum memilih firmware touch.
