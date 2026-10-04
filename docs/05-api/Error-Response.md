# Error Response

Semua error melewati `meinova_exception_handler` (`apps/core/exceptions/handler.py`).

---

## Bentuk

```json
{
  "success": false,
  "message": "Validation failed.",
  "errors": {
    "employee": ["This field is required."],
    "end_date": ["Tanggal selesai tidak boleh sebelum tanggal mulai."]
  },
  "status_code": 400
}
```

Untuk error yang punya `detail` tunggal (403, 404, 401), `errors` bernilai `null` dan kalimatnya pindah ke `message`:

```json
{
  "success": false,
  "message": "You do not have permission to perform this action.",
  "errors": null,
  "status_code": 403
}
```

Logikanya di handler:

```python
if isinstance(data, dict) and "detail" in data:
    message = str(data["detail"]); errors = None
else:
    message = "Validation failed."; errors = data
```

---

## Yang paling penting: penerjemahan `ValidationError` Django

```python
if isinstance(exc, DjangoValidationError):
    exc = DRFValidationError(as_serializer_error(exc))
```

**DRF hanya mengenali `ValidationError` miliknya sendiri.** Tanpa penerjemahan ini, `Model.full_clean()` yang gagal di service membalas **HTTP 500**, bukan 400 berisi error per field.

Ini bukan detail kecil: viewset ber-`ServiceWriteMixin` menjalankan `full_clean()` di setiap tulis, jadi seluruh validasi model melewati jalur ini.

!!! warning "Konsekuensi memasang `ServiceWriteMixin`"
    Begitu mixin terpasang, `full_clean()` benar-benar jalan — dan aturan `clean()` yang selama ini tidak pernah tersentuh lewat API tiba-tiba menolak data yang sebelumnya lolos. Itu **benar**, tapi jangan kaget.

---

## Kode status

| Status | Kapan |
|---|---|
| **400** | validasi serializer, `Model.clean()`, `assert_*` di service |
| **401** | token tidak ada / kedaluwarsa |
| **403** | `ModelPermission`, `CanManageSecurity`, `CanConfigureWorkflow` |
| **404** | id tidak ada, **atau id ada tapi di luar cakupan data** |
| **405** | method dimatikan (`http_method_names`) |
| **500** | bug |

!!! note "404 vs 403 pada cakupan data"
    `DataScopeService` dipasang di `filter_queryset()`, jadi baris di luar cakupan **tidak ada** dari sudut pandang `get_object()` → **404**, bukan 403.

    Itu disengaja: 403 memberi tahu "baris ini ada tapi bukan urusanmu", dan di daftar pegawai lintas perusahaan itu sendiri sudah kebocoran.

---

## Pesan error harus bisa ditindaklanjuti

Aturan yang berlaku di seluruh service:

| Buruk | Baik |
|---|---|
| "Sudah ada cuti lain" | "Bentrok dengan LV-2026-0042 (14–18 Agustus)" |
| "Constraint uniq_active_employee_number is violated" | "Nomor pegawai KW260007 sudah dipakai Budi Santoso" |
| "Tidak ada approver" | "Tidak ada pemegang ADMIN-SECTION di Section Site Operations. Role cadangan ADMIN-DEPARTMENT juga tidak ada pemegangnya di Department Operations…" |
| "Data tidak valid" | "Location Gebe Port bukan milik Branch Jakarta" |

Alasannya konkret: constraint DB melempar kalimat yang **tidak menempel di kolom mana pun**, jadi form tidak bisa menandai field yang salah dan penggunanya harus menebak. Karena itu keunikan nomor pegawai diperiksa **di serializer** lebih dulu, dengan pesan yang menyebut siapa pemakainya; constraint DB tetap jadi jaring terakhir untuk pemanggil non-API (importer, seed).

---

## Penolakan yang tidak terlihat di layar

Bug yang pernah menjatuhkan seluruh pengalaman penolakan: **request yang ditolak gagal tanpa satu kalimat pun.** Tombol Save ditekan, tidak terjadi apa-apa.

Lima sebab bertumpuk — semuanya di frontend, semuanya sudah diperbaiki di `framework/`:

1. `notify` tidak pernah dioper (dari 196 pemakaian composable CRUD, hanya 4 yang mengopernya)
2. Klien membaca `detail`, envelope menaruhnya di `message`
3. Grid inline diam total untuk error tanpa nama field
4. `<X>Form.vue` menyaring error ke kunci yang cocok dengan kolom tab, membuang `detail`
5. `page.vue` menelan kegagalan simpan — benar untuk 400 per-field, **salah untuk 403** yang tidak punya field mana pun untuk ditempeli

Detailnya di [Permission](../02-Framework/Permission.md#penolakan-403-dulu-tidak-terlihat-sama-sekali-di-layar).

!!! tip "Kalau menambah error baru, pastikan ia punya nama field"
    Error tanpa nama field tidak menempel ke kolom mana pun di form. Untuk error yang memang lintas field, pakai kunci `detail` / `non_field_errors` / `__all__` — ketiganya dirender `MFormBuilder` sebagai banner di bawah form.

---

## Yang belum ada

- **Kode error terstruktur** (`error_code: "LEAVE_OVERLAP"`). Klien hari ini mencocokkan kalimatnya, dan itu rapuh terhadap perubahan bahasa.
- **Request ID di response.** `apps/core/middleware/request_id.py` masih file kosong dan tidak terdaftar di `MIDDLEWARE`, jadi tidak ada cara mengaitkan error di layar dengan baris log di server.
