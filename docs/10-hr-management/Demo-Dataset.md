# Demo Dataset — Fondasi, Presensi & Dokumen HR

**Status: CONFIGURED FOR DEMO**

Halaman ini menjelaskan isi tenant peragaan sesudah fondasinya dibangun. Angka-angkanya diambil dari database yang berjalan, bukan dari rencana.

---

## Cakupan

| | |
|---|---|
| Perusahaan utama | Meinova Mineral Resources (MMR) |
| Perusahaan pendamping | Meinova Nusantara (MNI) — hanya direksi |
| Di luar cakupan peragaan | Meinova Logistik Samudra (MLS) — punya lokasi, belum berpegawai |
| Tanggal rujukan | 25 September 2026 |
| Periode | 25 Juli 2026 – 25 September 2026 (63 hari) |

---

## Organisasi

| Lokasi | Perusahaan | Pegawai |
|---|---|---|
| Jakarta Head Office | MMR | 8 |
| Jakarta Head Office | MNI | 2 |
| **Sagea Mine** | MMR | **20** |
| **Total** | | **30** |

Dari 20 pegawai di Sagea Mine, **19 adalah pegawai roster** dan **1 adalah pegawai kantor yang berkantor di site** — jadwalnya tetap dari kalender, bukan dari blok rotasi.

!!! info "30 pegawai, 28 peserta presensi"
    Dua direksi MNI punya Employee Group yang **mematikan Attendance**. Mereka tetap anggota rombongan kanonik — muncul di Employee Master, Org Chart, dan headcount — tapi **tidak pernah dijadwalkan**, jadi tidak punya baris presensi dan tidak pernah tercatat mangkir.

    Bedanya bukan kehalusan istilah: "tidak dijadwalkan" tidak menghasilkan apa-apa, sementara "dijadwalkan lalu dimaafkan" akan menerbitkan baris mangkir yang harus dibersihkan tangan setiap bulan.

---

## Kalender & hari libur

| Kalender | Cakupan | Sabtu–Minggu |
|---|---|---|
| Office Calendar 2026 | global | libur |
| Sagea Mine Operational Calendar 2026 | Sagea Mine | kerja |

| Hari libur di dalam periode | Cakupan |
|---|---|
| 17 Agustus 2026 — Hari Kemerdekaan | seluruh tenant |
| 4 September 2026 — Sagea Mine Safety Stand-Down | **hanya Sagea Mine** |

---

## Shift

| Kode | Jam | Lewat tengah malam | Peran |
|---|---|---|---|
| Office | 10:00 – 18:00 | tidak | shift tetap pegawai kantor |
| Shift 1 — Morning | 07:00 – 15:00 | tidak | putaran 1 blok site |
| **Shift 3 — Night** | **23:00 – 07:00** | **ya** | putaran 2 blok site |
| Shift 2 — Day | 15:00 – 23:00 | tidak | putaran 3 blok site |

Rencana shift per blok kerja yang terbit bersama roster:

| Shift | Baris rencana | Pegawai |
|---|---|---|
| Shift 1 — Morning | 269 | 19 |
| Shift 3 — Night | 268 | 19 |
| Shift 2 — Day | 268 | 19 |
| Hari pemulihan (tanpa shift) | 403 | 19 |
| Penyesuaian atasan | 1 | 1 |

---

## Roster

| | |
|---|---|
| Pegawai roster | **19 dari 19** punya rencana |
| Policy yang dipakai | 42 hari kerja / 14 hari field break, dua shift, kredit aktif |
| Rencana roster | 19 |
| Versi rencana | 20 (19 baseline + 1 dari penyesuaian) |
| Rencana shift | 1.209 baris |
| Segmen jadwal | 520 |
| Cakupan | setiap rencana menutup **seluruh** periode |

Titik awal siklus sengaja berbeda antar pegawai (berjenjang tiga hari), sehingga pada tanggal mana pun sebagian regu sedang bekerja, sebagian sedang field break, dan sebagian sedang dalam perjalanan.

Sebaran keadaan tanggal di dalam periode:

| Keadaan | Jumlah segmen |
|---|---|
| Work | 35 |
| Field Break | 25 |
| Travel Out | 21 |
| Travel In | 21 |

---

## Aturan kehadiran

| Aturan | Berlaku di | Toleransi telat | Ambang lembur |
|---|---|---|---|
| Standard Attendance | semua yang tidak punya aturan sendiri | 1 menit | 30 menit |
| Kantor Pusat — Jakarta | MMR / Jakarta HO | **15 menit** | 30 menit |
| Site — Sagea Mine | MMR / Sagea Mine | 0 menit | 30 menit |

---

## Dua contoh kepegawaian yang disengaja

| Pegawai | Keadaan | Yang diperagakan |
|---|---|---|
| Staf akuntansi kantor pusat | berhenti **10 Agustus 2026** — di tengah periode | pemberhentian di tengah periode: jadwal berhenti pada tanggal itu, gaji diprorata |
| Mekanik site | berhenti **10 Oktober 2026** — sesudah periode | pemberhentian berjadwal: masih bekerja penuh di seluruh periode, rosternya utuh |

