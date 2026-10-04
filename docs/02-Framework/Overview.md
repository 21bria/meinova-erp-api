# Framework — Overview

`apps/framework` + `apps/core` adalah fondasi yang dipakai **semua** modul bisnis. Tidak ada satu pun modul yang menulis ulang CRUD, pagination, export, atau schema UI-nya sendiri.

Kalau kamu menambah kode yang terasa "seharusnya sudah ada", periksa di sini dulu.

---

## Isi

| Halaman | Untuk |
|---|---|
| [Siklus Request](Request-Lifecycle.md) | View → Service → Model, tiga lapis penjagaan, envelope response |
| [Pipeline BE → FE](BE-to-FE-Pipeline.md) | **Wajib dibaca.** Bagaimana schema jadi halaman Nuxt |
| [Membuat Modul Baru](Build-A-Module.md) | Tutorial end-to-end |
| [Base Classes](Base-Classes.md) | `BaseModel`, `BaseReference`, `BaseService`, `BaseMasterViewSet`, dst. |
| [Schema DSL](Schema.md) | Referensi builder: `field`, `ui`, `tabs`, `action` |
| [Lookup](Lookup.md) | Dropdown, registry, penyaringan berantai |
| [Permission](Permission.md) | `ModelPermission`, `DataScopeService`, `MenuAccessService` |
| [Generator](Generator.md) | CLI Nuxt, template, apa yang boleh disunting tangan |

---

## Pembagian `core` vs `framework`

| | Isi |
|---|---|
| `apps/core` | Base model, base service, envelope response, exception handler, pagination, konstanta |
| `apps/framework` | Schema UI, introspeksi, base viewset, lookup, import generik, builder DSL, periode dashboard |

Aturan pembagi: **`core` tidak tahu apa-apa soal UI.** Kalau sesuatu ada karena frontend membutuhkannya, tempatnya di `framework`.

---

## Peta berkas

```
apps/framework/
├── builders/           # DSL schema: field, ui, tabs, action, dashboard, importer, …
├── introspection/      # model.py, serializer.py, schema.py → build_ui_schema()
├── views/
│   ├── master.py       # BaseMasterViewSet — CRUD + ui-schema/ + export/ + bulk-delete/
│   ├── reference.py    # BaseReferenceViewSet
│   ├── tree.py         # BaseTreeAPIView
│   ├── setting.py      # BaseSettingAPIView
│   ├── dashboard.py    # BaseDashboardAPIView
│   ├── mixins.py       # ServiceWriteMixin
│   ├── framework.py    # framework_schema_view — pencari module global
│   └── permissions.py  # framework_permissions_view — peta izin per endpoint
├── lookup/             # registry, decorator, base view
├── imports/            # pipeline import generik + registry importer
├── filters.py          # SafeSearchFilter
├── periods.py          # resolve_period(), trend_buckets()
└── urls.py

apps/core/
├── models/base.py      # BaseModel, BaseReference
├── services/base.py    # BaseService + turunannya
├── responses/api.py    # success_response, created_response, error_response
├── exceptions/handler.py
├── pagination.py       # StandardPagination
├── constants/common.py # MAX_PAGE_SIZE
└── middleware/current_user.py  # CurrentRequestMiddleware
```

---

## Empat jenis layar

Yang menentukan bentuk layar adalah base class yang dipakai viewset-nya.

| `schema_type` | Base class | Endpoint schema | Bentuk |
|---|---|---|---|
| `crud` | `BaseMasterViewSet` | `<resource>/ui-schema/` | tabel + form |
| `tree` | `BaseTreeAPIView` | sendiri | pohon centang |
| `setting` | `BaseSettingAPIView` | sendiri | satu form, satu record |
| `dashboard` | `BaseDashboardAPIView` | `Cls.as_schema_view()` | grid widget |

Keempatnya ditemukan `framework_schema_view` lewat `framework_module`:

```
GET /api/framework/schema/<framework_module>/
```

!!! warning "`framework_module` wajib diisi dan unik"
    Kalau tidak, module itu **tidak bisa digenerate** di frontend. Dan kalau dua view memakai nilai yang sama, yang ketemu lebih dulu yang menang — itu sebabnya subclass hasil `BaseDashboardAPIView.as_schema_view()` sengaja mengosongkan `framework_module`-nya.

