# Prosedur pemulihan

**Boot sementara dulu.** `fastboot boot` memuat image ke RAM dan tidak menulis partisi, tetapi kode yang dijalankannya punya akses ke hardware. Yang bisa ditulis tiap image diaudit di [WINDOWS.md](WINDOWS.md#what-a-booted-image-can-write): tahap 1 hanya RAM; image lengkap bisa menulis *store window* Data di dalam userdata setelah `flash-userdata`.

Satu-satunya penulisan permanen di skrip ini adalah `fastboot flash userdata`. Langkah itu menghapus data Android, dan `pipa.ps1 flash-userdata` hanya menjalankannya bila semua syarat ini terpenuhi:

1. `unit-facts.json` diukur dari tablet ini (`provenance.source = measured`, SHA-256 serial cocok dengan tablet di fastboot);
2. `flash_gate.py`: GPT dan board cocok, sparse image di-walk per chunk, ukuran ekspansi ≤ jendela userdata dan kelipatan 4096;
3. `getvar partition-size:userdata` dan `logical-block-size` yang dibaca ulang **sama persis** dengan pengukuran;
4. ada backup yang **lolos `Test-Backup`** untuk serial ini (manifest lengkap, jumlah file = laporan tablet, semua SHA-256 cocok);
5. frasa `HAPUS USERDATA <4 digit terakhir serial>` diketik.

Bootloader, `persist` (kalibrasi sensor/Wi-Fi), modem, `boot`/`vendor_boot`/`dtbo`/`vbmeta`, dan slot aktif tidak pernah disentuh. Skrip tidak memakai `erase`, `oem`, `set_active`, atau `flashing lock/unlock`.

## Sebelum menulis

1. Android, USB debugging: `pipa.ps1 backup` → `backup\<waktu>\manifest.json`, lalu dicek ulang otomatis. Yang **tidak** tercakup: data privat aplikasi, akun, Wi-Fi, pengaturan, `Android/data` dan `obb`. Cadangkan lewat aplikasinya atau akun Xiaomi/Google.
2. `adb reboot bootloader`, lalu `pipa.ps1 backup-fastboot` → `getvar-all.txt` (slot aktif, ukuran partisi, status unlock).
3. Unduh **fastboot ROM HyperOS resmi untuk pipa** dengan region yang sama dengan `ro.build.fingerprint` di `logs\firmware-*.json` atau `backup\*\manifest.json`.

## Gejala dan tindakan

| Gejala | Tindakan |
|---|---|
| Layar hitam / hang setelah `fastboot boot` | Tahan **Power + Volume Down** ~10 detik sampai fastboot. Tidak ada partisi yang ditulis |
| Kernel panic | Restart sendiri ke fastboot dalam 10 detik (`BootRamoops.c`). Ambil log: `pipa.ps1 log -Reader <img>` |
| Reboot normal masuk Android | Wajar: image sementara tidak tersimpan |
| Setelah `flash-userdata`, Android bootloop | `fastboot -s <serial> -w` (Android membuat ulang userdata), atau fastboot ROM resmi dengan `flash_all.bat` (**bukan** `flash_all_lock.bat`) |
| Data iPadOS rusak, Android tetap utuh | Tidak mungkin dua-duanya: userdata hanya berisi salah satu. Kembali ke Android = langkah di atas |
| Tidak bisa masuk fastboot | Isi daya ≥ 30 menit, lalu Power + Volume Down. EDL/9008 butuh akun resmi Xiaomi: service center |

## Data yang tidak pernah disimpan

Nomor seri hanya disimpan sebagai SHA-256. *Platform seed* (`UNIXNU_UNIQUE_CHIP_ID`) ada di `.cache\platform-seed` (di-ignore Git). Kunci owner RSA untuk root terverifikasi (lihat STATUS.md) disimpan di `.cache\owner-key\` dan tidak pernah masuk Git atau CI.
