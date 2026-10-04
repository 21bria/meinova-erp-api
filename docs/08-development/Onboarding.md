# Onboarding — Hari Pertama

Dari repo kosong sampai bisa login dan melihat data. Ikuti berurutan; melompati langkah seed hampir selalu berakhir di layar kosong yang tidak jelas sebabnya.

---

## Prasyarat

| | Versi |
|---|---|
| Python | 3.13+ |
| PostgreSQL | 16+ |
| Redis | 7+ |
| Node | 20+ dengan `pnpm` |

---

## 1 · Backend

```bash
git clone <repo> backend-erp && cd backend-erp

python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env      # lalu isi sesuai di bawah
```

`.env` yang dibaca:

| Key | Isi |
|---|---|
| `SECRET_KEY` | rahasia Django |
| `DEBUG` | `True` di lokal |
| `ALLOWED_HOSTS` | wajib memuat `.localhost` untuk subdomain tenant |
| `DB_NAME`, `DB_USER`, `DB_PASSWORD`, `DB_HOST`, `DB_PORT` | PostgreSQL |
| `REDIS_URL` | `/0` — Celery broker |
| `REDIS_CACHE_URL` | `/1` — Django cache |
| `REDIS_CHANNELS_URL` | `/2` — Channels (masih dikomentari) |
| `CELERY_RESULT_BACKEND` | `/3` |
| `MEINOVA_AGENT_API_KEY` | key untuk agent absensi on-premise |
| `ENFORCE_MODEL_PERMISSIONS` | bawaan `True` |
| `DATA_SCOPE_INCLUDE_NULL` | bawaan `False` |

!!! danger "Jangan campur Redis DB index"
    Empat keperluan, empat index. Mencampurnya membuat hasil task Celery tertimpa cache Django dan gagalnya sangat sulit dilacak.

Settings default `config.settings.local`.

---

## 2 · Migrasi — dua perintah, bukan `migrate`

Ini pakai **django-tenants**. `python manage.py migrate` biasa **tidak cukup**.

```bash
python manage.py migrate_schemas --shared     # SHARED_APPS → public schema
python manage.py migrate_schemas              # semua tenant schema
python manage.py migrate_schemas --schema=demo  # satu tenant saja
```

| | Isinya |
|---|---|
| `SHARED_APPS` | cuma `tenants` + contrib + corsheaders |
| `TENANT_APPS` | **semua app bisnis** |

App baru masuk `TENANT_APPS`, bukan `SHARED_APPS`.

---

## 3 · Tenant

```bash
python manage.py shell
```

```python
from apps.tenants.models import Client, Domain

client = Client.objects.create(schema_name="demo", name="Demo")
Domain.objects.create(domain="demo.localhost", tenant=client, is_primary=True)
```

Sesudah ini semua request ke `http://demo.localhost:8000` masuk ke schema `demo`.

```bash
python manage.py createsuperuser   # atau tenant_command kalau perlu per-schema
```

---

## 4 · Seed berurutan

**Urutan ini penting.** Tiap seed bergantung pada yang di atasnya.

```bash
SCHEMA=demo

# ── Master dasar ────────────────────────────────────────
python manage.py tenant_command seed_administration --only=organization-reference --schema=$SCHEMA
python manage.py tenant_command seed_administration --only=organization          --schema=$SCHEMA
python manage.py tenant_command seed_administration --only=geography             --schema=$SCHEMA
python manage.py tenant_command seed_administration --only=bank                  --schema=$SCHEMA
python manage.py tenant_command seed_administration --only=bank-branch           --schema=$SCHEMA
python manage.py tenant_command seed_administration --only=currency              --schema=$SCHEMA
python manage.py tenant_command seed_administration --only=numbering             --schema=$SCHEMA
python manage.py tenant_command seed_administration --only=calendar              --schema=$SCHEMA
python manage.py tenant_command seed_administration --only=hr-reference          --schema=$SCHEMA

# ── HR & payroll ────────────────────────────────────────
python manage.py tenant_command seed_hr_attendance   --schema=$SCHEMA
python manage.py tenant_command seed_payroll         --schema=$SCHEMA
python manage.py tenant_command seed_leave_policy    --schema=$SCHEMA
python manage.py tenant_command seed_roster_policy   --schema=$SCHEMA
python manage.py tenant_command seed_employee_action_policy --schema=$SCHEMA
python manage.py tenant_command seed_employee_data_policy   --schema=$SCHEMA

# ── Keamanan, menu, workflow ────────────────────────────
python manage.py tenant_command seed_menus           --schema=$SCHEMA
python manage.py tenant_command seed_security_roles  --schema=$SCHEMA
python manage.py tenant_command seed_workflows       --schema=$SCHEMA
python manage.py tenant_command seed_dashboard       --schema=$SCHEMA
python manage.py tenant_command seed_import_profiles --schema=$SCHEMA
```