---

## Apa yang gratis, apa yang harus ditulis

**Gratis dari `BaseMasterViewSet`:**

- CRUD lengkap + pagination + ordering + search
- `GET .../ui-schema/`
- `GET .../export/` (CSV, kolomnya = kolom tabel, ikut filter aktif)
- `POST .../bulk-delete/`
- Soft delete di `destroy()` dan bulk-delete
- `ModelPermission` (lewat `get_permissions()`)
- Penyaringan `RoleDataPermission` (lewat `filter_queryset()`)

**Harus ditulis sendiri:**

- `framework_module`, `schema`, `serializer_class`
- `service_class` + **`ServiceWriteMixin`** kalau logika service harus jalan
- `search_fields` yang cocok dengan model
- `filterset_fields` untuk tiap filter yang dideklarasikan di schema
- `data_scope`
- `select_related` / `prefetch_related` untuk kolom relasi yang dipakai tabel

---

## Import generik

Fitur import juga schema-driven. Untuk membuat satu resource bisa diimport:

1. Bikin importer turunan `BaseImporter` (`module`, `mapping`, `required_fields`, `resolve()`, `write()`), hias `@register_importer`
2. Pastikan modulnya di-import saat startup — daftarkan di `AppConfig.ready()`
3. Tambahkan `"import": importer.config(module="...")` ke schema + `"import": True` di `ui`
4. Seed `ImportProfile` untuk module itu

Sesudah itu endpoint berikut **otomatis tersedia** — tidak perlu bikin view/URL/task baru:

| Endpoint | Isi |
|---|---|
| `POST /api/imports/<module>/preview/` | validasi + resolusi relasi, tanpa menulis |
| `GET /api/imports/<module>/template/` | CSV template header + baris contoh |
| `POST /api/imports/<module>/confirm/` | antre ke Celery, balas 202 + `jobPublicId` |
| `GET /api/imports/profiles/lookup/?module=` | profile mapping per module |
| `GET /api/imports/jobs/<public_id>/` (+ `/errors/`, `/error-report/`) | progres & laporan |

Pipeline per baris: `normalize()` → `validate()` → `resolve()` → `write()`.

`ImportProfile` menimpa `mapping` bawaan importer, jadi klien dengan header berbeda cukup ubah profile tanpa sentuh kode. Urutan penerapannya: `mapping` (pilih kolom) → `defaults` (isi yang kosong) → `value_mapping` → `datetime_formats`.

!!! danger "Format tanggal US terbaca salah tanpa error"
    `DEFAULT_DATE_FORMATS` mencoba `%d/%m/%Y` **sebelum** `%m/%d/%Y`. File berformat US (`5/2/2011`) terbaca sebagai 5 Februari tanpa satu pun peringatan kalau `datetime_formats` tidak diisi di profile.

    Kolom tanggal diseragamkan ke ISO berdasarkan `date_fields` pada importer — importer baru yang punya kolom tanggal **wajib** mengisinya.

Detail: [Membuat Modul Baru](Build-A-Module.md).

---

## Periode dashboard

`apps/framework/periods.py`. Periode adalah **rentang tanggal**, bukan pasangan bulan/tahun.

`?mode=&start=&end=` diubah `resolve_period()` jadi satu dict, dan resolver widget cukup membaca `period["start"]` / `period["end"]` — satu widget melayani mode harian, mingguan, bulanan, kuartalan, tahunan, dan rentang bebas **tanpa cabang khusus**.

- Mode yang boleh dipakai ditentukan `modes` pada `dashboard.period_filter(...)`; mode di luar daftar itu ditolak backend.
- `?year=&month=` masih diterima sebagai jalur lama.
- Pembanding tren untuk mode kalender memakai periode kalender sebelumnya (Februari vs Januari **penuh**), bukan "mundur sekian hari".
- `trend_buckets()` memberi deret titik dengan satuan mengikuti mode — tanpa ini, memilih "hari ini" menghasilkan chart satu titik.
- **Awal minggu = Senin.** Frontend menghitung ulang rentang yang sama untuk label tombol, jadi aturan ini harus tetap sama di dua repo.
- **Tren dikembalikan `None` kalau pembandingnya nol.** "Naik 100%" untuk data yang baru mulai terisi lebih menyesatkan daripada tidak menampilkan apa-apa.
