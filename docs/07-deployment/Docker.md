# Docker

!!! warning "Belum ada"
    Tidak ada `Dockerfile` maupun `docker-compose.yml` di repo ini. `README.md` menyebut "Docker Ready" — itu **belum benar**.

Halaman ini mencatat apa yang perlu diperhatikan kalau containerisasi dibuat, karena beberapa hal di sistem ini tidak mengikuti pola Django biasa.

---

## Empat proses, bukan satu

| Service | Perintah | Catatan |
|---|---|---|
| `web` | `gunicorn config.wsgi:application` | boleh banyak replika |
| `worker` | `celery -A config worker -l info` | boleh banyak replika |
| `beat` | `celery -A config beat -l --scheduler django_celery_beat.schedulers:DatabaseScheduler` | **tepat satu** |
| `migrate` | `migrate_schemas` | job sekali jalan, bukan service |

!!! danger "Beat hanya boleh satu replika"
    Dua beat = jadwal jalan dua kali. Untuk `hr.dispatch_employee_reminders`, itu berarti pengingat kontrak ganda ke seluruh HR setiap pagi.

---

## Migrasi jangan dijalankan di entrypoint container

Ini yang paling sering salah pada Django multi-tenant.

`migrate_schemas` menyentuh **setiap** schema tenant. Kalau dijalankan di entrypoint:

- setiap replika `web` menjalankannya bersamaan → saling mengunci
- durasinya sebanding jumlah tenant, jadi startup bisa menggantung berpuluh menit
- kegagalan di tenant ke-17 meninggalkan sistem separuh termigrasi, dan container-nya restart lalu mengulang dari awal

Jalankan sebagai **job terpisah** sebelum rollout:

```
1. job migrate  → migrate_schemas --shared && migrate_schemas
2. rollout web, worker, beat
3. job seed     → seed_menus, seed_security_roles, …
```

---

## Yang perlu ada di image

- Python 3.13
- `libpq` untuk psycopg 3
- **`pillow`** butuh library imaging — dipakai `ThumbnailService`
- **`pypdfium2`** untuk `page_count` PDF
- `dbfread` untuk importer absensi

Multi-stage build; jangan bawa `venv/`, `node_modules/`, `media/`, `docs/` ke image runtime.

---

## Volume & state

| | Catatan |
|---|---|
| `media/` | `TenantFileSystemStorage` + `MULTITENANT_RELATIVE_MEDIA_ROOT = "%s"` → file terpisah per schema, tapi **di disk lokal**. Butuh volume bersama, atau pindah ke object storage sebelum ada lebih dari satu replika `web` |
| `staticfiles/` | hasil `collectstatic`, bisa di-bake ke image |
| PostgreSQL, Redis | jangan di-container untuk produksi |

**`media/` adalah penghalang nyata untuk menaikkan replika.** Selama masih filesystem lokal, dua replika `web` akan melayani file yang berbeda-beda.

---

## Environment

Seluruhnya lewat `python-decouple`, jadi env container cukup:

```
SECRET_KEY  DEBUG  ALLOWED_HOSTS
DB_NAME  DB_USER  DB_PASSWORD  DB_HOST  DB_PORT
REDIS_URL  REDIS_CACHE_URL  REDIS_CHANNELS_URL  CELERY_RESULT_BACKEND
MEINOVA_AGENT_API_KEY
DJANGO_SETTINGS_MODULE=config.settings.production
```

!!! warning "`config/celery.py` menetapkan default `config.settings.local`"
    ```python
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.local")
    ```

    `setdefault` berarti env container tetap menang — tapi **kalau lupa menyetelnya, worker jalan dengan settings development** (`DEBUG = True`) tanpa satu pun peringatan. Set eksplisit di semua service.

---

## Networking & tenant

Tenant ditentukan **hostname**, jadi reverse proxy **wajib** meneruskan `Host` asli:

```nginx
proxy_set_header Host $host;
proxy_set_header X-Forwarded-Proto $scheme;
```

Kalau tidak, semua request mendarat di schema `public` dan aplikasinya terlihat kosong total.

Butuh wildcard DNS + wildcard TLS (`*.meinova.id`).

---

## Healthcheck

**Belum ada endpoint health.** Sementara ini bisa `GET /api/schema/` (tidak menyentuh DB tenant), tapi itu bukan pengganti health check sungguhan.

Yang layak dibuat nanti: satu endpoint yang memeriksa DB + Redis dan **tidak** butuh tenant.

---

## Dua repo, dua image

Frontend Nuxt punya image sendiri. Yang perlu diingat: **hasil generate sudah di-commit**, jadi build image FE **tidak** menjalankan `pnpm meinova generate` — ia tidak boleh bergantung pada backend yang hidup saat build.