Seluruhnya **aman diulang**.

!!! warning "Tiga seed yang sering terlupa, dan akibatnya"
    | Lupa | Akibatnya |
    |---|---|
    | `--only=calendar` | `WorkCalendar` dan `Holiday` kosong → perhitungan hari cuti jatuh ke fallback Senin–Jumat dan hari libur nasional ikut memotong saldo |
    | `--only=currency` | tidak ada mata uang dasar → import payroll menolak baris penempatan gaji, dan gagalnya jauh dari sumbernya |
    | `--only=numbering` | dokumen tersimpan dengan **nomor kosong** — sengaja tidak melempar, tapi TR tanpa nomor tidak bisa dicetak |

!!! danger "`seed_security_roles` harus jalan SEBELUM penjagaan izin berlaku"
    Menyalakan `ENFORCE_MODEL_PERMISSIONS` di tenant yang role-nya kosong membuat seluruh sistem **read-only kecuali superuser**.

    Seed itu mengisi matriks awal, memberi `SYSTEM-ADMIN` ke semua superuser, dan memberi role dasar `EMPLOYEE` ke akun yang belum punya role sama sekali — tanpa yang terakhir, pegawai biasa kehilangan kemampuan mengajukan cutinya sendiri.

    Aman diulang: izin **ditambahkan**, tidak pernah dicabut.

---

## 5 · Data uji

Untuk melihat sistemnya bekerja dengan data yang masuk akal:

```bash
SCHEMA=demo

python manage.py tenant_command reset_demo_data      --schema=$SCHEMA   # bersihkan dulu
python manage.py tenant_command seed_workflows       --schema=$SCHEMA
python manage.py tenant_command seed_demo_workforce  --schema=$SCHEMA
python manage.py tenant_command seed_roster_demo     --schema=$SCHEMA
python manage.py tenant_command seed_site_travel_demo --schema=$SCHEMA
python manage.py tenant_command seed_workflow_demo   --schema=$SCHEMA
python manage.py tenant_command generate_leave_balances --year=2026 --schema=$SCHEMA
python manage.py tenant_command seed_employee_action_demo --schema=$SCHEMA
python manage.py tenant_command seed_demo_attendance --schema=$SCHEMA
python manage.py tenant_command seed_data_scopes     --schema=$SCHEMA   # opsional
```

!!! danger "Urutannya bukan selera"
    - **`seed_roster_demo` sebelum `seed_site_travel_demo`**: ia membangun ulang seluruh periode roster, dan Travel Request yang sudah menunjuk salah satu blok off akan menunjuk baris yang tidak ada lagi.
    - **`seed_demo_attendance` paling akhir**: hari kerja pegawai site diturunkan dari baris `RotationPeriod` yang berlaku, jadi menjalankannya sebelum rosternya terbit menghasilkan nol baris untuk seluruh site.

Isinya: **11 pegawai** — 4–5 kantor pusat Jakarta (`HO001`–) dan 6 site Gebe (`GBE001`–), lengkap dengan garis pelaporan, akun approver, dan dokumen rosternya.

- Password seluruh akun uji: **`<DEMO_PASSWORD>`** — diambil dari variabel lingkungan `DEMO_PASSWORD` dan dipasang ulang tiap seed supaya tiap meja bisa dicoba login sendiri. Tanpa variabel itu seed berhenti; tidak ada password bawaan.
- Nomor pegawainya berawalan `HO`/`GBE`, bukan meniru pola klien — data uji harus bisa dibedakan sekilas dan tidak boleh bertabrakan saat file master klien diimpor.
- Tanggal masuknya sengaja **berjenjang** supaya keempat cabang aturan jatah cuti terlewati.

`seed_demo_workforce` adalah **pemilik tunggal** nomor pegawai, jabatan, department, section, akun, role, dan garis pelaporan. Seed skenario lain hanya **mencari** orangnya lalu menjalankan dokumen.

Cetak rekap roster: `tenant_command report_rotation_cycles`.

---

## 6 · Jalankan

```bash
python manage.py runserver
celery -A config worker -l info          # terminal terpisah
```

| URL | Isi |
|---|---|
| `http://demo.localhost:8000/api/docs/` | Swagger |
| `http://demo.localhost:8000/api/schema/` | OpenAPI |
| `http://demo.localhost:8000/admin/` | Django admin |

!!! warning "Restart worker Celery setelah menambah/mengubah importer"
    Registry diisi saat `AppConfig.ready()`, jadi worker yang sudah lama jalan tidak mengenal importer baru dan job-nya gagal dengan `No importer registered for module '...'`.

---

## 7 · Frontend

