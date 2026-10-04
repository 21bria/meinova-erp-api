# Partitioning

**Belum ada, dan kemungkinan besar belum diperlukan.**

Halaman ini menjelaskan kenapa — dan apa yang sudah menggantikannya.

---

## Schema-per-tenant sudah jadi partisi

django-tenants memberi satu schema per tenant. Efek praktisnya sudah menyerupai partisi:

| | Efeknya |
|---|---|
| Data tenant terpisah secara fisik | query satu tenant tidak menyentuh data tenant lain |
| Index terpisah per schema | ukuran index mengikuti data satu tenant, bukan agregat |
| Restore selektif | satu tenant bisa dipulihkan tanpa mengganggu yang lain |
| `VACUUM` per tabel per schema | tabel besar satu tenant tidak memblokir yang lain |

Jadi tabel `hr_employee_attendance` yang secara logis "besar" sebenarnya adalah **N tabel terpisah**, masing-masing sebesar satu tenant.

**Itu yang membuat partisi tabel jarang diperlukan di sini.**

---

## Kapan partisi mulai masuk akal

Kalau **satu tenant** punya tabel yang benar-benar besar. Kandidat, berurutan:

| Tabel | Kenapa tumbuh | Perkiraan |
|---|---|---|
| `hr_employee_attendance` | 1 baris × pegawai × hari | 500 pegawai × 365 = 180 ribu/tahun |
| `master_audit_trail` | 1 baris per perubahan berpengguna | tergantung intensitas pemakaian |
| `hr_attendance_log` | tap mentah dari mesin fingerprint | lebih besar dari `employee_attendance` |
| `uploads_uploaded_file` | metadata; **byte-nya di disk**, bukan DB | |

Angka pertama menunjukkan skalanya: 180 ribu baris/tahun **belum** butuh partisi. PostgreSQL menangani jutaan baris dengan index yang benar tanpa keluhan.

Ambang yang masuk akal untuk mulai memikirkannya: **puluhan juta baris dalam satu schema**, atau query rentang tanggal yang sudah lambat walau index-nya benar.

---

## Kalau nanti diperlukan

Partisi **range per tanggal** untuk tabel deret waktu:

```sql
CREATE TABLE hr_employee_attendance (...) PARTITION BY RANGE (work_date);
CREATE TABLE hr_employee_attendance_2026 PARTITION OF hr_employee_attendance
    FOR VALUES FROM ('2026-01-01') TO ('2027-01-01');
```

Tiga hal yang harus dipikirkan **sebelum** memulai:

1. **Django tidak mendukung partisi secara native.** Perlu `RunSQL` di migrasi, dan `makemigrations` tidak akan mengenalinya.
2. **× jumlah schema.** Partisi harus dibuat di **setiap** tenant, dan partisi tahun berikutnya harus dibuat sebelum tahun itu tiba — kalau lupa, insert gagal. Itu task terjadwal baru yang harus dijaga.
3. **Kunci partisi harus ikut di setiap query** supaya partition pruning bekerja. Untuk `attendance` itu `work_date`, dan sebagian besar query memang menyaring per bulan — tapi periksa dulu, jangan asumsikan.

---

## Yang lebih murah dan biasanya cukup

Sebelum partisi, tiga hal ini hampir selalu memberi hasil lebih besar dengan risiko jauh lebih kecil:

### 1 · Perbaiki N+1

Endpoint list yang lambat di sistem ini **hampir selalu** karena relasi yang belum di-prefetch, bukan karena ukuran tabel. Lihat [Performance](Performance.md#1-n1-query--penyebab-nomor-satu).

### 2 · Index yang benar

Terutama gabungan `(kolom_penyaring, is_deleted)` dan partial index terkondisi `is_deleted=False`. Lihat [Indexing](Indexing.md).

### 3 · Arsip, bukan partisi

Untuk data yang sudah tidak dipakai operasional:

- `AuditTrail` lebih dari 2 tahun → tabel arsip atau dump ke object storage
- `hr_attendance_log` mentah setelah diproses jadi `EmployeeAttendance`

!!! warning "Jangan arsipkan sembarangan"
    Sistem ini **sengaja menyimpan riwayat, bukan menimpanya** — `EmployeeAction`, `PayrollAssignment` effective-dated, `RotationPeriod` berversi. Semuanya masih dibaca untuk menjawab "sejak kapan" dan "dari mana ke mana".

    Yang boleh diarsipkan hanya data yang benar-benar tidak lagi dirujuk. Dan riwayat kepegawaian punya kewajiban retensi tersendiri di luar pertimbangan teknis.

### 4 · Pindahkan tenant besar ke instance sendiri

Model deployment sudah mendukungnya: **dedicated/on-premise dari codebase yang sama.**

Untuk satu tenant yang jauh lebih besar dari yang lain, ini sering lebih murah daripada merekayasa partisi yang harus dijaga di semua schema.

---

## Ringkasnya

Partisi adalah **langkah keempat**, bukan pertama. Urutannya:

1. Ukur
2. Perbaiki N+1
3. Index yang benar
4. Arsip / pindahkan tenant besar
5. **Baru** partisi

Dan langkah pertama belum dilakukan sama sekali — lihat [Monitoring](../07-deployment/Monitoring.md).
