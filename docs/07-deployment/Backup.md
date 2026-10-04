# Backup

!!! danger "Belum ada backup terjadwal"
    Tidak ada script, tidak ada cron, tidak ada prosedur restore yang pernah diuji.

Halaman ini menetapkan apa yang perlu di-backup dan — yang lebih sering dilupakan — **apa yang tidak bisa dipulihkan dari backup database saja**.

---

## Tiga hal yang perlu di-backup

| # | Apa | Kalau hilang |
|---|---|---|
| 1 | **PostgreSQL** | semuanya |
| 2 | **`media/`** | seluruh lampiran, foto, dokumen kontrak |
| 3 | **`.env`** | kredensial — tapi `SECRET_KEY` yang hilang juga membatalkan seluruh token JWT yang beredar |

Redis **tidak** perlu di-backup: broker Celery dan cache, keduanya bisa dibangun ulang. Pengecualian kecil — jadwal Celery Beat ada di **PostgreSQL** (`DatabaseScheduler`), jadi sudah tercakup backup DB.

---

## PostgreSQL

Satu database, **banyak schema** — satu per tenant plus `public`.

```bash
# seluruh database — yang benar untuk pemulihan bencana
pg_dump -Fc -f meinova-$(date +%F).dump meinova_erp

# satu tenant — untuk restore selektif
pg_dump -Fc -n demo -f demo-$(date +%F).dump meinova_erp
```

!!! warning "Backup per-schema saja tidak cukup"
    Schema `public` memuat `tenants_client` dan `tenants_domain` — **peta schema ke domain**. Tanpa itu, schema tenant yang dipulihkan tidak bisa diakses siapa pun: tidak ada hostname yang mengarah ke sana.

    Backup `public` **bersama** setiap backup tenant, atau selalu backup seluruh database.

`-Fc` (custom format) karena ia mendukung restore selektif dan kompresi.

---

## `media/`

`TenantFileSystemStorage` dengan `MULTITENANT_RELATIVE_MEDIA_ROOT = "%s"` → satu direktori per schema.

```
media/
├── demo/
├── klien_a/
└── klien_b/
```

Ini yang bikin restore per-tenant mungkin: direktori tenant bisa disalin sendirian.

!!! danger "File tidak konsisten dengan DB kalau di-backup terpisah"
    `UploadedFile` menyimpan metadata (checksum, ukuran, versi) di DB, byte-nya di disk. Backup DB jam 02:00 dan backup file jam 03:00 menghasilkan baris DB yang menunjuk file yang belum ada, atau file yatim.

    Kalau selisih itu tidak bisa dihindari, **backup file lebih dulu** — baris DB yang menunjuk file hilang lebih mudah dilacak (`checksum_sha256` tidak cocok) daripada file tanpa baris.

---

## Retensi

Yang perlu dipertimbangkan, karena data HR punya nilai historis panjang:

| Jenis | Saran |
|---|---|
| Harian | 7 hari |
| Mingguan | 4 minggu |
| Bulanan | 12 bulan |
| Tahunan | sesuai kewajiban penyimpanan dokumen kepegawaian |

Baris terakhir bukan pilihan teknis. Riwayat kontrak, penggajian, dan dokumen kepegawaian punya kewajiban retensi tersendiri — dan sistem ini memang **menyimpan riwayat, bukan menimpanya** (`EmployeeAction`, `PayrollAssignment` effective-dated, `RotationPeriod` berversi).

---

## Yang sering dilupakan: soft delete bukan pengganti backup

Seluruh penghapusan di sistem ini soft — barisnya masih ada dengan `is_deleted=True`, dan `BaseMasterService.restore()` bisa mengembalikannya.

Itu **melindungi dari salah hapus satu baris**, bukan dari:

- migrasi yang menghapus kolom
- `reset_demo_data` yang dijalankan di tenant yang salah (ia **hard delete**)
- `purge/` pada file upload (satu-satunya hard delete yang disengaja)
- korupsi database

---

## Restore

**Backup yang belum pernah diuji restore bukan backup.**

```bash
createdb meinova_restore_test
pg_restore -d meinova_restore_test meinova-2026-08-13.dump
```

Yang wajib diverifikasi setelah restore uji:

- [ ] `tenants_client` dan `tenants_domain` di schema `public` terisi
- [ ] Jumlah schema sesuai jumlah tenant
- [ ] Satu tenant bisa dibuka lewat aplikasi
- [ ] Lampiran bisa diunduh (metadata **dan** filenya)
- [ ] `django_celery_beat` punya jadwalnya

### Restore satu tenant

Skenario yang paling mungkin nyata: satu klien salah menghapus data, yang lain harus tetap jalan.

```bash
pg_restore -d meinova_erp -n demo --clean meinova-2026-08-13.dump
```

!!! warning "`--clean -n demo` menghapus isi schema itu lebih dulu"
    Semua yang terjadi di tenant tersebut sejak backup **hilang**. Pastikan ini keputusan yang disadari, dan ambil dump schema itu apa adanya sebelum menimpanya.

Salin juga `media/demo/`.

---

## Prosedur yang perlu dibuat

- [ ] Cron `pg_dump` harian ke storage di luar server aplikasi
- [ ] Sinkronisasi `media/` (rsync atau object storage berversi)
- [ ] Uji restore **terjadwal**, bukan sekali saat setup
- [ ] Alert kalau backup gagal
- [ ] Dump manual sebelum migrasi yang menghapus/rename kolom

Baris terakhir bukan formalitas: rename `Site` → `Location` menyentuh model, FK di seluruh modul, dan empat migrasi lain — perubahan sebesar itu tidak punya jalan mundur yang murah.

Lihat [Disaster Recovery](Disaster-Recovery.md).
