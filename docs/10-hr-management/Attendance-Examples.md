# Attendance — Contoh untuk Manajemen

Halaman ini berisi skenario yang **bisa dibuka sendiri** di sistem peragaan. Setiap baris menyebut siapa yang membukanya, di layar mana, apa yang akan terlihat, dan modul mana yang melanjutkannya.

Jendela data: **25 Juli – 25 September 2026.**

---

## Management Examples

### 1. Ambang toleransi yang bisa dilihat berubah

**Persona:** atasan langsung di kantor pusat
**Layar:** Attendance → daftar presensi seorang staf kantor, akhir Juli

Empat hari berturut-turut, kedatangan naik sedikit demi sedikit:

| Tanggal | Datang | Menit terlambat | Status |
|---|---|---:|---|
| 27 Juli | 10:12 | 0 | Present |
| 28 Juli | 10:15 | **0** | Present |
| 29 Juli | 10:16 | **1** | **Late** |
| 30 Juli | 10:18 | 3 | Late |

**Yang dijelaskan:** kebijakan kantor pusat memaafkan 15 menit, dan menit ke-16 adalah menit pertama yang dihitung. Angkanya dipotong toleransi, bukan dihitung dari nol.
**Modul berikutnya:** Izin Kehadiran bisa memaafkan sebagian menit ini — **HR-DEMO-3**.

---

### 2. Kebijakan yang sama, lokasi berbeda

**Persona:** HR Manager
**Layar:** Attendance → filter per lokasi

| | Baris presensi | Terlambat | Persentase |
|---|---:|---:|---:|
| Jakarta Head Office | 362 | 59 | **16,3 %** |
| Sagea Mine | 805 | 251 | **31,2 %** |

**Yang dijelaskan:** perilaku kedatangan di kedua lokasi dibangkitkan dari sebaran yang sama persis. Selisih angkanya murni karena kebijakannya — 15 menit di kantor, nol menit di site.
**Modul berikutnya:** —

---

### 3. Shift malam yang menyeberang tengah malam

**Persona:** pengawas site
**Layar:** Attendance → seorang kru Sagea Mine, 26 Juli

| | |
|---|---|
| Hari kerja | **26 Juli 2026** |
| Shift | Shift 3 — Malam |
| Jadwal | 26 Juli 23:00 → **27 Juli 07:00** |
| Tap masuk | 26 Juli 22:52 |
| Tap pulang | **27 Juli 07:38** |
| Jam kerja bersih | 466 menit |
| Bukti lembur | 38 menit |
| Status | Present |

**Yang dijelaskan:** dua tap di dua tanggal kalender menghasilkan **satu** baris presensi, tertanggal hari kerjanya. Tidak ada kolom di file mesin yang menyebut tanggal kerja — sistem yang menentukannya dari jadwal.
**Modul berikutnya:** 38 menit itu adalah bukti, bukan lembur yang disetujui — **HR-DEMO-3**.

---

### 4. Rotasi tiga shift dan hari pemulihan

**Persona:** HR Admin site
**Layar:** Shift Calendar → seorang kru, Agustus

| Tanggal | Shift |
|---|---|
| 15 – 21 Agustus | Shift 1 — Pagi |
| 22 – 28 Agustus | Shift 3 — Malam |
| **29 Agustus** | **hari pemulihan — tanpa shift** |
| 30 Agustus – 2 September | Shift 2 — Siang |

**Yang dijelaskan:** hari pemulihan tetap berada di dalam blok kerja — bukan hari off, bukan cuti. Ia tidak punya kewajiban presensi, dan penutupan hari **tidak** menandainya mangkir.
**Modul berikutnya:** —

---

### 5. Hari libur yang hanya berlaku di satu lokasi

**Persona:** manajemen
**Layar:** Work Calendar → 4 September 2026, lalu Attendance pada tanggal yang sama

| Siapa | 4 September |
|---|---|
| Pegawai kantor di Jakarta | bekerja |
| **Pegawai kantor yang berkantor di Sagea Mine** | **libur — tidak ada baris presensi** |
| Kru roster di Sagea Mine | **tetap bekerja** |

