# Permission Management — Izin Kehadiran

Izin Kehadiran menjawab pertanyaan yang tidak bisa dijawab cuti: **"boleh datang jam berapa hari ini"**, bukan "berapa sisa hak saya tahun ini".

---

## Business purpose

| Pertanyaan | Jawaban |
|---|---|
| **Apa yang dilakukan modul ini?** | Memberi konteks resmi atas pengecualian presensi — terlambat, pulang lebih awal, keluar sementara, atau tidak masuk sehari — **tanpa memotong saldo cuti**. |
| **Siapa yang memakainya?** | Pegawai (mengajukan), atasan langsung (menyetujui), HR (memverifikasi). |
| **Apa yang harus dikonfigurasi lebih dulu?** | Alur persetujuan, garis pelaporan, dan aturan perlakuan payroll. |
| **Apa yang butuh persetujuan?** | Setiap izin. Yang belum disetujui **tidak memaafkan apa pun**. |
| **Data apa yang mengalir ke modul berikutnya?** | Menit yang dimaafkan, menit izin keluar sementara, dan penanda ketidakhadiran berizin. |

**Kenapa bukan jenis cuti baru.** Cuti punya saldo, hak bertahun, saldo pembuka, dan tanggal mulai berlaku. Izin tidak punya satu pun dari semuanya. Menumpangkannya ke jenis cuti berarti setiap perhitungan saldo harus mengecualikannya dengan syarat khusus, dan kartu cuti terisi baris yang angkanya tidak pernah berarti apa-apa.

---

## Business flow

```mermaid
flowchart LR
    EX["Attendance Exception<br/>telat · pulang cepat · alpa"] --> REQ["Permission Request"]
    REQ --> SPV["Supervisor Approval"]
    SPV --> HR["HR Verification"]
    HR --> CLS["Attendance Classification<br/>menit yang dimaafkan"]
    CLS --> PF["Payroll Facts"]

    style EX fill:#7c2d12,color:#fff
    style CLS fill:#166534,color:#fff
    style PF fill:#92400e,color:#fff
```

---

## Permission Types

Empat bentuk, dan yang membedakannya **jam mana yang dipakai** — bukan sekadar labelnya.

| Tipe | Yang diisi | Artinya |
|---|---|---|
| **Terlambat Datang** | jam batas | boleh datang paling lambat jam sekian |
| **Pulang Lebih Awal** | jam mulai | boleh pulang mulai jam sekian |
| **Keluar Sementara** | jam keluar & kembali | jendela di tengah jam kerja |
| **Izin Sehari** | — | yang diizinkan seluruh harinya |

Izin harus jatuh **di dalam jendela shift** pegawainya. Izin 18:00–20:00 untuk orang bershift 08:00–17:00 ditolak: hampir selalu salah ketik tanggal, dan menerimanya diam-diam menghasilkan dokumen yang tidak memaafkan apa pun lalu jadi keluhan sebulan kemudian.

Shift malam lolos apa adanya — jendelanya sudah tahu bahwa 23:00–07:00 berakhir di tanggal berikutnya.

---

## Employee Request

Pegawai mengajukan sendiri lewat Self Service: tanggal, tipe, jam, dan alasan. Alasan wajib.

Tanggal yang periode payroll-nya **sudah dikunci** ditolak, dengan pesan yang menyebutkan jalan keluarnya. Yang tidak boleh berubah adalah tanggal yang angkanya sudah dipakai membayar orang.

---

## Supervisor Approval & HR Verification

Dua meja, satu alur, berlaku untuk seluruh lokasi:

| Meja | Siapa |
|---|---|
| 1 | **atasan langsung**, dari garis pelaporan |
| 2 | **HR Admin**, pada lokasi pegawainya |

Status yang mungkin: Draf → Diajukan → Ditinjau → **Disetujui** / Ditolak / Dibatalkan.

!!! warning "Hanya yang disetujui memaafkan"
    Pengajuan yang masih berjalan **tidak** memaafkan apa pun. Kalau ia ikut dibaca, setiap orang bisa membebaskan keterlambatannya sendiri dengan mengetik dokumen yang tidak pernah disetujui siapa pun.

    Yang masih berjalan tetap terlihat di layar presensi sebagai **menunggu izin** — penjelasan kenapa baris yang tampak melanggar sedang menunggu keputusan, bukan pembebasan.

---

## Late Permission

Yang dimaafkan adalah keterlambatan **sampai batas yang diizinkan**. Datang lebih lambat dari batas itu meninggalkan sisa yang tetap tanpa izin.

