# Standar API

Aturan yang berlaku untuk **setiap** endpoint di sistem ini. Kalau endpoint barumu menyimpang dari salah satu, itu keputusan yang perlu alasan tertulis.

---

## Envelope response

Semua response memakai bentuk yang sama:

```json
{
  "success": true,
  "message": "Success.",
  "data": { },
  "status_code": 200
}
```

Response berpaginasi menambahkan `meta`:

```json
{
  "success": true,
  "message": "Data retrieved successfully.",
  "data": [ ],
  "meta": {
    "count": 128,
    "total_pages": 7,
    "page": 1,
    "page_size": 20,
    "next": "http://demo.localhost:8000/api/hr/employees/?page=2",
    "previous": null
  },
  "status_code": 200
}
```

Helper di `apps/core/responses/api.py`:

| Helper | Status |
|---|---|
| `success_response(data, message=, meta=)` | 200 |
| `created_response(data, message=)` | 201 |
| `error_response(message=, errors=, status_code=)` | 400 (default) |
| `no_content_response()` | 204 |

!!! warning "Kunci pesannya `message`, bukan `detail`"
    Klien yang membaca `detail` lebih dulu lalu jatuh ke `error.message` milik `$fetch` akan menampilkan `[POST] "http://…": 403 Forbidden` — teks teknis, bukan pesan yang bisa ditindaklanjuti. Di frontend gunakan `apiErrorMessage()`.

---

## Konvensi URL

```
/api/<domain>/<resource>/
/api/<domain>/<resource>/<id>/
/api/<domain>/<resource>/<id>/<action>/
/api/<domain>/lookup/<nama>/
```

- **Plural, kebab-case**: `/api/hr/travel-requests/`, bukan `/api/hr/travelRequest/`
- **Trailing slash wajib** (DRF `DefaultRouter`)
- Action pakai kata kerja: `submit/`, `approve/`, `withdraw/`, `bulk-delete/`

Rute didaftarkan berlapis:

```
config/urls.py → apps/<domain>/api/urls.py → apps/<domain>/api/<resource>/urls.py
```

!!! danger "Urutan pendaftaran rute pernah menelan endpoint"
    - Di `apps/hr/api/urls.py`, rute spesifik harus **di atas** router viewset umum.
    - Di `apps/imports/api/urls.py`, rute `<path:module>` harus **paling akhir** — ia serakah dan akan menelan `jobs/` dan `profiles/`.
    - Di `apps/framework/urls.py`, rute baru berawalan `schema/` wajib didaftarkan sebelum `schema/<path:module>/`.

---

## Prefix yang sudah terdaftar

| Prefix | App |
|---|---|
| `/api/accounts/` | auth, users, roles, permissions |
| `/api/framework/` | schema module + peta izin |
| `/api/administration/` | organisasi, master, kalender, dashboard home |
| `/api/workflow/` | engine approval generik |
| `/api/hr/` | HR |
| `/api/payroll/` | payroll |
| `/api/imports/`, `/api/uploads/` | import & upload generik |
| `/api/docs/`, `/api/schema/` | Swagger + OpenAPI |

---

## Default DRF

`config/settings/base.py`:

```python
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ("...JWTAuthentication",),
    "DEFAULT_PERMISSION_CLASSES": ("rest_framework.permissions.IsAuthenticatedOrReadOnly",),
    "DEFAULT_RENDERER_CLASSES": ("rest_framework.renderers.JSONRenderer",),
    "DEFAULT_FILTER_BACKENDS": (DjangoFilterBackend, SearchFilter, OrderingFilter),
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.StandardPagination",
    "PAGE_SIZE": 20,
    "EXCEPTION_HANDLER": "apps.core.exceptions.handler.meinova_exception_handler",
}
```

!!! note "`IsAuthenticatedOrReadOnly` sebagai default itu disengaja"
    Membaca dibiarkan terbuka di level DRF; yang menjaga sungguhan adalah `ModelPermission` (menulis) dan `DataScopeService` (baris mana yang terlihat). Lihat [Permission](../02-Framework/Permission.md).

    Tapi artinya: **viewset yang tidak turunan `BaseMasterViewSet` dan tidak menulis `permission_classes` sendiri bisa dibaca siapa saja.**

`BaseMasterViewSet` menimpanya jadi `[IsAuthenticated, ModelPermission]`, dan memasang `ModelPermission` lewat `get_permissions()` supaya viewset yang menulis ulang `permission_classes` tidak lolos.

---

## Multi-tenant

Tenant ditentukan **hostname**, bukan header dan bukan payload:

```
http://demo.localhost:8000/api/hr/employees/    → schema "demo"
http://klien-a.meinova.id/api/hr/employees/     → schema "klien_a"
```

Tidak ada `?tenant=` dan tidak ada `X-Tenant-Id`. Konsekuensinya klien API harus memakai domain tenant yang benar, termasuk saat generate frontend (`MEINOVA_API_BASE_URL`).

Pengecualian: agent absensi on-premise memakai header `X-Agent-Key`, tapi tenantnya **tetap** dari hostname.

---

## Endpoint yang `AllowAny`

Dua, dan keduanya disengaja:

| Endpoint | Alasan |
|---|---|
| `GET /api/framework/schema/<module>/` | supaya generator frontend bisa jalan tanpa token |
| `GET <resource>/ui-schema/` | idem |

Artinya **struktur field ikut terekspos publik**. Yang tidak terekspos: datanya.

---

## Yang gratis di setiap resource CRUD

| Endpoint | Isi |
|---|---|
| `GET .../ui-schema/` | schema UI |
| `GET .../export/` | CSV, kolomnya = kolom tabel, **ikut filter aktif** |
| `POST .../bulk-delete/` | `{"ids": [...]}` |

---

## Checklist endpoint baru

- [ ] URL plural kebab-case + trailing slash
- [ ] Terdaftar berlapis, urutannya benar
- [ ] Balasan memakai envelope (otomatis kalau lewat `BaseMasterViewSet`)
- [ ] `permission_classes` **tidak** ditulis ulang tanpa alasan — kalau ditulis, pastikan `ModelPermission` tetap ikut
- [ ] `data_scope` terisi
- [ ] `search_fields` cocok dengan model
- [ ] `filterset_fields` memuat semua filter di schema
- [ ] `select_related`/`prefetch_related` untuk kolom relasi yang dipakai tabel
- [ ] Muncul benar di `/api/docs/`

---

## Rujukan

[Error Response](Error-Response.md) · [Pagination](Pagination.md) · [Filtering](Filtering.md) · [Sorting](Sorting.md) · [Authentication](Authentication.md) · [Validation](Validation.md) · [Upload](Upload.md)