**Yang dijelaskan:** Safety Stand-Down Sagea Mine berlaku menurut **lokasi**, bukan menurut perusahaan. Ia membebaskan pegawai berkalender di lokasi itu — tapi **tidak** membebaskan kru roster, karena segmen kerja roster tidak dikurangi hari libur.
**Modul berikutnya:** kalau stand-down memang harus menghentikan kru, jalurnya penyesuaian roster atau dokumen cuti — lihat [Known Limitations](Attendance-Closing.md#known-limitations).

---

### 6. Tidak hadir yang lahir dari penutupan hari

**Persona:** HR Admin
**Layar:** Attendance Closing, lalu Attendance

| | Sebelum | Sesudah |
|---|---|---|
| Hari kerja terjadwal | ya | ya |
| Baris presensi | **tidak ada** | ada |
| Status | — | **Absent** |
| Sumber | — | System |

**Yang dijelaskan:** ketidakhadiran tidak pernah dikirim mesin. Ia disimpulkan dari hari terjadwal yang tidak punya catatan, dan baris kesimpulan itu ditandai supaya bisa dibedakan dari catatan sungguhan.
**Modul berikutnya:** 35 baris seperti ini menunggu dokumen Cuti — **HR-DEMO-3**.

---

### 7. Tap pulang yang tidak terekam, lalu dikoreksi

**Persona:** HR Admin kantor pusat
**Layar:** Attendance → buka baris → koreksi

| | Sebelum | Sesudah |
|---|---|---|
| Tap mesin | 1 (hanya masuk) | 1 — **tidak berubah** |
| Jam pulang | kosong | 18:14 |
| Jam kerja bersih | 0 | 440 menit |
| Ditandai koreksi tangan | tidak | **ya** |
| Alasan | — | tertulis |
| Disunting oleh | — | HR Admin |

**Yang dijelaskan:** bukti mentah tidak pernah disunting. Yang bertambah adalah kesimpulan harian beserta nama orang yang bertanggung jawab atasnya.
**Modul berikutnya:** —

---

### 8. Keterlambatan yang menerbitkan kewajiban cuti

**Persona:** atasan langsung
**Layar:** Attendance → baris bertanda kewajiban cuti

| Terlambat | Penanda |
|---:|---|
| 151 menit | **1,00 hari** |

**Yang dijelaskan:** kebijakan kantor pusat menyatakan keterlambatan di atas 120 menit sebaiknya diselesaikan dengan cuti. Yang terbit adalah **penanda** — saldo cuti tidak berkurang dari sini. Atasan bisa menetapkan angka lain atau membebaskan dengan alasan tertulis; angka menurut aturan tetap tersimpan di belakangnya.
**Modul berikutnya:** dokumen Cuti — **HR-DEMO-3**.

---

### 9. Pegawai yang berhenti di tengah periode

**Persona:** HR Manager
**Layar:** Attendance → seorang staf kantor yang berhenti 10 Agustus

| | |
|---|---|
| Hari kerja terjadwal di jendela | **11** |
| Baris presensi | **11** |
| Baris sesudah tanggal berhenti | **0** |

**Yang dijelaskan:** tanggal berhenti adalah pagar. Tidak ada kewajiban presensi sesudahnya, dan penutupan hari tidak menerbitkan satu baris mangkir pun.
**Modul berikutnya:** —

---

### 10. Pegawai yang tidak pernah dijadwalkan

**Persona:** manajemen
**Layar:** Attendance → cari anggota Direksi

| | |
|---|---|
| Hari kerja terjadwal | **0** |
| Baris presensi | **0** |
| Baris Absent | **0** |

**Yang dijelaskan:** Employee Group mereka mematikan Attendance. Mereka **tidak pernah dijadwalkan** — bukan dijadwalkan lalu dimaafkan. Bedanya terlihat di angka: yang kedua akan menerbitkan baris mangkir yang harus dibersihkan tangan setiap bulan.

Karena itu rombongan peragaan berisi **30 pegawai** tetapi hanya **28 peserta presensi**.
**Modul berikutnya:** —

---

## Ringkasan angka yang akan dilihat manajemen

| | |
|---:|---|
| **1.167** | baris presensi di jendela dua bulan |
| **822** | Present |
| **310** | Late |
| **35** | Absent — seluruhnya dari penutupan hari |
| **254** | baris dengan menit pulang cepat |
| **65** | baris terlambat **dan** pulang cepat |
| **272** | baris dengan bukti lembur |
| **7** | baris bertanda kewajiban cuti |
| **283** | baris shift malam yang menyeberangi tengah malam |
| **534** | baris membawa pengecualian yang belum dijelaskan dokumen apa pun |
| **21** | tap mesin mentah tersimpan |
| **0** | baris di hari field break, perjalanan, pemulihan, libur kantor, atau sesudah berhenti |

!!! success "Angkanya konsisten dengan aturannya"
    Menjalankan perhitungan ulang atas seluruh jendela melaporkan **nol baris berubah**. Artinya setiap angka yang tersimpan sepakat dengan Attendance Policy yang berlaku hari ini — tidak ada satu pun yang berasal dari hitungan di luar mesin kebijakan.
