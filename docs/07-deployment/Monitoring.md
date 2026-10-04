# Monitoring

!!! danger "Logging belum dikonfigurasi sama sekali"
    `config/settings/logging.py` **kosong**, dan tidak ada `LOGGING` di `base.py`.

    Ini bukan kekurangan kenyamanan. Beberapa jalur di sistem ini **sengaja menelan exception dan hanya mencatat log** — tanpa logging terkonfigurasi, kegagalannya hilang total dan tidak ada yang tahu.

---

## Yang hilang tanpa logging

Jalur-jalur ini dirancang untuk **tidak** menggagalkan operasi utamanya. Semuanya melapor lewat `logger`, dan tidak ada tempat lain:

| Jalur | Yang ditelan | Akibat kalau tidak terpantau |
|---|---|---|
| `BaseService._audit` | kegagalan pencatatan audit | perubahan tercatat di tabel, jejaknya tidak — dan tidak ada yang tahu jejaknya bolong |
| `EmploymentService.sync_leave_balances` | kegagalan penerbitan saldo | pegawai baru tanpa saldo cuti, tanpa sebab yang terlihat |
| `AttendanceEmployeeMatcher.names_match` | nama tidak cocok saat sync | **nomor salah enroll menempel ke karyawan lain** — pernah terjadi di produksi, 1.326 tap |
| `SafeSearchFilter` | field pencarian tak dikenal | pencarian diam-diam tidak mencari apa yang diharapkan |
| `WorkflowStep.condition` yang tidak bisa dinilai | | step approval berjalan padahal seharusnya dilewati (atau sebaliknya) |
| `issue_leave_records` bentrokan beda jenis | | catatan cuti tidak terbit dari TR yang sudah disetujui |
| Registry `@register_completion` didaftarkan dua kali | | handler yang belakangan menang, diam-diam |

**Baris ketiga yang paling mahal.** Verifikasi nama sengaja jadi alarm, bukan gerbang — absensi tidak boleh hilang gara-gara ejaan nama. Tapi alarm yang tidak ada yang mendengarnya sama saja dengan tidak ada alarm.

---

## Konfigurasi logging minimum

```python
# config/settings/logging.py
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "verbose": {
            "format": "{asctime} {levelname} {name} {message}",
            "style": "{",
        },
    },
    "handlers": {
        "console": {"class": "logging.StreamHandler", "formatter": "verbose"},
    },
    "root": {"handlers": ["console"], "level": "INFO"},
    "loggers": {
        "apps": {"handlers": ["console"], "level": "INFO", "propagate": False},
        "django.request": {"handlers": ["console"], "level": "WARNING", "propagate": False},
        "celery": {"handlers": ["console"], "level": "INFO", "propagate": False},
    },
}
```

Lalu `from .logging import *` di `base.py` — berkasnya sudah ada, tinggal diisi.

Console handler cukup kalau container-nya sudah mengumpulkan stdout. Yang penting **logger `apps` tidak tersaring**.

!!! warning "Tanpa request ID, log tidak bisa dikaitkan ke kejadian di layar"
    `apps/core/middleware/request_id.py` masih file kosong dan tidak terdaftar di `MIDDLEWARE`.

    Untuk multi-tenant, log juga sebaiknya membawa **schema tenant** — tanpa itu "ada error di jam 9" tidak memberi tahu klien mana.

---

## Yang perlu dipantau

### Aplikasi

| Metrik | Kenapa |
|---|---|
| Error rate per status (4xx vs 5xx) | 500 di sini biasanya berarti `search_fields` salah atau `ordering` menyebut kolom tak ada |
| Latensi endpoint list | kolom relasi tanpa `select_related` menghasilkan N+1 yang tumbuh seiring data |
| `/api/framework/schema/` | dipanggil generator, seharusnya jarang di produksi — lonjakan berarti ada yang men-scrape struktur |

### Celery

| Metrik | Kenapa |
|---|---|
| Panjang antrean | import besar bisa menahan antrean lama |
| Task gagal | `No importer registered` = worker belum direstart setelah deploy |
| **Beat hidup dan hanya satu** | dua beat = pengingat kontrak ganda ke seluruh HR tiap pagi |

`flower` sudah ada di `requirements.txt` — pemantau Celery paling murah untuk dipasang.

### Database

Koneksi, query lambat, ukuran per schema. Yang terakhir khas multi-tenant: **satu tenant besar bisa mendominasi**, dan itu tidak terlihat dari metrik agregat.

---

## Yang layak dibuat alert

Bukan sekadar dashboard — hal-hal yang butuh tindakan:

- [ ] Beat mati, atau lebih dari satu instance
- [ ] Task Celery gagal berturut-turut
- [ ] Lonjakan 500
- [ ] `name_warning_records` > 0 pada sync absensi → **ada nomor pegawai salah enroll di mesin fingerprint**
- [ ] Job import yang mengendap di status berjalan
- [ ] Backup gagal

Baris keempat spesifik untuk sistem ini dan tidak akan muncul di template monitoring mana pun.

---

## Audit trail sebagai alat investigasi

`AuditTrail` mencatat **siapa mengubah apa** (hanya kolom yang berubah), termasuk soft delete — dan soft delete justru tindakan yang paling perlu dijawab "siapa yang menghapus ini".

Batasnya harus disadari saat memakainya untuk investigasi:

- **Viewset tanpa `ServiceWriteMixin` tidak masuk audit sama sekali.** Cakupannya = daftar viewset ber-mixin, bukan seluruh sistem.
- **Yang tanpa pengguna terautentikasi tidak dicatat** — seed, importer, management command.
- **Login/logout tidak dicatat.**

Jadi "tidak ada di audit trail" **bukan** bukti sesuatu tidak terjadi.

---

## Yang belum ada

- `LOGGING` (paling mendesak)
- Request ID + schema tenant di log
- Error tracking (Sentry)
- APM
- Health check endpoint
- `prometheus_client` ada di `requirements.txt` tapi **belum dipakai**