```bash
cd ~/Project/nuxt/meinova-erp
pnpm install
pnpm dev
```

Base URL API diambil dari `MEINOVA_API_BASE_URL` (default `http://demo.localhost:8000`).

Regenerate satu module:

```bash
pnpm meinova generate hr/employees
```

Baca [Pipeline BE → FE](../02-Framework/BE-to-FE-Pipeline.md) sebelum menyentuh apa pun di `app/modules/`.

---

## 8 · Test

```bash
python manage.py test apps.hr.tests.roster --keepdb
```

!!! warning "`--keepdb` bukan opsional"
    Tiap `TenantTestCase` membuat schema tenant sendiri lewat `migrate_schemas`, jadi sekali jalan **~4 menit** tanpa itu.

Test baru ada di satu tempat: `apps/hr/tests/roster/`. Sisanya masih `tests.py` kosong.

Empat berkasnya, dan pembagiannya disengaja:

| Berkas | Jenis | Catatan |
|---|---|---|
| `test_rotation_generator.py` | `SimpleTestCase` | **tidak menyentuh database sama sekali** |
| `test_roster_calculation.py` | `SimpleTestCase` | idem — kedua kalkulator memang fungsi murni, dan itu properti yang harus dijaga |
| `test_leave_day_calculator.py` | `TenantTestCase` | |
| `test_roster_flow.py` | `TenantTestCase` | |

Begitu ada yang menambahkan query ke kalkulator, dua berkas pertama yang pertama gagal — itu memang gunanya.

!!! note "`TenantTestCase` tidak memanggil `super().setUpClass()`"
    Jadi **tidak ada rollback per-test** dan `setUpTestData` tidak jalan. Tiap test harus membuat pegawainya sendiri dan hanya membaca miliknya.

---

## 9 · Dokumentasi

```bash
pip install mkdocs mkdocs-material
mkdocs serve -a 127.0.0.1:8001
```

---

## Troubleshooting hari pertama

| Gejala | Sebab yang paling mungkin |
|---|---|
| `Related model 'administration.site' cannot be resolved` saat membuat tenant | migrasi yang menyentuh model hasil rename tanpa `run_before` |
| Layar kosong, tabel bilang "No results." tanpa error | `endpoint` tidak dideklarasikan di schema → generator menurunkannya dari `framework_module` dan mendarat di URL yang tidak ada |
| Kolom "-" di semua baris | serializer `fields = "__all__"`, kolomnya mencari `<relasi>_name` |
| HTTP 500 saat mengetik di kotak cari | `search_fields` menyebut kolom yang tidak ada di model |
| Tombol Save ditekan, tidak terjadi apa-apa | 403 yang tidak dilaporkan; cek Network tab |
| Semua tombol tulis 403 | `seed_security_roles` belum dijalankan |
| Sidebar kosong / menu hilang setelah login | `seed_menus` belum dijalankan, atau role dibatasi tanpa baris menu yang benar |
| Dropdown selalu kosong | registry lookup belum di-import dari `AppConfig.ready()`, atau parameter tidak terdaftar di `filter_fields` |
| Halaman baru 404 walau berkasnya ada | restart `pnpm dev` |
| Import job gagal `No importer registered` | restart worker Celery |
| Jam absensi tergeser +7 | selisih `TIME_ZONE` UTC vs render `date.getHours()` — [utang teknis yang diketahui](#utang-teknis-yang-perlu-diketahui) |

---

## Utang teknis yang perlu diketahui

Bukan untuk diperbaiki hari pertama, tapi jangan kaget menemukannya:

- **`CORS_ALLOW_ALL_ORIGINS = True`** di `base.py` dan tidak di-override di `production.py`.
- **`production.py` praktis kosong** (cuma `DEBUG = False`) — belum ada hardening security setting.
- **`config/settings/cache.py`, `email.py`, `logging.py` masih kosong.**
- **Middleware custom di `apps/core/middleware/`** (audit, request_id, timezone, exception) sebagian besar file kosong dan tidak terdaftar di `MIDDLEWARE`. Yang sudah jalan cuma `CurrentRequestMiddleware`.
- **Celery Beat aktif, tapi baru satu jadwal.** `django_celery_beat` ada di `SHARED_APPS` dengan `DatabaseScheduler`, dan `hr.dispatch_employee_reminders` jalan tiap jam 6 pagi. Yang belum dijadwalkan: notifikasi H-7 travel request, rolling horizon roster, pembersihan file kedaluwarsa.
- **Timezone**: `TIME_ZONE` proyek UTC, sementara frontend merender dengan `date.getHours()` (jam browser), jadi data absensi hasil import tergeser +7 jam di layar. Belum diperbaiki — memperbaikinya berarti memutuskan apakah yang bergerak `TIME_ZONE`, importer, atau perendernya.
