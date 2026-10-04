# HR — Yang Belum Ada

Daftar terbuka, diurutkan dari yang paling siap dikerjakan. Semuanya diambil dari keadaan kode hari ini, bukan dari wishlist produk.

---

## Siap dikerjakan — infrastrukturnya sudah ada

### 1 · Notifikasi H-7 Travel Request

`request_lead_days` / `notify_lead_days` / `urgent_purposes` sudah tersimpan di `RosterPolicy` dan muncul di layar settingnya, tapi **belum ada satu baris kode pun yang membacanya**.

Penjadwalnya **bukan** penghalang: Celery Beat aktif (`DatabaseScheduler`) dan `hr.dispatch_employee_reminders` sudah jalan tiap jam 6 pagi. Polanya tinggal ditiru — task menyebar per schema sendiri.

### 2 · Rolling horizon roster otomatis

`extend_roster_horizon` sudah jalan sebagai command dan **tidak butuh approval** (ia menempel halaman baru di bawah kalender, bukan mencetak ulang kalendernya). Tinggal satu entri jadwal.

### 3 · Regenerate modul yang schema-nya sudah siap

| Modul | Yang kurang |
|---|---|
| `hr/leave` | `schema.actions` sudah ditulis, tombol Submit/Approve belum muncul |
| `hr/site-rotations` | idem — "Generate Periods", "Regenerate" |
| `hr/employee-data-policies` | belum digenerate sama sekali |

Semuanya cuma perlu `pnpm meinova generate <module>`.

### 4 · Pengingat sertifikat kedaluwarsa

`EmployeeCertificate` punya tanggal berlakunya, dan mesin pengingatnya sudah jalan.

### 5 · Overtime lewat engine approval

`OvertimeStatus` sudah memuat nilai yang sama dengan Leave, tapi **belum disambungkan** ke engine. Checklistnya sudah baku: [Build A Module](../../02-Framework/Build-A-Module.md#kalau-modulnya-dokumen-berapproval).

---

## Butuh keputusan desain dulu

### Cuti tahunan di dalam blok off memotong 0 hari

`LeaveDayCalculator` menghitung hari **kerja yang hilang**, dan pegawai roster yang cuti saat blok off-nya tidak kehilangan hari kerja apa pun.

Konsekuensinya baris "Cuti Tahunan" di dalam blok off **tidak mengurangi saldo** — labelnya tidak berpengaruh apa-apa.

**Belum diputuskan** apakah TR harus memotong sebesar hari kalender barisnya sendiri.

### Carry-over saldo cuti

Kolomnya sudah ada di `LeavePolicy`; yang memindahkan sisa antar tahun belum ada. Perlu diputuskan: kedaluwarsa berapa lama, dibatasi berapa hari, dan apakah bisa diuangkan.

### Dashboard pribadi untuk `EMPLOYEE`

Angka `hr/dashboard` sudah tersaring ke datanya sendiri, jadi bukan kebocoran — tapi "Total Pegawai 1" bukan dashboard yang berguna.

Yang dibutuhkan berbeda: sisa saldo cuti, jadwal roster, dokumen yang sedang diajukan.

### Timezone

`TIME_ZONE` proyek UTC, frontend merender dengan `date.getHours()` (jam browser), jadi **data absensi hasil import tergeser +7 jam di layar**.

Memperbaikinya berarti memutuskan apakah yang bergerak `TIME_ZONE`, importer, atau perendernya — dan ketiganya menyentuh data yang sudah tersimpan.

---

## Modul yang belum ada modelnya

| | Keadaan |
|---|---|
| **Performance** | `models/performance.py` **file kosong**; 9 master sudah diseed tapi tidak dipakai apa pun — lihat [Performance](Performance.md) |
| **Separation** | `models/separation.py` **file kosong**; ditangani sebagai jenis `EmployeeAction`, dan itu mungkin memang cukup |
| **Medical** | hanya sub-data, belum ada modul — lihat [Medical](Medical.md) |

---

## Roster & Travel

- `travel_day_mode = ACTUAL_ITINERARY` — kolomnya tersimpan, **rekonsiliasi rencana ↔ realisasi belum ada**
- Layar pembanding back-to-back
- Eksekusi kedaluwarsa kredit (`credit_expiry_months` tersimpan, belum dibaca)
- **Cetak PDF Travel Request** — approval sudah jalan; yang tersisa merender kotak tanda tangan dari `approval.steps`

---

## Recruitment

Portal kandidat, upload CV (uploads sudah ada, belum disambungkan), penjadwalan wawancara bernotifikasi, pipeline board, onboarding checklist.

---

## Utang teknis yang menyentuh HR

| | Catatan |
|---|---|
| **Lookup di luar Employee belum disaring cakupan data** | `EmployeeViewSet.lookup` sudah; sisanya belum |
| **Test hanya di `apps/hr/tests/`** | app lain `tests.py` kosong; tidak ada test API level HTTP |
| **22 viewset belum menuliskan `endpoint` di schema** | sehingga tidak terdaftar di peta izin FE, dan tombolnya tidak bisa disaring |
| **`entity` tidak dioper generator** | toast berbunyi `Data "X" created`, bukan `Employee "X" created` |

---

## Yang sengaja TIDAK dikerjakan

Supaya tidak diusulkan lagi:

| | Kenapa |
|---|---|
| Memisah form cuti HO vs site | yang berbeda cara menghitungnya, bukan jenis cutinya — dua tabel berarti dua saldo dan pegawai yang pindah jadi kasus khusus permanen |
| Memecah role `EMPLOYEE` jadi site/kantor | tiga lapisan harus diduplikasi, dan pemberian rolenya **gagal diam-diam** saat orangnya pindah. `visibility_rule` membacanya dari penempatan |
| Menghidupkan `EmployeeMovement` | kode mati tanpa migration; riwayat dibaca dari `EmployeeAction` yang `APPLIED` |
| Mengembalikan baris travel ke roster | dua tempat = dua tanggal keberangkatan untuk penerbangan yang sama |
| Menambah pola roster baru tanpa alasan | dropdown pernah berisi enam pola hampir sama dan langsung jadi keluhan pengguna |
| Menolak (bukan memperingatkan) celah antar periode roster | menggeser satu blok selalu melewati keadaan tumpang tindih — menolak membuat jadwal bersambung mustahil disunting |
