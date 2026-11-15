# Prosedur pemulihan

Prinsip proyek ini: **boot sementara dulu**. `fastboot boot` memuat image ke RAM dan tidak menulis apa pun. Satu-satunya penulisan permanen adalah `fastboot flash userdata` (menghapus data Android), dan hanya lewat `pipa.ps1 flash-userdata -IUnderstandDataLoss` setelah semua gate lulus. Bootloader, `persist` (kalibrasi), modem, dan slot boot tidak pernah disentuh.

## Sebelum menulis apa pun

1. `pipa.ps1 backup` (Android, USB debugging): menarik `/sdcard` dan `getprop`. Data aplikasi perlu dicadangkan lewat aplikasinya masing-masing (akun Xiaomi/Google, WhatsApp, dll.).
2. `adb reboot bootloader`, lalu `pipa.ps1 backup-fastboot`: menyimpan `fastboot getvar all` (slot aktif, ukuran partisi, status unlock).
3. Unduh **fastboot ROM HyperOS resmi untuk pipa** dengan region yang sama seperti tablet (lihat `ro.build.fingerprint` di `getprop.txt`). Simpan bersama Mi Flash Tool atau `platform-tools`.

## Gejala dan tindakan

| Gejala | Tindakan |
|---|---|
| Layar hitam / hang setelah `fastboot boot` | Tahan **Power + Volume Down** ~10 detik sampai logo fastboot. Tidak ada yang tertulis, Android tetap utuh |
| Kernel panic | Kernel me-restart ke fastboot sendiri dalam 10 detik (`BootRamoops.c`). Ambil log dengan `pipa.ps1 log -Reader <log-reader.img>` |
| Tablet kembali ke Android saat reboot normal | Wajar. Image sementara tidak tersimpan |
| Setelah `flash-userdata`, Android bootloop | `fastboot -w` (hapus userdata dan cache, lalu Android membuat ulang userdata) atau flash fastboot ROM resmi tanpa mengunci bootloader (`flash_all.bat`, **bukan** `flash_all_lock.bat`) |
| Partisi lain rusak (tidak disentuh skrip ini, tapi untuk jaga-jaga) | fastboot ROM resmi `flash_all.bat` |
| Tidak bisa masuk fastboot sama sekali | Isi daya ≥ 30 menit, lalu Power + Volume Down. EDL/9008 butuh akun resmi Xiaomi: hubungi service center |

## Yang tidak dilakukan proyek ini

- `fastboot flash boot|vendor_boot|dtbo|vbmeta|persist|modem|bluetooth|dsp|...`, `fastboot erase`, `fastboot oem ...`, `fastboot flashing lock/unlock`.
- Menyalin `persist` atau data kalibrasi perangkat lain.
- Menyimpan nomor seri: kolektor hanya menyimpan SHA-256-nya. *Platform seed* (`UNIXNU_UNIQUE_CHIP_ID`) tidak pernah masuk Git (`.cache/platform-seed`, di-ignore).
