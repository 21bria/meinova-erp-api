# Organization — API

Prefix `/api/administration/organization/`. Aturan umum di [Standar API](../../05-api/Standards.md).

---

## CRUD

| Resource | Endpoint | `framework_module` |
|---|---|---|
| Company | `.../companies/` | `administration/organization/company` |
| Branch | `.../branches/` | `.../branch` |
| Location | `.../locations/` | `.../location` |
| Division | `.../divisions/` | `.../division` |
| Department | `.../departments/` | `.../department` |
| Section | `.../sections/` | `.../section` |
| Position | `.../positions/` | `.../position` |
| Cost Center | `.../cost-centers/` | `.../cost-center` |
| Facility | `.../facilities/` | `.../facility` |

Semuanya `BaseMasterViewSet` — dapat `ui-schema/`, `export/`, `bulk-delete/` gratis.

---

## Lookup

```
/api/administration/organization/lookup/{companies,branches,locations,divisions,
                                          departments,sections,positions,cost-centers}/
```

!!! danger "Path lookup gampang salah tulis dan gagalnya diam"
    Bentuknya `/<prefix domain>/lookup/<nama>/`, **bukan** `/<resource>/lookup/`.

    Schema attendance sempat memakai `/api/administration/companies/lookup/` yang **tidak pernah ada** — dropdown-nya 404 tanpa pesan error.

### `OrganizationScopedLookup`

Seluruh lookup organisasi mewarisinya. Ia:

1. Mendaftarkan **seluruh induk** di `filter_fields`
2. Memakai pola **"cocok dengan induk ATAU induknya null"**

!!! danger "Parameter yang tidak terdaftar di `filter_fields` diabaikan diam-diam"
    Penyebab klasik dropdown yang "tidak mau tersaring".

### `CompanyLookup` mengirim `next_employee_number`

`serialize()` menyertakan `EmployeeNumberService.preview()`, supaya field Company di form Employee bisa `autofill={"employee_number": "next_employee_number"}` — memilih Company langsung memperlihatkan nomor yang akan terbit.

Angka itu **tebakan**: tidak mengunci, tidak menaikkan penghitung, tidak membuat baris master.

---

## Penyaringan berantai di form

```python
field.lookup(
    lookup_endpoint=".../locations/",
    lookup_params={"company_id": "$company", "branch_id": "$branch"},
    depends_on="company",
)
```

!!! warning "Kirim SELURUH induk, bukan cuma yang terdekat"
    Karena level organisasi boleh dilompati, penyaringan satu level akan **gugur** dan dropdown menampilkan data seluruh perusahaan.

`depends_on` cukup `"company"` — hanya Company yang wajib, dan `depends_on` yang menyebut level opsional akan **mematikan** dropdown selama level itu kosong.

Detail: [Lookup](../../02-Framework/Lookup.md).

---

## Filter berantai di toolbar tabel

Bekerja dengan mekanisme yang sama sejak empat bug di jalur itu diperbaiki. Sebelumnya: di tabel Locations, memilih Company "Karya Wijaya" tetap menyisakan dropdown Branch berisi **dua belas baris bernama persis "Default Location"** dari dua belas perusahaan berbeda.

!!! warning "Schema organisasi memakai `filter` bentuk dict"
    ```python
    filter={"group": "quick", "order": 20}
    ```

    Generator dulu memeriksa `=== true`, jadi **semuanya jatuh** — layar Departments tidak punya filter Company, Location, maupun Division sama sekali.

    Gagalnya diam, dan ke arah yang paling sulit dilacak: filter yang tidak pernah muncul tidak bisa dibedakan dari filter yang memang tidak ditulis.

---

## Cakupan data

!!! danger "Delapan dari sembilan viewset organisasi belum punya `data_scope`"
    Tabel Company/Branch/Location/Department masih terbaca **utuh** oleh admin bercakupan sempit.

    Ini utang yang diketahui — dashboard Administration justru lebih ketat daripada tabelnya.

Kalau menambahkannya, ingat: `filter_queryset()`, bukan `get_queryset()`. Alasannya di [Request Lifecycle](../../02-Framework/Request-Lifecycle.md#cakupan-data-datascopeservice).

---

## Kalender & Work Calendar

Berkait erat dengan Location:

```
/api/administration/calendar/{fiscal-years,posting-periods,holidays,work-calendars,roster-crews}/
```

!!! bug "Kolom Company/Location '-' di semua baris"
    `HolidaySerializer`/`WorkCalendarSerializer` cuma `fields = "__all__"`, sementara kolom hasil generate mencari `company_name`/`location_name`.

    Akibatnya di sini lebih buruk daripada kolom kosong biasa: keduanya **wajib per company** di model, jadi satu hari libur nasional menghasilkan **dua belas baris identik kecuali kolom Company** — dan kolom itulah yang tidak terisi, sehingga datanya terbaca seperti duplikat yang perlu dibersihkan.

    Sudah ditambahkan, plus `company`/`location` sebagai penyaring — introspeksi memberi keduanya filter **tanpa endpoint**, jadi dropdown-nya selalu kosong dan harus disebut eksplisit di `ORGANIZATION_FILTER_FIELDS`.

Tujuh filter hari (Monday…Sunday) dimatikan — nyaris tidak ada yang mencari "kalender yang Seninnya hari kerja".

!!! bug "`PostingPeriodService.list()` mengurutkan lewat kolom yang tidak ada"
    `period_no` tidak pernah ada di model, jadi tab Accounting Period membalas **500** setiap kali dibuka dan tidak pernah bisa dipakai siapa pun. Diurutkan `fiscal_year__year, start_date, code`.

---

## Checklist menambah resource organisasi

- [ ] Kode unik **per company** (`UniqueConstraint` + `condition=Q(is_deleted=False)`)
- [ ] Lookup mewarisi `OrganizationScopedLookup`
- [ ] Seluruh induk terdaftar di `filter_fields`
- [ ] `lookup_params` di schema menyebut seluruh induk
- [ ] `depends_on` hanya menyebut induk yang **wajib**
- [ ] Serializer menyebut `<relasi>_name` untuk setiap FK yang jadi kolom
- [ ] `filterset_fields` memuat semua filter
- [ ] `data_scope` — jangan ikut melewatkannya lagi
