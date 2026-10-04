# Modul Payroll

🟡 **Sebagian.** Master lengkap dan diseed, **belum ada model payroll run** — jadi belum ada penggajian yang benar-benar dijalankan.

---

## Yang sudah ada: tujuh master

Semuanya CRUD lengkap dengan halaman FE.

| Model | Tabel | `framework_module` |
|---|---|---|
| `PayrollGroup` | `payroll_group` | `payroll/payroll-groups` |
| `SalaryGrade` | `payroll_salary_grade` | `payroll/salary-grades` |
| `SalaryLevel` | `payroll_salary_level` | `payroll/salary-levels` |
| `AllowanceTemplate` | `payroll_allowance_template` | `payroll/allowance-templates` |
| `DeductionTemplate` | `payroll_deduction_template` | `payroll/deduction-templates` |
| `OvertimeGroup` | `payroll_overtime_group` | `payroll/overtime-groups` |
| `TaxStatus` | `payroll_tax_status` | `payroll/tax-statuses` |

```bash
tenant_command seed_payroll
```

---

## Penempatan gaji ada di HR, bukan di sini

`PayrollAssignment` (`apps/hr/models/payroll.py`) — **effective-dated**:

- `is_current` + `effective_from` / `effective_to`
- Banyak baris per pegawai
- Kenaikan gaji lewat `EmployeeAction` **menutup baris lama dan membuat baris baru**, bukan menimpa
- Kolom non-gaji (BPJS, metode bayar) **disalin** — kenaikan gaji tidak boleh diam-diam mengosongkannya

Ia mewajibkan payroll group + currency + tanggal berlaku.

---

## PTKP bukan Marital Status

Jebakan yang sudah ditangani otomatis, dan layak diketahui sebelum menyentuh importer.

`TK/0`, `K/1`, dst. adalah **`payroll.TaxStatus`**. `administration.MaritalStatus` isinya S/M/D/W.

Karena file klien lazim menaruh PTKP di kolom bernama "marital status", `EmployeeReferenceResolver.prepare_values()` **mengalihkannya**: nilai yang gagal dicocokkan sebagai Marital Status tapi **ada** di master Tax Status dipindah ke `tax_status`, lalu status kawinnya diturunkan dari awalan kode (TK → Single, K → Married).

Nilai yang tidak ketemu di kedua master tetap error seperti biasa.

!!! warning "PTKP hasil pengalihan otomatis tidak mewajibkan payroll group"
    Ditandai `_tax_status_auto`. Konsekuensinya: **tax status-nya tidak tersimpan** kalau grup payroll tidak ada.

    Isi `defaults.payroll_group` di ImportProfile kalau PTKP-nya memang mau ikut masuk.

Profile `EMPLOYEE-CSV-US-PTKP` memakai satu kolom file untuk dua target: nilai asli ke `tax_status`, hasil `value_mapping` ke `marital_status`.

---

## Bug currency yang menyentuh payroll

!!! bug "Tidak ada tenant yang punya mata uang dasar, sejak seed pertama"
    `apps/administration/seeds/currency.py` menulis kunci `is_base`, sementara kolomnya `is_base_currency`. `seed_reference` **membuang kunci yang bukan field model tanpa error**.

    Gagalnya jauh dari sumbernya: **import payroll** menjatuhkan currency kosong ke `Currency.is_base_currency`, tidak ketemu, dan baris penempatan gajinya **ditolak**.

    Sudah dibetulkan. Tenant lama wajib `seed_administration --only=currency`.

---

## Yang belum ada

| | Catatan |
|---|---|
| **Model payroll run** | inti modul ini — belum ada |
| Komponen gaji per periode | |
| Slip gaji | |
| Perhitungan PPh 21 | `TaxStatus` sudah ada sebagai master |
| BPJS | kolomnya ada di `PayrollAssignment`, perhitungannya belum |
| Approval payroll | engine sudah ada dan generik |
| Integrasi absensi → payroll | `EmployeeAttendance` dan `EmployeeOvertime` sudah terisi |

Karena belum ada model payroll run, widget **"Monthly Payroll"** dan **"Total Payroll"** di dashboard **sengaja tidak dibuat** — bukan diisi nol.

---

## Kalau nanti dibangun

1. **Payroll run adalah dokumen berapproval** — ikuti [checklistnya](../../02-Framework/Build-A-Module.md#kalau-modulnya-dokumen-berapproval). Engine-nya generik, tidak perlu ditulis ulang.
2. **Slip gaji sangat sensitif** — masuk `EmployeeDataPolicy`, dan wajib ditutup di **tiga jalur**: serializer, endpoint sub-resource, dan export CSV. Menutup satu tidak menutup dua lainnya.
3. **Baca dari `PayrollAssignment` yang `is_current` pada tanggal periode**, bukan yang terbaru — payroll bulan lalu harus memakai gaji yang berlaku bulan lalu.
4. **Jangan seed angka tarif karangan.** Pelajaran dari `SICK-STD`: angka tanpa dasar di master lebih berbahaya daripada tidak ada angka.
