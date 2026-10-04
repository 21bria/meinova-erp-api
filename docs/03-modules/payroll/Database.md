# Payroll — Database

Tujuh tabel berprefiks `payroll_`. Konvensi umum di [Naming Convention](../../06-database/Naming-Convention.md).

---

## Tabel

| Tabel | Model |
|---|---|
| `payroll_group` | `PayrollGroup` |
| `payroll_salary_grade` | `SalaryGrade` |
| `payroll_salary_level` | `SalaryLevel` |
| `payroll_allowance_template` | `AllowanceTemplate` |
| `payroll_deduction_template` | `DeductionTemplate` |
| `payroll_overtime_group` | `OvertimeGroup` |
| `payroll_tax_status` | `TaxStatus` |

3 migrasi.

---

## Constraint

Kode unik di payroll **sudah dikonversi** dari `unique=True` polos jadi `UniqueConstraint` + `condition=Q(is_deleted=False)`.

Tanpa itu, kode grup payroll yang dihapus akan terkunci selamanya — dan tidak ada pesan yang menjelaskan kenapa kode yang "tidak ada di layar" ditolak sebagai duplikat.

---

## `PayrollAssignment` ada di app `hr`

`apps/hr/models/payroll.py`, tabel `hr_employee_payroll_assignment`.

**Effective-dated:**

```python
is_current = models.BooleanField(...)
effective_from = models.DateField(...)
effective_to = models.DateField(null=True, blank=True)
```

Banyak baris per pegawai. Kenaikan gaji lewat `EmployeeAction` **menutup baris lama** (`effective_to`) dan membuat baris baru — kolom non-gaji (BPJS, metode bayar) **disalin**.

Ia mewajibkan payroll group + currency + tanggal berlaku, jadi baris import yang kolom payroll-nya diisi eksplisit tapi tanpa `payroll_group` **ditolak**.

!!! note "Kenapa effective-dated, bukan ditimpa"
    Payroll bulan lalu harus memakai gaji yang berlaku bulan lalu. Kalau ditimpa, perhitungan ulang periode lampau menghasilkan angka yang berbeda dari slip yang sudah dibagikan.

    Pola yang sama dengan `RotationPeriod` berversi dan `EmployeeAction`.

---

## `TaxStatus` — PTKP

`TK/0`, `K/1`, `K/3`, dst.

!!! danger "Jangan tertukar dengan `administration.MaritalStatus`"
    Yang itu isinya S/M/D/W. Importer sudah menangani pengalihannya otomatis — lihat [Overview](Overview.md#ptkp-bukan-marital-status).

---

## Yang belum ada

Tidak ada tabel payroll run, komponen gaji per periode, atau slip. Lihat [Overview](Overview.md#yang-belum-ada).
