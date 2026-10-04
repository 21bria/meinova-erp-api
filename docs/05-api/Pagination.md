# Pagination

`apps.core.pagination.StandardPagination`, turunan `PageNumberPagination`. Dipasang sebagai `DEFAULT_PAGINATION_CLASS`, jadi berlaku di semua list endpoint.

---

## Parameter

```
GET /api/hr/employees/?page=2&page_size=50
```

| Param | Default | Batas |
|---|---|---|
| `page` | 1 | |
| `page_size` | `API_PAGE_SIZE` env, jatuh ke `DEFAULT_PAGE_SIZE = 20` | `MAX_PAGE_SIZE = 100` |

Konstantanya di `apps/core/constants/common.py`.

---

## Response

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

Jumlah total dibaca dari **`meta.count`**, bukan `data.length`.

---

## `page_size` di atas batas dipotong diam-diam

`max_page_size = 100`. Nilai `?page_size=500` **tidak** ditolak — DRF memotongnya jadi 100 tanpa pesan.

!!! danger "Frontend tidak boleh menawarkan pilihan di atas 100"
    Kalau ditawarkan, pengguna memilih 500, halaman menampilkan 100 baris, tapi `total_pages` dihitung dari 100 — angkanya konsisten, tapi **tidak sesuai yang dia pilih**, dan tidak ada satu pun petunjuk kenapa.

---

## Semua pagination server-side

Tidak ada satu layar pun yang memuat semua baris lalu memotongnya di browser. Termasuk:

- Tabel CRUD hasil generate
- Kotak masuk workflow, submissions, running documents (`WorkflowPagination.vue` yang sama untuk ketiganya)
- Daftar kandidat di dialog Add Employees

**Pengecualian yang sah:** endpoint lookup. Dropdown memakai pencarian server-side dengan batas hasil, bukan pagination berhalaman — orang tidak menelusuri dropdown halaman per halaman.

---

## Kotak masuk memundurkan halaman sendiri

Setelah approver memutuskan, baris yang baru diputuskan **hilang** dari daftar. Kalau ia sedang di halaman terakhir dan itu baris satu-satunya, halamannya jadi kosong — dan halaman kosong terlihat seperti "semuanya sudah selesai".

Karena itu ketiga layar workflow memundurkan `page` otomatis begitu halaman aktif jadi kosong sementara `count` masih > 0.

---

## Endpoint yang sengaja tidak berpaginasi

| Endpoint | Alasan |
|---|---|
| `GET .../export/` | CSV memang harus utuh; dialirkan `queryset.iterator(chunk_size=500)` supaya tidak memuat semuanya ke memori |
| `GET .../ui-schema/` | bukan data |
| `GET /api/administration/dashboard/summary/` | satu objek berisi semua widget |
| Dashboard modul (`BaseDashboardAPIView`) | idem — satu request mengembalikan seluruh widget |

!!! note "Kenapa dashboard satu request"
    Satu endpoint per widget bikin halaman seperti HR menembak **12 request** hanya untuk render pertama. Alasan yang sama dipakai `dashboard/summary/` di beranda.

---

## Performa

Halaman berikutnya tetap menjalankan `COUNT(*)` penuh. Untuk tabel yang sudah besar itu jadi bagian termahal dari request.

**Belum dioptimasi.** Kalau nanti perlu, arahnya `CountlessPagination` untuk layar yang tidak butuh total, bukan mengubah `StandardPagination` yang sudah dipakai semua orang.

Yang lebih sering jadi penyebab lambat, dan lebih mudah diperbaiki: **kolom relasi tanpa `select_related`**. Satu tabel 20 baris dengan 5 kolom FK yang lupa di-`select_related` menjalankan 101 query.
