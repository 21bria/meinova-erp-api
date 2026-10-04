# Policy Resolution

**Status: IMPLEMENTED**

Hampir semua aturan HR di sistem ini berbentuk **master data berjenjang**: satu aturan umum untuk semua, ditimpa aturan yang lebih khusus. Halaman ini menjelaskan cara sistem memilih aturan mana yang berlaku.

---

## Satu pola, dipakai berulang

Aturan kehadiran, aturan cuti, aturan roster, dan definisi alur persetujuan semuanya memakai pola yang sama:

!!! abstract "Kolom yang dikosongkan berarti BERLAKU UNTUK SEMUA"
    Bukan "tidak berlaku". Ini jebakan yang paling sering terjadi saat mengisi master berjenjang: admin mengosongkan kolom Company karena mengira aturannya jadi tidak aktif, padahal justru jadi berlaku untuk seluruh perusahaan.

Ketika beberapa aturan sama-sama cocok, yang menang adalah yang **paling khusus** — dihitung dengan skor, bukan dengan urutan baris di database. Urutan baris berubah sendiri saat data disunting; skor tidak.

---

## Aturan Kehadiran

Kekhususan dihitung begini:

```
skor = 4 × (Company diisi)
     + 2 × (Work Location diisi)
     + 1 × (Employee Group diisi)
```

Skor tertinggi menang.

!!! example "Contoh dari dataset peragaan"
    | Aturan | Company | Lokasi | Golongan | Skor |
    |---|---|---|---|---|
    | Standard Attendance | — | — | — | **0** |
    | Kantor Pusat — Jakarta | MMR | Jakarta HO | — | **6** |
    | Site — Sagea Mine | MMR | Sagea Mine | — | **6** |

    Seorang staf di Jakarta cocok dengan dua aturan (yang umum dan yang kantor pusat). Skor 6 menang, jadi toleransinya 15 menit.

    Seorang pegawai perusahaan lain di tenant yang sama tidak cocok dengan keduanya, jadi jatuh ke aturan umum berskor 0.

!!! failure "Tidak ada override tingkat pegawai"
    Sistem ini **tidak punya** pengecualian per orang untuk aturan kehadiran. Yang tersedia hanya tiga tingkat di atas. Dokumentasi yang menyebut urutan "Employee Override → Employee Group → Site → Company" keliru: tidak ada tingkat pegawai, dan Company **mengalahkan** Lokasi, bukan sebaliknya.

---

## Yang diatur Aturan Kehadiran

| Pengaturan | Artinya |
|---|---|
| Toleransi keterlambatan | datang dalam batas ini masih dihitung tepat waktu |
| Keterlambatan dihitung dari mana | dari batas toleransi, atau dari jam jadwal |
| Toleransi pulang cepat | sama, untuk kepulangan |
| Ambang "dianggap ambil cuti" | terlambat lebih dari sekian menit berubah jadi potongan cuti |
| Berapa hari cuti yang dipotong | biasanya setengah hari |
| Jenis cuti yang dipotong | wajib diisi begitu ambang di atas dinyalakan |
| Perlu ditinjau atasan? | atau langsung HR |
| Siapa diberi tahu | pegawainya, atasannya, HR |
| Ambang lembur | lewat jadwal minimal sekian menit baru dihitung lembur |
| Pembulatan lembur | ke bawah |
| Potongan istirahat | untuk menghitung jam kerja bersih |

Yang **tidak** ada di sini: jam masuk dan jam pulang itu sendiri. Itu milik shift. Menyalinnya ke dua tempat berarti cepat atau lambat yang satu berubah dan yang lain tidak.

---

## Batas yang harus diketahui

!!! danger "KNOWN LIMITATION — aturan tidak punya tanggal berlaku"
    Aturan Kehadiran, Aturan Cuti, dan Roster Policy **tidak menyimpan tanggal mulai berlaku**. Yang tersimpan hanya nilai yang berlaku sekarang.

    Akibatnya nyata dan harus dipahami sebelum mengubah angka:

    > **Menghitung ulang presensi akan menerapkan aturan yang berlaku sekarang ke seluruh rentang tanggal yang dipilih — termasuk bulan yang sudah lewat.**

    Tidak ada cara menyatakan "toleransi 15 menit berlaku sejak 1 September". Kalau angkanya diubah lalu presensi dihitung ulang untuk dua bulan ke belakang, dua bulan itu memakai angka yang baru.

    **Yang tidak pernah berubah adalah jam tap.** Jam masuk dan jam pulang yang tersimpan adalah fakta dan tidak disentuh perhitungan ulang. Yang berubah hanya status dan menit-menit turunannya.

!!! example "Bukti dari perubahan yang benar-benar dijalankan"
    Toleransi kantor pusat dinaikkan dari 1 menit ke 15 menit, lalu presensi dua bulan dihitung ulang:

    | | Hasil |
    |---|---|
    | Baris diperiksa | 600 |
    | Baris berubah | **60** |
    | Kolom yang berubah | hanya menit keterlambatan |
    | Status berubah | 8 baris, dari *Terlambat* menjadi *Hadir* |
    | Total menit keterlambatan | 8.948 → 8.133 |
    | **Jam masuk / jam pulang** | **tidak satu pun berubah** — dibuktikan dengan membandingkan seluruh 600 baris sebelum dan sesudah |
