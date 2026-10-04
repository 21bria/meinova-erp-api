# Menjalankan di Lokal

Ringkas. Versi lengkap dengan seed dan troubleshooting ada di [Onboarding](../08-development/Onboarding.md).

---

## Prasyarat

Python 3.13+ · PostgreSQL 16+ · Redis 7+ · Node 20+ dengan `pnpm`

---

## Backend

```bash
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # isi DB, Redis, SECRET_KEY

python manage.py migrate_schemas --shared
python manage.py migrate_schemas

python manage.py runserver
```

Settings default `config.settings.local`:

```python
DEBUG = True
ALLOWED_HOSTS = ["localhost", "127.0.0.1", ".localhost", "erp.localhost"]
```

`.localhost` yang membuat subdomain tenant bekerja tanpa menyunting `/etc/hosts` — di macOS dan sebagian besar Linux, `*.localhost` sudah resolve ke `127.0.0.1`.

---

## Tenant

Aplikasi **tidak bisa dipakai tanpa tenant.** `http://localhost:8000` mendarat di schema `public` yang tidak punya satu pun tabel bisnis.

```python
from apps.tenants.models import Client, Domain

client = Client.objects.create(schema_name="demo", name="Demo")
Domain.objects.create(domain="demo.localhost", tenant=client, is_primary=True)
```

Sesudah itu: **`http://demo.localhost:8000`**, bukan `localhost:8000`.

---

## Proses yang perlu jalan

| Proses | Perintah | Perlu kapan |
|---|---|---|
| Web | `python manage.py runserver` | selalu |
| Worker | `celery -A config worker -l info` | import file, task async |
| Beat | `celery -A config beat -l info --scheduler django_celery_beat.schedulers:DatabaseScheduler` | jarang di lokal |

!!! warning "Restart worker setelah menambah/mengubah importer"
    Registry diisi saat `AppConfig.ready()`. Worker lama tidak mengenal importer baru dan job-nya gagal `No importer registered for module '...'`.

Beat memakai `DatabaseScheduler` — jadwalnya di tabel di **public schema**, satu penjadwal melayani semua tenant. Di lokal biasanya tidak perlu dijalankan; kalau mau menguji task terjadwal, panggil perintahnya langsung:

```bash
python manage.py tenant_command send_employee_reminders --schema=demo
```

---

## Frontend

```bash
cd ~/Project/nuxt/meinova-erp
pnpm install
pnpm dev
```

`MEINOVA_API_BASE_URL` default `http://demo.localhost:8000` — cocok dengan tenant di atas.

!!! warning "Rute baru butuh restart dev server"
    Nuxt tidak selalu menangkap halaman yang dibuat proses lain saat `pnpm dev` sudah berjalan; rutenya 404 sampai server dijalankan ulang, walau berkasnya ada dan build-nya lolos.

---

## Dokumentasi

```bash
mkdocs serve -a 127.0.0.1:8001
```

---

## Yang berbeda dari produksi

| | Lokal | Produksi |
|---|---|---|
| `DEBUG` | `True` | `False` |
| Media | dilayani Django (`if settings.DEBUG`) | **belum diatur** — lihat [Production](Production.md) |
| Static | `runserver` | `collectstatic` + web server |
| CORS | terbuka | **masih terbuka juga** — `CORS_ALLOW_ALL_ORIGINS = True` di `base.py` dan tidak di-override |

Baris terakhir itu utang teknis yang diketahui, bukan perbedaan yang disengaja.

---

## Troubleshooting

| Gejala | Sebab |
|---|---|
| Semua endpoint 404 / admin kosong | membuka `localhost:8000`, bukan `demo.localhost:8000` |
| `relation "..." does not exist` | `migrate_schemas` (tanpa `--shared`) belum jalan |
| `Related model 'administration.site' cannot be resolved` | migrasi tanpa `run_before` — lihat [Migration](../06-database/Migration.md) |
| Sidebar kosong setelah login | `seed_menus` belum jalan |
| Semua tombol tulis 403 | `seed_security_roles` belum jalan |
| Import job gagal `No importer registered` | restart worker Celery |
| Halaman baru 404 | restart `pnpm dev` |

Daftar lengkapnya di [Onboarding](../08-development/Onboarding.md#troubleshooting-hari-pertama).
