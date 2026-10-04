# Backup Database

Prosedur lengkap (termasuk `media/`, retensi, dan restore) ada di **[Deployment → Backup](../07-deployment/Backup.md)**. Halaman ini hanya bagian database-nya.

---

## Yang khas multi-tenant

Satu database, **banyak schema**. Dua hal yang membedakannya dari backup Django biasa:

### 1 · Schema `public` wajib ikut

`public` memuat `tenants_client` dan `tenants_domain` — **peta schema ke domain**.

!!! danger "Tanpa `public`, schema tenant yang dipulihkan tidak bisa diakses siapa pun"
    Datanya utuh, tapi tidak ada hostname yang mengarah ke sana. Gejalanya terlihat persis seperti databasenya kosong.

    `public` juga memuat jadwal `django_celery_beat`. Kalau hilang, pengingat kepegawaian diam-diam berhenti — dan tidak ada yang menyadarinya sampai ada kontrak yang telat diperpanjang.

### 2 · Restore selektif per tenant mungkin

Skenario yang paling mungkin nyata: satu klien salah menghapus data, yang lain harus tetap jalan.

---

## Perintah

```bash
# Seluruh database — untuk pemulihan bencana
pg_dump -Fc -f meinova-$(date +%F).dump meinova_erp

# Satu tenant + public — untuk restore selektif
pg_dump -Fc -n demo -n public -f demo-$(date +%F).dump meinova_erp
```

`-Fc` (custom format) karena mendukung restore selektif dan kompresi.

### Restore

```bash
# Penuh
createdb meinova_erp
pg_restore -d meinova_erp meinova-2026-08-13.dump

# Satu tenant — MENGHAPUS isi schema itu lebih dulu
pg_restore -d meinova_erp -n demo --clean demo-2026-08-13.dump
```

!!! danger "`--clean -n demo` menghapus isi schema itu"
    Semua yang terjadi di tenant tersebut sejak backup **hilang**. Ambil dump schema itu apa adanya sebelum menimpanya.

---

## Verifikasi setelah restore

- [ ] `SELECT schema_name, name FROM tenants_client;` terisi
- [ ] `SELECT domain, tenant_id FROM tenants_domain;` terisi
- [ ] Jumlah schema = jumlah tenant
- [ ] Login berhasil di **beberapa** tenant, bukan cuma satu
- [ ] Jadwal `django_celery_beat` ada

---

## Soft delete bukan pengganti backup

Seluruh penghapusan lewat UI adalah soft delete, dan `BaseMasterService.restore()` bisa mengembalikannya. Itu melindungi dari **salah hapus satu baris**, bukan dari:

- migrasi yang menghapus kolom
- `reset_demo_data` di tenant yang salah (**hard delete**)
- korupsi database

---

## Sebelum migrasi berisiko

**Dump manual sebelum migrasi yang menghapus atau mengganti nama kolom.**

Migrasi semacam itu tidak punya jalan mundur yang murah — lihat [Migration](Migration.md#rollback).

---

## Yang belum ada

- Backup terjadwal
- Restore yang pernah diuji
- Alert kalau backup gagal
- PITR (WAL archiving)

**Backup yang belum pernah diuji restore bukan backup.**