---

## Presensi

Seluruh presensi di jendela dibangun ulang dari jadwal yang berlaku. **Setiap baris jatuh pada hari kerja terjadwal** — tidak ada satu pun di hari field break, hari perjalanan, hari pemulihan, hari libur kantor, atau tanggal sesudah seorang pegawai berhenti.

| | |
|---:|---|
| **1.167** | baris presensi |
| **362** | Jakarta Head Office |
| **805** | Sagea Mine |
| **21** | tap mesin mentah tersimpan |

### Asal-usul setiap baris

| Asal | Baris | Yang terlihat di layar |
|---|---:|---|
| Bukti mesin lewat unggah file | **11** | `Import` — tap mentahnya ikut tersimpan |
| Rekap harian deterministik | **1.121** | `Attendance Device` |
| Kesimpulan penutupan hari | **35** | `System` |
| Koreksi tangan | **1** | ditandai koreksi, beralasan tertulis |

### Status dan angka

| | |
|---:|---|
| **822** | Present |
| **310** | Late |
| **35** | Absent — seluruhnya dari penutupan hari |
| **254** | baris dengan menit pulang cepat |
| **65** | baris terlambat **dan** pulang cepat |
| **272** | baris dengan bukti lembur |
| **7** | baris bertanda kewajiban cuti |
| **283** | baris shift malam yang menyeberangi tengah malam |

### Angka telat per lokasi

| | Baris | Terlambat | Persentase |
|---|---:|---:|---:|
| Jakarta Head Office — toleransi 15 menit | 362 | 59 | **16,3 %** |
| Sagea Mine — toleransi 0 menit | 805 | 251 | **31,2 %** |

Sebaran jam kedatangan di kedua lokasi **identik**. Selisih angkanya murni hasil kebijakan yang berbeda.

### Hari yang sengaja tidak menghasilkan baris

| Sebab | Hari |
|---|---:|
| Field break | 289 |
| Travel out | 21 |
| Travel in | 21 |
| Hari pemulihan | 61 |
| Akhir pekan & hari libur pegawai kantor | 205 |
| Sesudah tanggal berhenti | 46 |

Contoh yang bisa dibuka sendiri: [Contoh untuk Manajemen](Attendance-Examples.md).

---

## Dokumen HR

Dua puluh tiga dokumen yang **menjelaskan** pengecualian presensi di atas — bukan yang menghapusnya.

| | Jumlah | Keadaan |
|---|---:|---|
| **Cuti** | **9** | 4 disetujui · 1 ditolak · 1 dibatalkan · 1 diajukan · 1 draf · 1 tercatat |
| **Izin Kehadiran** | **7** | seluruhnya disetujui |
| **Catatan Lembur** | **7** | 6 tercatat · 1 dibatalkan · 1 di antaranya tidak dibayar |

### Konfigurasi yang menyertainya

| | |
|---|---|
| Aturan perlakuan payroll atas izin | **4** aturan global |
| Tingkat lembur site | **2** (0–2 jam ×1,5 · di atas 2 jam ×2,0), disusun **per hari** |
| Pegawai berkelompok lembur | **15** pegawai site yang sudah dinyatakan berhak |

### Dampaknya pada presensi

| | Sebelum | Sesudah |
|---|---:|---:|
| Baris presensi | 1.167 | **1.167** |
| Tidak Hadir | 35 | **34** |
| **Cuti** | 0 | **1** |
| Pengecualian tanpa izin | 534 | **527** |
| Baris "ada izin" | 0 | **4** |
| Baris "sebagian ada izin" | 0 | **2** |
| **Jam tap** | — | **tidak satu pun berubah** |

### Yang sengaja tetap terbuka

| | |
|---:|---|
| **28** | hari tidak hadir tanpa keterangan |
| **527** | pengecualian tanpa izin |
| **266** | baris berbukti lembur tanpa catatan lembur |
| **73** | baris berbukti lembur kantor pusat yang belum punya kelompok lembur |
| 1 | cuti ditolak · 1 dibatalkan · 1 masih menunggu |

---

## Yang belum ada

| | |
|---|---|
| Kunjungan tamu | belum ada — **HR-DEMO-4** |
| Slip gaji | satu run masih berstatus tinjauan, memakai angka presensi sebelum pembangunan ulang — **HR-DEMO-5** |
| Jurnal | belum ada — **HR-DEMO-6** |

---

## Data uji teknis yang sengaja dipisahkan

Tenant ini juga memuat enam pegawai dari lini **uji teknis** yang dipakai membuktikan perhitungan payroll. Mereka **bukan bagian dari peragaan manajemen**: dinonaktifkan, tidak punya presensi, tidak punya roster, tidak punya akun pengguna, dan tidak dipakai dalam satu skenario bisnis pun.

Penjelasannya ada di [Technical Reference](Technical-Reference.md); mereka tidak muncul di halaman bisnis mana pun.