### Terbukti

| Izin sampai | Datang | Telat menurut mesin | Dimaafkan | Tanpa izin | Keadaan |
|---|---|---:|---:|---:|---|
| 10:20 | 10:18 | **3** | **3** | 0 | **Ada izin** |
| 12:00 | 12:46 | **151** | **105** | **46** | **Sebagian ada izin** |

Baris kedua adalah contoh yang paling berguna untuk manajemen: izin diberikan sampai pukul 12:00, orangnya datang 12:46, dan 46 menit selisihnya **tetap tercatat tanpa izin** di sebelah angka yang dimaafkan.

---

## Early Leave Permission

Cara kerjanya cerminan dari yang di atas: pulang **sesudah** jam yang diizinkan memaafkan seluruhnya; pulang lebih awal dari jam itu menyisakan selisihnya.

Pulang cepat **bukan sebuah status** — ia menit pada baris yang statusnya tetap *Hadir* atau *Terlambat*.

---

## Temporary Out

Menit yang benar-benar jatuh **di dalam jam kerja**. Izin 16:00–18:00 untuk shift yang selesai 17:00 adalah satu jam ketidakhadiran, bukan dua.

Dicatat di kolomnya sendiri — bukan sebagai keterlambatan, bukan sebagai pulang cepat. Payroll memperlakukannya berbeda: yang satu potongan yang dimaafkan, yang satu jam kerja yang memang tidak dijalani.

**Izin keluar sementara tidak memaafkan pulang cepat pada hari yang sama.** Keduanya pengecualian yang berbeda dan masing-masing butuh dokumennya sendiri.

---

## Full Day Permission

Tidak masuk sehari **dengan izin**, tanpa dokumen cuti dan tanpa memotong saldo.

Baris presensinya tetap *Tidak Hadir* — dan itu benar: orangnya memang tidak hadir. Yang ditambahkan penanda **ketidakhadiran berizin**, yang membedakannya dari mangkir.

---

## Attendance Classification

Izin **tidak pernah menyentuh jam tap**. Ini bukan detail teknis; ini yang membuat catatan presensi tetap bisa dipercaya.

| Yang **tidak** berubah | Yang berubah |
|---|---|
| Jam masuk | Menit yang dimaafkan |
| Jam pulang | Menit izin keluar sementara |
| Menit terlambat menurut mesin | Penanda ketidakhadiran berizin |
| Menit pulang cepat menurut mesin | Keadaan izin |
| Status baris | — |

Keadaan izin yang muncul di layar:

| Keadaan | Artinya |
|---|---|
| **Ada izin** | seluruh pengecualiannya tertutup |
| **Sebagian ada izin** | sebagian tertutup, sisanya tidak |
| **Menunggu izin** | ada pengajuan yang belum diputuskan |
| **Tanpa izin** | ada pengecualian, tidak ada dokumen yang menjelaskannya |

"Terlambat dua jam karena izin" dan "terlambat dua jam tanpa izin" tetap dua baris yang **angkanya sama** dan **perlakuannya berbeda** — dan payroll bisa membedakannya tanpa membuka dokumen izinnya satu per satu.

---

## Payroll Treatment

Perlakuan payroll adalah **konfigurasi**, bukan aturan yang ditanam di kode. Tiga pilihan:

| Perlakuan | Artinya |
|---|---|
| **Dibayar** | menitnya tidak memotong gaji |
| **Tidak dibayar** | menitnya memotong |
| **Informasi saja** | tercatat, payroll tidak menyentuhnya |

Aturan dicari berjenjang: kebijakan payroll pegawai → perusahaannya → aturan global. Tidak ada yang cocok berarti **informasi saja** — bukan pilihan yang diambil siapa pun, melainkan penjaga supaya payroll yang sudah berjalan tidak bergeser angkanya hanya karena modul izin lahir.

### Konfigurasi di tenant peragaan

| Tipe izin | Perlakuan | Ambang | Sah menurut validasi |
|---|---|---:|---|
| Terlambat Datang | **Dibayar** | — | ya |
| Pulang Lebih Awal | **Dibayar** | — | ya |
| **Keluar Sementara** | **Tidak dibayar** | 60 menit | **tidak — lihat di bawah** |
| Izin Sehari | **Informasi saja** | — | ya |

