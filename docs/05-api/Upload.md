# Upload File

`apps/uploads` — satu tabel `UploadedFile` untuk **semua** lampiran di sistem, bukan `FileField` yang tersebar di tiap model.

---

## Kenapa satu tabel terpusat

Kalau tiap model punya `FileField` sendiri:

- tidak ada satu tempat untuk menjawab "file apa saja yang dipegang tenant ini"
- validasi ekstensi & ukuran harus ditulis ulang di setiap model
- soft delete file jadi ikut aturan model induknya, padahal file punya siklus hidupnya sendiri (restore, replace, purge)
- tidak ada dedup lewat checksum

Karena itu model lain menunjuk `UploadedFile` lewat FK, dan schema field bertipe `file`/`image` otomatis diarahkan ke endpoint upload.

---

## Endpoint

Base: `/api/uploads/`. Lookup pakai **`public_id` (UUID)**, bukan pk.

| Method | URL | Isi |
|---|---|---|
| `POST` | `/api/uploads/` | upload satu file |
| `POST` | `/api/uploads/multiple/` | upload banyak sekaligus |
| `GET` | `/api/uploads/` | daftar |
| `GET` | `/api/uploads/<public_id>/` | detail |
| `POST` | `/api/uploads/<public_id>/replace/` | ganti isi, **`version` naik** |
| `GET` | `/api/uploads/<public_id>/download/` | unduh, `download_count` naik |
| `GET` | `/api/uploads/<public_id>/preview/` | inline (gambar/PDF) |
| `DELETE` | `/api/uploads/<public_id>/` | soft delete |
| `GET` | `/api/uploads/deleted/` | daftar yang terhapus |
| `POST` | `/api/uploads/<public_id>/restore/` | kembalikan |
| `POST` | `/api/uploads/<public_id>/purge/` | **hard delete** |

Parser: `MultiPartParser`, `FormParser`, `JSONParser`.

!!! note "`public_id` UUID, bukan pk"
    Pk berurutan bisa ditebak, dan URL file gampang bocor lewat share link. `public_id` juga salah satu dari sedikit kolom unik yang **sengaja tidak** dikondisikan ke `is_deleted` — UUID tidak pernah dipakai ulang.

!!! warning "`purge/` satu-satunya hard delete di sistem ini"
    Di seluruh codebase penghapusan selalu soft. File pengecualian, karena byte-nya benar-benar memakan disk dan retensi file punya aturannya sendiri.

---

## Batasan

`config/settings/uploads.py`:

| Setting | Nilai |
|---|---|
| `UPLOAD_MAX_FILE_SIZE` | 25 MB |
| `UPLOAD_MAX_MULTIPLE_FILES` | 20 |
| `UPLOAD_ALLOWED_EXTENSIONS` | `.jpg .jpeg .png .gif .webp .pdf .doc .docx .xls .xlsx .csv .ppt .pptx .txt .rtf .zip` |
| `UPLOAD_ALLOWED_MIME_TYPES` | daftar padanannya |

Diperiksa **dua-duanya** — ekstensi *dan* MIME type (`apps/uploads/validators.py`). Ekstensi saja tidak cukup: `.pdf` yang isinya executable lolos kalau cuma nama berkasnya yang diperiksa.

Nama file dilewatkan `get_valid_filename()` dan disimpan sebagai `stored_name`; `original_name` menyimpan yang diketik user.

---

## Kolom yang perlu diketahui

| Kolom | Isi |
|---|---|
| `public_id` | UUID — identitas publik |
| `file_type`, `category` | `TextChoices` untuk penyaringan |
| `size`, `extension`, `mime_type` | metadata dasar |
| `checksum_sha256` | dedup & verifikasi integritas |
| `width`, `height`, `page_count` | diisi `MetadataService` |
| `thumbnail` | diisi `ThumbnailService` |
| `version`, `replaced_at` | naik tiap `replace/` |
| `download_count`, `last_download_at` | dinaikkan lewat `F()`, bukan read-modify-write |
| `is_public` | |
| `expires_at` | retensi — **belum ada yang mengeksekusinya** |
| `status` | `TextChoices` |

`download_count` dinaikkan dengan `F("download_count") + 1` supaya dua unduhan bersamaan tidak saling menimpa.

---

## Service

| Service | Tugas |
|---|---|
| `UploadService` | validasi + simpan + metadata |
| `ReplaceService` | ganti isi, naikkan versi |
| `UploadDeleteService` | soft delete / restore / purge |
| `MetadataService` | dimensi gambar, jumlah halaman PDF |
| `ThumbnailService` | thumbnail |
| `StorageService` | abstraksi lokasi penyimpanan |
| `AttachmentLifecycleService` | kaitan file ↔ record induk |

---

## Dari sisi schema UI

Field bertipe `file`/`image` di schema otomatis dinormalisasi (`normalize_upload_field` di `apps/framework/introspection/schema.py`):

```python
field.file(label="Contract Document", accept=[".pdf"])
field.image(label="Photo")
```

Endpoint bawaannya `/api/uploads/`, widget `upload` / `image-upload`.

!!! danger "Kolom file mematikan pencatatan audit kalau tidak ditangani"
    `PrintSetting.logo` bertipe `ImageFieldFile`, dan `_jsonable()` di `BaseService._audit` melempar saat menyerialisasinya. Exception-nya ditelan `except`, jadi **tabel audit untuk model itu tetap nol baris tanpa satu pun pesan**.

    Sudah diperbaiki dengan `DjangoJSONEncoder` + `default=str`. Kalau menambah tipe kolom tidak lazim, periksa jalur ini.

!!! note "File tidak ikut export CSV"
    `export=False` datang dari introspeksi untuk field file, image, dan many-to-many — memang tidak bisa diekspor jadi satu sel.

---

## Yang belum ada

- **Eksekusi `expires_at`.** Kolomnya tersimpan, tapi belum ada task yang membersihkan file kedaluwarsa. Penjadwalnya sudah siap — `django_celery_beat` aktif dan `CELERY_BEAT_SCHEDULER` sudah `DatabaseScheduler` — jadi yang kurang cuma tasknya.
- **Storage backend selain lokal.** `config/settings/storage.py` ada, tapi S3/GCS belum dikonfigurasi. `MEDIA_URL` hanya dilayani Django saat `DEBUG`.
- **Virus scanning.**
- **Cakupan data.** `UploadedFileViewSet` bukan turunan `BaseMasterViewSet`, jadi `DataScopeService` tidak berlaku — daftarnya disaring `IsAuthenticated` saja.
