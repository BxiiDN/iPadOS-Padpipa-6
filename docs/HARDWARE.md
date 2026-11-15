# Hardware Xiaomi Pad 6 (pipa) dan jalur driver

Kolom **Sumber** menunjuk file yang memuat nilainya. **Diukur di unit ini** baru terisi setelah `pipa.ps1 collect`.

| Blok | Hardware | Nilai kunci | Sumber | Driver XNU | Status upstream (dilaporkan) |
|---|---|---|---|---|---|
| CPU | 4× Cortex-A55 (MPIDR 0x000–0x300) + 3× A77 + 1× A77 Prime (0x400–0x700) | GICv3 `0x17a00000`/`0x17a60000` stride `0x20000`, timer 19,2 MHz, PSCI | UniXNU-pipa `make-pipa-adt.py`, DTB | `ArmCpu` (pipa), IPI sebagai SPI 952–959 | 8 core, 2 cluster E/P, EPSS ke level atas |
| Memori | LPDDR5 8 GB | bank `0x80000000+0x3bb00000`, `0xc0000000+0x1c0000000` (DTB stok) | `pipa.dtb` `/memory` | DarwinBoot window | **ukur unit** |
| Reserved | hyp, AOP, SMEM, TZApps, PIL (`0x86200000+0xc500000`), splash `0x9c000000`, ramoops `0xb0000000` | 22 carve-out statis | `MemoryMapLib.c`, DTB | — | `check_memory.py`: semua no-map ter-cover |
| Storage | UFS 3.1, host `0x1d84000`, SMMU stream `0xe0`/`0x4e0` | userdata = jendela root | UniXNU-pipa README, DTB `ufshc@1d84000` | `PipaUfs` | root APFS dari UFS. **GPT 256 GB: ukur unit** |
| Display | panel dual-DSI video `mdss_dsi_m82_36_02_0a_dual_dphy_video` 1800×2880 @120 Hz | GOP framebuffer di splash region | README referensi | `GopFramebuffer` (CPU/GPU copy, 60 Hz tetap, tanpa vsync) | jalan; tanpa mode-setting DSI/MDSS |
| Backlight | KTZ8866 I2C `0x11` | — | DTB `ktz8866@11`, `CONFIG_BACKLIGHT_KTZ8866` | **belum ada** | kecerahan = yang ditinggalkan firmware |
| GPU | Adreno 650v3, chip id `0x06050002`, GMEM 1,125 MiB | GMU, SQE (linux-firmware 0x112), zap PAS 13 | README referensi | `Adreno650` + `AdrenoMetal`/Turnip | Metal jalan, 40–54 fps |
| Touch | Novatek NT36532, GENI SPI QUP0 SE4 `0x990000` 9,6 MHz, IRQ TLMM 39, reset GPIO33 | 0..17999 × 0..28799 | `TouchBoard.h`, DTB `novatek@0` | `PipaNovatekTouch` + `QcomGeniSpi` | jalan, ~120 laporan/detik |
| Tombol | PON PM8150 (power, vol−), PM8150 GPIO6 (vol+) | SPMI | `Buttons.c` | paket pipa | jalan |
| Baterai | PM8150B fg-gen4 (**varian pipa**), 8840 mAh | SPMI USID 2, SOC `0x4009` | `NativeBatteryBoard.h`, MiCode defconfig | `NativeBattery` → `IOPMPowerSource` | **belum dijalankan** di tablet. Bandingkan dengan `qpnp-fg-gen4-pipa.c` |
| Charger | SMB5 + bq2597x + SMB1390 | — | MiCode `smb5-lib-pipa.c` | hanya dibaca | proteksi tetap di firmware/PMIC; watchdog charger tidak di-pet (lihat README referensi) |
| Wi-Fi | QCA6390 PCIe0 (MHI) | WLAN_EN GPIO20, PERST GPIO79, CLKREQ GPIO80 | DTB `cnss-qca6390`, defconfig | donor UniXNU-j716f `Ath12kWifi` | **belum** |
| Bluetooth | QCA6390 UART (QUP0 SE6) | BT_EN GPIO21, SW_CTRL GPIO124 | DTB, BxiiDN record | donor `QcaBluetooth` | **belum** |
| Audio | LPASS bolero + WCD938x + 4× AW882xx (I2C `0x34–0x37`), ADSP | `aw882xx_acf.bin`, `adsp.mdt` | DTB, LineageOS proprietary-files | perlu ADSP PAS + routing; donor HakiOS `hakios.adsp.c` | **belum** |
| Sensor | accel/gyro/cahaya di SSC (SLPI) | — | DTB `qcom,msm-ssc-sensors` | perlu SLPI PAS + QMI SSC | **belum** |
| Kamera | CAMSS (cam-isp, icp, ipe, bps), sensor via CCI | — | DTB | — | **belum**; butuh firmware ICP + tuning |
| Video HW | Venus | `firmware-xiaomi-pipa-venus` | postmarketOS | — | **belum**; decode = CPU |
| USB | DWC3 `0x0a600000`, PS5169, FSA4480 | — | MemoryMapLib, DTB | `UsbDebug` (di fork BxiiDN, mati default) | charging oleh PMIC; data belum |
| Haptic | AW8697 | **disabled** di DTB | DTB | — | tidak ada hardware aktif |

## Firmware proprietary

Daftar lengkap ada di [`manifest/firmware.toml`](../manifest/firmware.toml). Tidak ada satu pun yang masuk Git; `check_firmware.py --scan-repo` menolak commit seperti itu.

| File | Dari mana | Catatan |
|---|---|---|
| `a650_gmu.bin`, `a650_zap.elf` | `/vendor/firmware/` tablet sendiri (`pipa.ps1 firmware`) | zap ditandatangani Xiaomi; **jangan** pakai digest TB-J716F |
| `a650_sqe.fw` | linux-firmware `qcom/a650_sqe.fw` (v0x112) | milik vendor v0x093 ditolak Linux |
| `novatek_nt36532_m82_fw_tm.bin` | tabel firmware built-in kernel stok | harus sesuai panel maker unit ini |