!!! danger "KONFIGURASI TIDAK SAH — lolos karena masternya belum punya jalur tulis tervalidasi"
    Kolom ambang terbaca seperti "batas sebelum potongan mulai". Itu memang artinya, tapi **hanya pada perlakuan Dibayar**: di sanalah ia dibaca, dan yang dipotong hanya kelebihannya. Pada perlakuan **Tidak dibayar** seluruh durasinya memang sudah tidak dibayar, jadi ambangnya tidak punya apa pun untuk dikerjakan.

    Terukur, dengan ambang 60 menit:

    | Perlakuan | Izin 30′ | Izin 60′ | Izin 90′ |
    |---|---|---|---|
    | **Dibayar** | 30 dibayar / 0 dipotong | 60 / 0 | **60 / 30** |
    | **Tidak dibayar** | 0 / 30 | 0 / 60 | **0 / 90** |
    | Informasi saja | 0 / 0 | 0 / 0 | 0 / 0 |

    Maksud kebijakan "satu jam pertama ditoleransi, kelebihannya dipotong" karena itu ditulis sebagai **Dibayar + ambang 60**, bukan *Tidak dibayar + ambang 60*.

    **Sistem sendiri menolak pasangan yang kedua.** Aturan yang perlakuannya *Tidak dibayar* sekaligus berambang **gagal validasi**, dengan pesan yang menyebutkan jalan keluarnya: pilih *Dibayar* kalau yang dimaksud "dibayar sampai sekian menit".

    Baris peragaan untuk Keluar Sementara tetap tersimpan begitu karena master ini **belum punya layar, endpoint, maupun service** — satu-satunya cara mengisinya hari ini menulis langsung ke basis data, dan jalan itu tidak memanggil pemeriksaannya. Jadi yang tersimpan bukan kebijakan yang dipilih perusahaan, melainkan **baris yang seharusnya ditolak**.

    Akibatnya yang terukur: izin keluar sementara 90 menit dipotong **90 menit**. Itu bukan aturan "gratis satu jam" yang berjalan salah — pada baris ini ambangnya memang tidak pernah dibaca.

    Barisnya **dibiarkan apa adanya** supaya jejak fase ini tetap bisa diaudit. Kebijakan yang benar untuk Keluar Sementara diputuskan di fase Payroll.

---

## Examples

Tujuh dokumen di tenant peragaan, semuanya menjelaskan pengecualian yang benar-benar ada:

| Cerita | Tipe | Sebelum | Sesudah |
|---|---|---|---|
| Mengantar anak sekolah | Terlambat | telat 3, tanpa izin | **dimaafkan 3**, ada izin |
| Rapat pagi di kantor klien | Terlambat | telat 151, tanpa izin | **dimaafkan 105, sisa 46 tanpa izin** |
| Kontrol kesehatan **dan** menjemput di bandara | Terlambat + Pulang awal | telat 25, pulang cepat 44 | **keduanya dimaafkan** |
| Serah terima alat molor, **shift malam** | Terlambat | telat 6, tanpa izin | **dimaafkan 6**, ada izin |
| Mengurus dokumen di kelurahan | Keluar sementara | pulang cepat 15 | **izin 90 menit**, pulang cepatnya tetap tanpa izin |
| Mendampingi keluarga berobat | Izin sehari | Tidak Hadir, tanpa izin | **ketidakhadiran berizin** |

Dalam setiap kasus jam masuk, jam pulang, menit terlambat, dan menit pulang cepat **tidak bergerak satu pun**.

Sesudahnya **527 dari 534** baris berpengecualian tetap **tanpa izin**. Itu yang membuat daftar kerja HR punya isi.

---

## Known Limitations

| # | Keterbatasan | Dampaknya |
|---|---|---|
| 1 | **Aturan perlakuan izin belum punya layar, endpoint, maupun service** | Satu-satunya jalur pengisian melewati validasinya, sehingga pasangan perlakuan–ambang yang ditolak sistem tetap bisa tersimpan — dan satu baris seperti itu memang sedang tersimpan |
| 1b | Ambang menit hanya berpasangan dengan *Dibayar* | Lihat kotak di atas — konfigurasi peragaan memakai *Tidak dibayar* + ambang, jadi seluruh durasinya dipotong |
| 2 | Izin keluar sementara tidak memaafkan pulang cepat | Hari yang punya keduanya butuh dua dokumen |
| 3 | Pulang cepat bukan sebuah status | Dikenali lewat menitnya, bukan lewat status baris |
| 4 | Izin sehari pada perlakuan *Informasi saja* tetap terhitung ketidakhadiran di payroll | Hanya perlakuan *Dibayar* yang mengeluarkannya dari potongan |
| 5 | Izin tidak menerbitkan baris presensi | Hari yang barisnya belum ada mendapat klasifikasinya begitu barisnya terbit |
