# HR — API

Seluruh endpoint di bawah `/api/hr/`. Aturan umum (envelope, pagination, error) ada di [Standar API](../../05-api/Standards.md).

---

## Urutan pendaftaran rute

`apps/hr/api/urls.py` — **urutannya berarti**:

```python
urlpatterns = [
    path("", include(...employee.urls)),
    ...
    # Rute path-tetap harus di ATAS router viewset supaya tidak
    # tertelan rute `<str:pk>` milik router.
    path("", include(...dashboard.urls)),
    path("reminder-policy/", include(...)),
    path("lookup/", include(...)),
    path("", include(...attendance_sync.urls)),
    ...
    # Router/viewset umum PALING AKHIR
    path("", include(...attendance.urls)),
]
```

!!! danger "Rute baru yang path-tetap wajib ditaruh di atas router"
    Router DRF mendaftarkan `<str:pk>`, yang akan **menelan** `/api/hr/dashboard/` dan menganggap `dashboard` sebagai id.

---

## CRUD

Semuanya mendukung `?page=&page_size=&search=&ordering=` plus `ui-schema/`, `export/`, `bulk-delete/`.

| Resource | Endpoint |
|---|---|
| Employee | `/api/hr/employees/` |
| Sub-data pegawai | `/api/hr/employee-{banks,families,educations,experiences,certificates,documents,medical-events,trainings}/` |
| Payroll assignment | `/api/hr/payroll-assignments/` |
| Attendance | `/api/hr/attendances/` |
| Leave | `/api/hr/leaves/`, `/api/hr/leave-balances/` |
| Overtime | `/api/hr/overtimes/` |
| Employee Action | `/api/hr/employee-actions/` |
| Travel Request | `/api/hr/travel-requests/` (+ purposes, arrangements) |
| Roster Schedule | `/api/hr/site-rotations/` (+ rotation-periods) |
| Roster Setup | `/api/hr/roster-setups/`, `/api/hr/roster-setup-lines/` |
| Roster Adjustment | `/api/hr/roster-adjustments/` |
| Rotation Credit | `/api/hr/rotation-credits/` |
| Training | `/api/hr/training-programs/`, `/api/hr/training-participants/` |
| Recruitment | `/api/hr/job-vacancies/`, `/api/hr/candidates/`, `/api/hr/candidate-interviews/` |

---

## Action per dokumen

### Leave

```
POST /api/hr/leaves/<id>/{submit,withdraw,approve,reject,return}/
```

### Travel Request

```
POST /api/hr/travel-requests/<id>/{submit,approve,reject,withdraw}/
POST /api/hr/travel-requests/<id>/from-rotation-period/
```

### Employee Action

```
POST /api/hr/employee-actions/<id>/{submit,withdraw,approve,reject,apply}/
```

`apply/` untuk mengulang penerapan yang gagal — **kegagalan penerapan tidak membatalkan persetujuan**, ia ditempel ke `apply_error`.

### Roster Setup

```
GET  /api/hr/roster-setups/<id>/candidates/
POST /api/hr/roster-setups/<id>/add-employees/
GET  /api/hr/roster-setups/<id>/preview/
POST /api/hr/roster-setups/<id>/{submit,withdraw,commit}/
```

`commit/` **bisa diulang** — ia melewati baris yang sudah `COMMITTED`.

### Roster Adjustment

```
GET  /api/hr/roster-adjustments/<id>/preview/
POST /api/hr/roster-adjustments/<id>/{submit,withdraw,apply}/
```

### Rotation Credit

```
POST /api/hr/rotation-credits/<id>/reverse/
GET  /api/hr/rotation-credits/balances/
POST /api/hr/rotation-credits/convert-preview/
```

Ledger **append-only**: `update()` dan `soft_delete()` melempar.

### Roster Schedule (jalur lama)

