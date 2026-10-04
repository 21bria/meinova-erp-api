# Payroll — Dashboard

**Belum ada**, dan itu keputusan sadar.

---

## Widget yang tidak dibuat

| Widget | Kenapa |
|---|---|
| "Monthly Payroll" (beranda) | belum ada model payroll run |
| "Total Payroll" (dashboard HR) | idem |
| "Revenue vs Expense" | `finance` masih kerangka kosong |

Ketiganya ada di mockup awal dan **dihapus, bukan diisi nol**.

> **Widget yang datanya belum ada modelnya tidak dibuat, bukan diisi angka contoh.**

Angka karangan di layar demo adalah utang yang dibayar pelanggan: "Monthly Payroll Rp 1.2B" muncul untuk setiap orang yang login, di tenant mana pun, **termasuk saat didemokan ke klien**.

Di dashboard HR, tempatnya diisi **Jam Lembur** dan **Lowongan Terbuka** yang datanya nyata.

---

## Yang sudah bisa dihitung hari ini

Tanpa model payroll run pun, beberapa angka sudah punya sumbernya:

| Angka | Sumber |
|---|---|
| Jumlah pegawai per payroll group | `PayrollAssignment` yang `is_current` |
| Distribusi salary grade/level | idem |
| Pegawai tanpa penempatan payroll | `Employee` tanpa `PayrollAssignment` aktif — ini **temuan yang berguna**, karena mereka tidak akan ikut terhitung saat payroll dijalankan |
| Jam lembur per periode | `EmployeeOvertime` (sudah ada di dashboard HR) |

Baris ketiga layak dibuat lebih dulu: ia jenis pemeriksaan yang sama dengan **Kesehatan Konfigurasi** di dashboard Administration — dan pemeriksaan semacam itu menemukan bug `is_base_currency` di menit pertama.

---

## Kalau nanti dibuat

Ikuti pola dashboard modul yang sudah ada — mekanismenya di [UI/UX → Dashboard](../../04-ui-ux/Dashboard.md), contoh terlengkap di [HR Dashboard](../hr/Dashboard.md).

Yang paling mudah terlewat:

!!! danger "`BaseDashboardAPIView` tidak melewati `filter_queryset()`"
    Tiap queryset **wajib** memanggil `DataScopeService.filter(...)`, dan petanya **disamakan persis** dengan `data_scope` di viewset masing-masing.

    Untuk payroll ada lapis kedua: `EmployeeDataPolicy`. Angka agregat yang tidak menyaringnya akan membocorkan total gaji ke orang yang tidak boleh melihat gaji satu pun pegawai.
