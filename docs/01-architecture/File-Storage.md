# File Storage

`apps/uploads` — satu tabel `UploadedFile` untuk semua lampiran. Detail endpoint dan modelnya di [API → Upload](../05-api/Upload.md).

Halaman ini soal **penyimpanan fisiknya**.

---

## Konfigurasi

```python
# config/settings/storage.py
DEFAULT_FILE_STORAGE = "django_tenants.files.storage.TenantFileSystemStorage"
MULTITENANT_RELATIVE_MEDIA_ROOT = "%s"
```

```python
MEDIA_URL  = "/media/"
MEDIA_ROOT = BASE_DIR / "media"
```

Hasilnya satu direktori per schema:

```
media/
├── demo/
├── klien_a/
└── klien_b/
```

**Itu yang membuat restore per-tenant mungkin** — direktori tenant bisa disalin sendirian.

---

## Dua penghalang produksi

### 1 · `MEDIA_URL` hanya dilayani saat `DEBUG`

```python
# config/urls.py
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
```

Di produksi **tidak ada yang melayaninya**. Nginx harus dikonfigurasi.

### 2 · Disk lokal menahan horizontal scaling

Dua replika `web` akan melayani file yang berbeda-beda: upload mendarat di satu replika, permintaan unduhnya bisa jatuh ke replika lain yang tidak punya filenya.

!!! danger "Ini penghalang pertama untuk menambah replika"
    Jalan keluar, dari yang paling murah:

    1. Volume bersama (NFS) — cepat, jadi penghalang I/O sendiri nanti
    2. Object storage (S3/GCS) — `config/settings/storage.py` sudah jadi tempatnya

    Backend object storage yang dipilih **wajib tetap memisahkan per schema**.

---

## Backup: file dan DB harus konsisten

`UploadedFile` menyimpan metadata (checksum, ukuran, versi) di DB, byte-nya di disk.

!!! warning "Backup DB jam 02:00 dan backup file jam 03:00 menghasilkan ketidakcocokan"
    Baris DB yang menunjuk file yang belum ada, atau file yatim.

    Kalau selisih itu tidak bisa dihindari, **backup file lebih dulu** — baris DB yang menunjuk file hilang lebih mudah dilacak (`checksum_sha256` tidak cocok) daripada file tanpa baris.

Lihat [Backup](../07-deployment/Backup.md).

---

## Validasi

Diperiksa **dua-duanya** — ekstensi *dan* MIME type (`apps/uploads/validators.py`).

> Ekstensi saja tidak cukup: `.pdf` yang isinya executable lolos kalau cuma nama berkasnya yang diperiksa.

| Setting | Nilai |
|---|---|
| `UPLOAD_MAX_FILE_SIZE` | 25 MB |
| `UPLOAD_MAX_MULTIPLE_FILES` | 20 |
| `UPLOAD_ALLOWED_EXTENSIONS` | 16 ekstensi |

Nama file dilewatkan `get_valid_filename()` → `stored_name`; `original_name` menyimpan yang diketik user.

---

## Hard delete, satu-satunya di sistem ini

`POST /api/uploads/<public_id>/purge/`.

Di seluruh codebase penghapusan selalu soft. File pengecualian, karena **byte-nya benar-benar memakan disk** dan retensi file punya aturannya sendiri.

`public_id` (UUID) juga salah satu dari sedikit kolom unik yang **sengaja tidak** dikondisikan ke `is_deleted` — UUID tidak pernah dipakai ulang.

---

## Jebakan: kolom file mematikan pencatatan audit

!!! bug "Tanpa suara"
    `PrintSetting.logo` bertipe `ImageFieldFile`. `_jsonable()` di `BaseService._audit` melempar saat menyerialisasinya, exception-nya **ditelan `except`**, dan tabel audit untuk model itu tetap **nol baris tanpa satu pun pesan**.

    Sudah diperbaiki dengan `DjangoJSONEncoder` + `default=str`. Kalau menambah tipe kolom tidak lazim, periksa jalur ini.

---

## Yang belum ada

- Storage backend selain lokal
- **Eksekusi `expires_at`** — Celery Beat sudah aktif, tinggal tasknya
- Virus scanning
- **Cakupan data** — `UploadedFileViewSet` bukan turunan `BaseMasterViewSet`, jadi `DataScopeService` tidak berlaku; daftarnya disaring `IsAuthenticated` saja
- CDN
