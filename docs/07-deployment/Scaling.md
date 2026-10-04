# Scaling

Apa yang jadi penghalang lebih dulu, dan kenapa. Ditulis dari struktur sistem yang ada, bukan dari template kapasitas.

---

## Empat penghalang, berurutan

| # | Penghalang | Kapan terasa | Sulitnya |
|---|---|---|---|
| 1 | **`media/` di disk lokal** | begitu replika `web` lebih dari satu | sedang |
| 2 | **N+1 query di endpoint list** | sudah terasa sekarang di tabel berkolom relasi banyak | mudah |
| 3 | **`migrate_schemas` lama** | begitu tenant lebih dari ~20 | operasional |
| 4 | **`COUNT(*)` pada pagination** | tabel jutaan baris | belum mendesak |

---

## 1 · `media/` — penghalang pertama untuk horizontal scaling

`TenantFileSystemStorage` + `MULTITENANT_RELATIVE_MEDIA_ROOT = "%s"` menyimpan file **di disk lokal**, terpisah per schema.

Selama itu, dua replika `web` melayani file yang berbeda-beda: upload mendarat di satu replika, permintaan unduhnya bisa jatuh ke replika lain yang tidak punya filenya.

Jalan keluar, dari yang paling murah:

1. Volume bersama (NFS) — cepat dipasang, jadi penghalang I/O sendiri nanti
2. Object storage (S3/GCS) — `config/settings/storage.py` sudah jadi tempatnya; perlu backend yang tetap memisahkan per schema

**Ini yang harus diselesaikan lebih dulu** kalau replika `web` perlu ditambah.

---

## 2 · N+1 query — sudah terasa sekarang, dan paling mudah diperbaiki

Satu tabel 20 baris dengan 5 kolom FK yang lupa di-`select_related` menjalankan **101 query**.

Pola yang berulang di repo ini:

| Kasus | Yang dibutuhkan |
|---|---|
| Kolom `<relasi>_name` di tabel | `select_related` |
| Kepala Travel Request (department, section, position, point of hire) | `select_related` — **wajib**, kalau tidak daftar dokumen menambah beberapa query per baris |
| `build_schedule_warnings` membaca periode + travel | `prefetch_related("periods__travels")` — tanpa itu **satu query per periode** |
| `SiteRotationSerializer.leave_balances` | prefetch, lalu disaring **di Python** — jangan diubah jadi query per baris |
| Donut Approval Status | `Count("id", distinct=True)` — `visible_instances` menyaring lewat join, jadi dokumen bertiga kotak tanda tangan terhitung tiga kali. `.distinct()` pada queryset **tidak** menolong setelah `values().annotate()` |

!!! tip "Cara menemukannya"
    Buka endpoint list dengan `DEBUG=True` dan hitung query. Kalau jumlahnya tumbuh sebanding jumlah baris, ada relasi yang belum di-prefetch.

Ini perbaikan termurah dengan dampak terbesar di sistem ini hari ini.

---

## 3 · `migrate_schemas` — penghalang operasional, bukan performa

Durasinya sebanding **jumlah tenant**. Untuk 50 tenant, satu migrasi sederhana bisa berpuluh menit.

Konsekuensinya:

- Migrasi **tidak boleh** jalan di entrypoint container
- Jendela deploy tumbuh seiring pertumbuhan pelanggan
- Kegagalan di tenant ke-17 meninggalkan sistem separuh termigrasi

Yang bisa dilakukan: `migrate_schemas --executor=multiprocessing`, dan menghindari migrasi yang menulis ulang tabel besar (tambah kolom nullable dulu, isi belakangan, baru ketatkan).

---

## 4 · Pagination `COUNT(*)`

`StandardPagination` menjalankan `COUNT(*)` penuh tiap halaman. Untuk tabel jutaan baris itu jadi bagian termahal dari request.

Belum mendesak. Kalau nanti perlu: kelas pagination terpisah untuk layar yang tidak butuh total, **bukan** mengubah `StandardPagination` yang sudah dipakai semua orang.

---

## Yang sudah siap di-scale

**Celery worker.** Konfigurasinya memang dipilih untuk itu:

```python
CELERY_TASK_ACKS_LATE = True
CELERY_TASK_REJECT_ON_WORKER_LOST = True
CELERY_WORKER_PREFETCH_MULTIPLIER = 1
```

Task di sini panjang (import ribuan baris absensi) dan tidak boleh hilang saat worker mati. `prefetch_multiplier = 1` mencegah satu worker menimbun task yang tidak sempat ia kerjakan.

!!! danger "Beat tetap tepat satu"
    Berapa pun worker ditambah, `celery beat` hanya boleh satu instance. Dua beat = `hr.dispatch_employee_reminders` jalan dua kali = pengingat kontrak ganda ke seluruh HR setiap pagi.

---

## Batas yang sengaja dipasang di kode

Bukan penghalang scaling — ini pagar yang mencegah satu request meminta pekerjaan tak terbatas:

| Batas | Nilai | Di mana |
|---|---|---|
| `MAX_PAGE_SIZE` | 100 | `apps/core/constants` |
| `MAX_HORIZON_MONTHS` | 24 | `RosterCalculationService` |
| `MAX_SEGMENTS_PER_PLAN` | 400 | idem |
| `MAX_SETUP_LINES` | 200 | `RosterSetupService` |
| `UPLOAD_MAX_MULTIPLE_FILES` | 20 | settings |
| Kedalaman rantai delegasi | 5 | `WorkflowDelegation` |

Batas roster ada **di dalam kalkulator**, bukan di viewset — supaya query param yang salah ketik tidak bisa memintanya membuat roster tak hingga.

---

## Isolasi tenant

Satu tenant besar bisa mendominasi CPU database dan memperlambat yang lain. Itu sifat shared multi-tenant, dan jawabannya sudah ada di model deployment: **klien enterprise dijalankan dedicated/on-premise dari codebase yang sama.**

Jadi pertanyaannya bukan "bagaimana mengisolasi di dalam satu instance", melainkan **kapan sebuah klien dipindahkan ke instance sendiri**. Sinyalnya: ukuran schema-nya dominan, atau jendela migrasinya sudah mengganggu klien lain.

---

## Yang perlu diukur dulu

Sebelum mengoptimasi apa pun:

- [ ] Query per request di endpoint list yang paling sering dibuka
- [ ] Ukuran per schema
- [ ] Durasi `migrate_schemas`
- [ ] Panjang antrean Celery saat import besar

Ketiga metrik pertama belum diukur sama sekali — lihat [Monitoring](Monitoring.md).
