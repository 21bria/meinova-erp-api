# Sorting

`rest_framework.filters.OrderingFilter`, terpasang di `BaseMasterViewSet`.

---

## Parameter

```
GET /api/hr/employees/?ordering=full_name
GET /api/hr/employees/?ordering=-created_at
GET /api/hr/employees/?ordering=organization__department__name,-employee_number
```

Awalan `-` = menurun. Beberapa kolom dipisah koma.

---

## Konfigurasi

```python
class BaseMasterViewSet(ModelViewSet):
    ordering_fields = "__all__"
    ordering = ["name"]
```

| Atribut | Isi |
|---|---|
| `ordering_fields` | kolom yang **boleh** disortir. `"__all__"` = semua |
| `ordering` | urutan bawaan kalau `?ordering=` tidak dikirim |

!!! warning "Bawaan `ordering = ["name"]` salah untuk model tanpa kolom `name`"
    Sama seperti `search_fields`. Timpa di viewset-nya:

    ```python
    ordering = ["employee_number"]
    ```

---

## `ordering` di viewset menang atas `Meta.ordering` model

Ini pernah membingungkan.

`OrderingFilter` memakai atribut `ordering` viewset sebagai default, dan `order_by()` yang dihasilkannya **membuang** urutan yang ditulis di `Meta.ordering` model. Jadi mengubah salah satunya saja tidak cukup — keduanya harus disamakan.

Contoh nyata, `RotationTravel`:

```python
# viewset
ordering = ["period__start_date", "period__sequence", "direction", "travel_start_date"]

# model Meta — disamakan
ordering = ["period__start_date", "period__sequence", "direction", "travel_start_date"]
```

Urutannya **ikut periode, bukan tanggal travel** — baris sisipan mendapat nomor urut terakhir yang bebas walau tanggalnya di tengah, jadi menyortir dengan `sequence` saja menaruhnya di dasar tabel.

`direction` sebagai pemecah seri kebetulan benar: `"in" < "out"` secara alfabet, dan itu memang urutan yang diinginkan.

---

## Kolom turunan tidak bisa disortir

Kolom yang dirakit di serializer (`display_name`, `total_days` hasil perhitungan Python, `progress.percent`) **tidak ada di database**, jadi `?ordering=` untuknya ditolak `OrderingFilter` — atau lebih buruk, diabaikan diam-diam kalau `ordering_fields = "__all__"` sempat meloloskannya.

Dua jalan keluar, dan pilih sadar:

| Cara | Kapan |
|---|---|
| **Denormalisasi ke kolom** | kalau memang sering disortir/difilter |
| `sortable=False` di schema | kalau tidak |

`LeaveBalance.used` adalah contoh pilihan pertama: **disimpan, bukan dihitung on-the-fly**, persis supaya bisa disortir dan difilter di tabel. Konsekuensinya ia harus dijumlahkan ulang setiap kali record cuti berubah — dan itu dilakukan `EmployeeLeaveService` dengan **penjumlahan ulang**, bukan penambahan inkremental, supaya tidak bisa hanyut.

---

## Sortir yang menembus relasi

```
?ordering=organization__department__name
```

Bekerja, tapi **wajib** disertai `select_related` di viewsetnya — kalau tidak, tiap baris menambah satu query saat dirender.

---

## Urutan yang punya alasan bisnis

Beberapa `ordering` di sistem ini bukan preferensi tampilan:

| Model | Urutan | Kenapa |
|---|---|---|
| `RotationPeriod` | `rotation, start_date, sequence` | baris sisipan harus duduk di sebelah blok yang dipecahnya, bukan terlempar ke dasar |
| `PostingPeriod` | `fiscal_year__year, start_date, code` | sempat `period_no` yang **tidak ada di model** → tab Accounting Period membalas **500** setiap kali dibuka |
| `BaseReference` | `sort_order, code` | urutan dropdown ditentukan orang, bukan abjad |

!!! bug "`ordering` yang menyebut kolom tak ada = 500, bukan diabaikan"
    `PostingPeriodService.list()` mengurutkan lewat `period_no` yang tidak pernah ada di model, jadi tabnya tidak pernah bisa dipakai siapa pun sejak dibuat.

---

## Checklist

- [ ] `ordering` bawaan menyebut kolom yang benar-benar ada
- [ ] Kalau `Meta.ordering` model penting, viewset menyamakannya
- [ ] Kolom turunan diberi `sortable=False` atau didenormalisasi
- [ ] Sortir lintas relasi disertai `select_related`
