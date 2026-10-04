# Payroll — Yang Belum Ada

Modul ini 🟡 **sebagian**: tujuh master lengkap dan diseed, **inti modulnya belum ada**.

---

## Yang paling menentukan: model payroll run

Tanpanya tidak ada penggajian yang benar-benar dijalankan — yang ada baru masternya.

Konsekuensi yang sudah terlihat: tiga widget dashboard **sengaja tidak dibuat**, dan satu-satunya jalur payroll yang benar-benar dipakai hari ini adalah **`PayrollAssignment`** (penempatan gaji per pegawai, effective-dated).

---

## Daftar

| | Catatan |
|---|---|
| **Model payroll run** | periode, status, daftar pegawai, angka yang dibekukan |
| **Komponen gaji per periode** | `AllowanceTemplate`/`DeductionTemplate` sudah ada sebagai master |
| **Slip gaji** | + cetak PDF |
| **Perhitungan PPh 21** | `TaxStatus` (PTKP) sudah ada dan sudah terisi dari importer |
| **BPJS** | kolomnya ada di `PayrollAssignment`, perhitungannya belum |
| **Approval payroll run** | engine sudah generik — lihat [Workflow](Workflow.md) |
| **Integrasi absensi → payroll** | `EmployeeAttendance` dan `EmployeeOvertime` sudah terisi |
| **Dashboard payroll** | lihat [Dashboard](Dashboard.md) |
| **Export bank** | format transfer per bank |

---

## Yang sudah siap dipakai saat membangunnya

Beberapa hal tidak perlu dibuat lagi:

| Sudah ada | Untuk |
|---|---|
| Engine approval generik | payroll run sebagai dokumen |
| `NumberingSequence` | nomor dokumen payroll run |
| `EmployeeDataPolicy` | kerahasiaan slip gaji |
| Celery + Beat aktif | perhitungan yang lama, penjadwalan periode |
| Import generik | import komponen gaji dari file |
| `PayrollAssignment` effective-dated | sumber angka gaji per tanggal |

---

## Empat aturan yang sudah jelas

Diambil dari pola yang berlaku di modul lain — supaya tidak diputuskan ulang nanti.

1. **Baca `PayrollAssignment` yang `is_current` pada tanggal periode**, bukan yang terbaru. Payroll bulan lalu harus memakai gaji yang berlaku bulan lalu.
2. **Bekukan angkanya di baris run** begitu disetujui. Menghitung ulang tiap dibuka berarti slip yang sudah dibagikan bisa berubah.
3. **Slip gaji masuk `EmployeeDataPolicy`**, ditutup di **tiga jalur** — serializer, endpoint sub-resource, export CSV.
4. **Jangan seed angka tarif karangan.** Pelajaran dari `SICK-STD` yang diseed 30 hari tanpa dasar hukum: angka karangan di master lebih berbahaya daripada tidak ada angka, karena orang menganggapnya sudah divalidasi.

---

## Utang yang sudah diketahui

- `PayrollAssignmentViewSet` **belum punya `data_scope` sendiri** — cakupan barisnya datang dari `EmployeeDataPolicy` saja
- Tenant lama wajib `seed_administration --only=currency` (bug `is_base` vs `is_base_currency` — lihat [Overview](Overview.md#bug-currency-yang-menyentuh-payroll))
