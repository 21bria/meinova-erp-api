# Payroll — API

Prefix `/api/payroll/`. Aturan umum di [Standar API](../../05-api/Standards.md).

---

## Endpoint

Tujuh master, semuanya `BaseMasterViewSet` — dapat `ui-schema/`, `export/`, `bulk-delete/` gratis.

| Endpoint | `framework_module` |
|---|---|
| `/api/payroll/payroll-groups/` | `payroll/payroll-groups` |
| `/api/payroll/salary-grades/` | `payroll/salary-grades` |
| `/api/payroll/salary-levels/` | `payroll/salary-levels` |
| `/api/payroll/allowance-templates/` | `payroll/allowance-templates` |
| `/api/payroll/deduction-templates/` | `payroll/deduction-templates` |
| `/api/payroll/overtime-groups/` | `payroll/overtime-groups` |
| `/api/payroll/tax-statuses/` | `payroll/tax-statuses` |

Semuanya punya halaman FE.

---

## Penempatan gaji: di bawah `/api/hr/`

```
/api/hr/payroll-assignments/
```

`PayrollAssignment` tinggal di app `hr`, bukan `payroll` — ia sub-data pegawai, dan tab Payroll di kartu pegawai membacanya dari sana.

!!! warning "Endpoint ini termasuk yang disaring `EmployeeDataPolicy`"
    `EDP-PAYROLL` bawaan: yang bersangkutan, atasan langsung, HR-MANAGER.

    Disaring di `filter_queryset()` lewat `EmployeeDataSubjectMixin`, bukan `get_queryset()`.

!!! note "`PayrollAssignmentViewSet` belum punya `data_scope` sendiri"
    Jadi cakupan barisnya datang dari `EmployeeDataPolicy` saja, bukan dari `RoleDataPermission`.

---

## Yang belum ada

Tidak ada endpoint payroll run, slip gaji, atau perhitungan — modelnya belum ada.

Lihat [Overview](Overview.md#yang-belum-ada).
