# CI / CD

!!! warning "Belum ada"
    Tidak ada `.github/` di repo ini. Seluruh test, migrasi, dan deploy dijalankan manual.

Halaman ini menetapkan pipeline yang **akan** dipakai, dan — lebih penting — menjelaskan kenapa deploy sistem ini tidak boleh sepenuhnya otomatis.

---

## Kenapa deploy tidak boleh sepenuhnya otomatis

Tiga hal yang membedakannya dari aplikasi Django biasa:

1. **`migrate_schemas` menyentuh setiap tenant.** Durasinya sebanding jumlah tenant, dan kegagalan di tenant ke-17 meninggalkan sistem separuh termigrasi. Itu keputusan yang perlu diawasi orang, bukan langkah yang berjalan diam-diam saat container start.
2. **Sebagian rilis butuh seed satu kali** yang tidak bisa disimpulkan dari diff — lihat [Release](../08-development/Release.md#rilis-yang-butuh-seed-satu-kali).
3. **Dua repo harus dirilis berurutan.** Backend dulu; frontend yang lebih baru dengan backend lama memanggil endpoint yang belum ada.

Yang **boleh** otomatis: pemeriksaan (CI). Yang harus dipicu orang: migrasi dan rollout (CD).

---

## CI — tahap yang layak dipasang

Urutan dari yang paling berharga per satuan usaha:

### Tahap 1 — pemeriksaan murah

```yaml
- python manage.py makemigrations --check --dry-run
- python manage.py check
```

`makemigrations --check` menangkap kesalahan yang paling sering lolos: **model diubah tapi migrasinya lupa di-commit.** Gejalanya baru muncul di mesin orang lain.

### Tahap 2 — test

```yaml
services: [postgres:16, redis:7]
steps:
  - python manage.py test --keepdb
```

Butuh PostgreSQL sungguhan — django-tenants memakai schema, tidak jalan di SQLite.

Cakupan hari ini masih tipis (`apps/hr/tests/roster/` dan `apps/hr/tests/policy/`), tapi dua berkas `SimpleTestCase` di antaranya menjaga properti yang berharga: **kalkulator roster tidak boleh menyentuh database.** Begitu ada yang menambahkan query, CI yang gagal.

### Tahap 3 — replay migrasi dari nol

```yaml
- createdb ci_fresh
- python manage.py migrate_schemas --shared
- # buat tenant baru → migrate_schemas
```

Ini yang akan menangkap bug kelas `run_before`: empat migrasi pernah menambah FK ke `administration.Site` (model yang direname) tanpa menyatakan urutannya, dan **penyediaan tenant baru gagal** — tapi hanya di database kosong, jadi tidak pernah terlihat di mesin developer yang databasenya sudah lama.

Tahap ini yang paling spesifik untuk repo ini dan paling sulit ditemukan tanpa otomasi.

### Tahap 4 — frontend

```yaml
- pnpm install --frozen-lockfile
- pnpm typecheck
- pnpm lint
- pnpm build
```

!!! warning "Build lolos bukan bukti halamannya jalan"
    `<SelectItem value="">` melempar saat **hidrasi di browser**, bukan saat SSR — `nuxi build` lolos dan `curl` membalas 200 walau halamannya rusak.

    Kalau nanti ada smoke test, ia harus memuat halaman di browser sungguhan (Playwright), bukan sekadar mengambil HTML-nya.

### Tahap 5 — dokumentasi

```yaml
- mkdocs build --strict
```

Murah, dan menangkap link serta anchor rusak. `--strict` sudah lolos hari ini — jaga supaya tetap begitu.

---

## Yang TIDAK boleh dijalankan CI

- **Seed apa pun ke database sungguhan**
- **`reset_demo_data`** — ia menghapus data
- **`migrate_schemas` ke produksi** sebagai bagian dari build

---

## CD — bentuk yang cocok

```
[manual trigger]
   ↓
1. job migrate      migrate_schemas --shared && migrate_schemas
   ↓ (berhenti kalau gagal)
2. rollout backend  web, worker, beat
   ↓
3. job seed         perintah dari deskripsi PR
   ↓
4. rollout frontend
   ↓
5. verifikasi manual
```

Langkah 3 tidak bisa dibuat generik: perintahnya berbeda tiap rilis dan **tidak bisa disimpulkan dari diff**. Itu sebabnya template PR punya bagian "Seed yang harus dijalankan setelah deploy".

Langkah 5 juga tidak bisa dihapus — beberapa kegagalan di sistem ini (kolom "-", prop hantu, filter yang tidak menyaring) tidak menghasilkan error apa pun.

---

## Secret yang dibutuhkan

`SECRET_KEY`, kredensial DB, `MEINOVA_AGENT_API_KEY`, kredensial registry.

Yang **tidak** boleh ada di CI: kredensial produksi untuk tahap test. Tahap test memakai database sekali pakai.

---

## Prioritas kalau mulai hari ini

1. `mkdocs build --strict` + `makemigrations --check` — dua baris, langsung berguna
2. `python manage.py test --keepdb`
3. Replay migrasi dari nol
4. Frontend typecheck + build
5. Branch protection pada `main`