```
POST /api/hr/site-rotations/<id>/generate-periods/
POST /api/hr/site-rotations/<id>/regenerate-periods-force/
POST /api/hr/site-rotations/<id>/extend-periods/      {"cycles": 3} | {"until": "..."}
POST /api/hr/site-rotations/<id>/regenerate-from/     {"from_sequence": 5}
POST /api/hr/site-rotations/<id>/shift-periods/       {"from_sequence": 3, "days": -2}
```

!!! danger "`generate-periods/` membangun ulang SELURUHNYA"
    Untuk dokumen yang sudah berjalan, pakai tiga endpoint terakhir — semuanya bekerja **dari satu titik ke depan**.

---

## Riwayat kepegawaian

```
GET /api/hr/employees/<id>/employment-history/
```

Dirakit dari `EmployeeAction` yang `APPLIED` + satu baris `HIRE` dari `join_date`.

Lewat `get_object()` supaya `RoleDataPermission` berlaku — tanpa itu riwayat kontrak dan gaji seluruh tenant terbaca lewat satu URL yang ditebak.

Isinya disaring `EmployeeDataPolicy`: baris yang tidak boleh dilihat **dibuang dari payload**, bukan ditandai — penanda "3 perubahan disembunyikan" sudah memberi tahu bahwa ada kenaikan gaji.

---

## Dashboard

```
GET /api/hr/dashboard/?mode=&start=&end=
```

Satu request mengembalikan **semua widget**: `{period, widgets: {<key>: ...}}`.

---

## Lookup

```
GET /api/hr/lookup/{training-programs,job-vacancies,candidates,roster-plans,rotation-segments}/
```

Registry di `apps/hr/api/lookup/registry.py`, di-import dari `HrConfig.ready()` — **kalau lupa, endpoint-nya 404**.

!!! danger "`EmployeeViewSet.lookup` merakit querysetnya sendiri"
    Ia **tidak** melewati `filter_queryset()`, jadi `DataScopeService.filter` dipasang eksplisit. Tanpa itu, admin site yang hanya boleh melihat 6 pegawai tetap mendapat daftar nama seluruh tenant.

    **Lookup HR lain belum disaring.**

---

## Sync absensi — jalur agent, bukan JWT

```
POST /api/hr/attendance/sync/
X-Agent-Key: <MEINOVA_AGENT_API_KEY>
```

Kontraknya **tidak boleh diubah diam-diam** — agent berjalan di mesin klien dan tidak ikut ter-deploy:

- Dedup lewat **`source_key`** dari agent, disimpan sebagai `external_id`
- Respons **wajib** menyertakan `data.results[]` berisi `{source_key, success, status, message}` per record — record yang tidak muncul **dianggap gagal** oleh agent
- `status: "unmatched"` = employee tidak ketemu
- Pencocokan **murni lewat `employee_number`**; nama dipakai sebagai **alarm, bukan gerbang** (`name_warning`)

Detail: [Attendance](Attendance.md).

---

## Import

Lewat jalur generik:

```
POST /api/imports/hr.employee/{preview,confirm}/
GET  /api/imports/hr.employee/template/
GET  /api/imports/jobs/<public_id>/
```

URL import attendance lama (`/api/hr/attendance/import/{preview,confirm}/`) **sengaja dibiarkan hidup** sebagai jalur transisi.

---

## Cakupan data

Tiap viewset menyatakan `data_scope`:

```python
data_scope = {
    "company": "employee__organization__company",
    "location": "employee__organization__location",
    "own": "employee__user_id",
}
```

`EMPLOYEE` dibatasi `own`, jadi daftar rosternya 1 baris dan POST-nya dibalas 403 — dua lapis berbeda yang kebetulan menghasilkan read-only.

!!! warning "Kunci yang tidak ada di peta dilewati, bukan menolak semua"
    Jadi viewset yang lupa menyebut `own` justru **terbuka semua** untuk role yang dicakup `own`.
