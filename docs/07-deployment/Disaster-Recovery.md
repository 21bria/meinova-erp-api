# Disaster Recovery

Prosedur pemulihan. Prasyaratnya ada di [Backup](Backup.md) — dan hari ini **prasyarat itu belum terpenuhi**: belum ada backup terjadwal maupun restore yang pernah diuji.

---

## Skenario, dari yang paling mungkin

| # | Skenario | Kemungkinan | Pemulihan |
|---|---|---|---|
| 1 | Satu tenant salah hapus data | tinggi | soft delete / restore per schema |
| 2 | Migrasi gagal di tengah | sedang | restore + rollback migrasi |
| 3 | Seed salah dijalankan | sedang | tergantung seed-nya |
| 4 | Disk `media/` hilang | rendah | restore file |
| 5 | Database rusak total | rendah | restore penuh |
| 6 | Server hilang | rendah | rebuild + restore |

Tiga yang pertama jauh lebih sering terjadi daripada tiga terakhir, dan dua di antaranya **tidak butuh backup sama sekali**.

---

## 1 · Salah hapus data

**Periksa dulu apakah ini soft delete.** Seluruh penghapusan lewat UI di sistem ini soft — barisnya masih ada dengan `is_deleted=True`.

```python
from django_tenants.utils import schema_context
from apps.hr.models import Employee

with schema_context("demo"):
    row = Employee.all_objects.get(pk=154)   # bukan .objects
    row.is_deleted = False
    row.deleted_at = None
    row.deleted_by = None
    row.save()
```

Lebih baik lewat service, karena ia punya hook dan mencatat audit:

```python
EmployeeService.restore(instance=row, user=admin)
```

!!! warning "Tidak ada tombol restore di UI"
    Hanya lewat shell atau importer. Itu disengaja — tapi artinya pemulihan seperti ini butuh akses server.

**Yang benar-benar hilang** (hard delete): `purge/` pada file upload, `reset_demo_data`, penghapusan `FavoriteApp`/`UserDashboardLayout`, dan model tanpa kolom `is_deleted`.

---

## 2 · Migrasi gagal di tengah

Paling berbahaya di sistem ini, karena `migrate_schemas` menyentuh **setiap** tenant berurutan. Kegagalan di tenant ke-17 meninggalkan 16 tenant termigrasi dan sisanya tidak.

```bash
# 1. Hentikan traffic — jangan biarkan aplikasi jalan separuh termigrasi
# 2. Periksa tenant mana yang sudah
python manage.py tenant_command showmigrations <app> --schema=<tenant>

# 3a. Kalau penyebabnya bisa diperbaiki: betulkan, lalu lanjutkan
python manage.py migrate_schemas

# 3b. Kalau tidak: mundurkan yang sudah, per tenant
python manage.py tenant_command migrate <app> <nomor_sebelumnya> --schema=<tenant>
```

!!! danger "Migrasi yang menghapus kolom tidak bisa dimundurkan tanpa kehilangan data"
    `RunPython` tanpa `reverse_code` juga tidak. Untuk perubahan sebesar rename `Site` → `Location`, jalan mundurnya **hanya** restore dari backup.

    Karena itu: dump manual sebelum migrasi yang menghapus atau mengganti nama kolom.

---

## 3 · Seed salah dijalankan

Tergantung seed-nya:

| Seed | Sifat | Pemulihan |
|---|---|---|
| `seed_menus`, `seed_security_roles`, `seed_workflows`, `seed_administration` | idempotent, **hanya menambah** | tidak perlu — jalankan lagi kalau perlu |
| `seed_*_demo` | membuat data uji | hapus manual (nomor pegawai `HO*`/`GBE*`, akun `demo.*`) |
| **`reset_demo_data`** | **hard delete** | **restore dari backup** |

Yang terakhir yang berbahaya. Ia menyaring lewat awalan nomor pegawai dan akun `demo.*` — jadi di tenant produksi yang penomorannya berbeda, ia biasanya tidak menemukan apa-apa. **Biasanya**, bukan pasti.

Itu salah satu alasan data uji sengaja tidak meniru pola penomoran klien.

---

## 4 · `media/` hilang

Metadata file ada di DB (`UploadedFile`), byte-nya di disk. Kalau disk hilang tapi DB utuh:

- Baris DB-nya masih ada, unduhannya gagal
- `checksum_sha256` bisa dipakai memverifikasi file yang dipulihkan
- File per schema di `media/<schema>/`, jadi bisa dipulihkan per tenant

Kalau file **tidak** bisa dipulihkan, baris DB-nya sebaiknya ditandai — bukan dihapus, karena record induk (kontrak, dokumen pegawai) menunjuknya lewat FK.

---

## 5 · Restore penuh

```bash
# 1. Database
createdb meinova_erp
pg_restore -d meinova_erp meinova-2026-08-13.dump

# 2. Verifikasi peta tenant DULU
psql meinova_erp -c "SELECT schema_name, name FROM tenants_client;"
psql meinova_erp -c "SELECT domain, tenant_id FROM tenants_domain;"

# 3. Media
rsync -a backup/media/ /srv/meinova/media/

# 4. Jalankan, verifikasi per tenant
```

!!! danger "Langkah 2 tidak boleh dilewati"
    Schema `public` memuat peta schema→domain. Kalau `tenants_client`/`tenants_domain` kosong, **seluruh tenant tidak bisa diakses** walau datanya utuh — tidak ada hostname yang mengarah ke sana, dan gejalanya terlihat seperti databasenya kosong.

---

## 6 · Server hilang

```
1. Provision server + PostgreSQL + Redis
2. Deploy kode (git — bukan bagian dari backup)
3. Pulihkan .env       ← sering jadi penghalang
4. Restore database
5. Restore media/
6. collectstatic, jalankan web + worker + beat
7. Arahkan DNS
8. Verifikasi per tenant
```

!!! warning "`SECRET_KEY` yang hilang membatalkan seluruh JWT yang beredar"
    Semua orang harus login ulang. Tidak fatal, tapi harus diantisipasi dalam komunikasi ke klien — dan itu alasan `.env` layak masuk daftar backup.

---

## Verifikasi setelah pemulihan apa pun

- [ ] `tenants_client` & `tenants_domain` terisi
- [ ] Jumlah schema = jumlah tenant
- [ ] Login berhasil di **beberapa** tenant, bukan cuma satu
- [ ] Sidebar muncul (menu permission utuh)
- [ ] Satu lampiran bisa diunduh — metadata **dan** filenya
- [ ] Jadwal `django_celery_beat` ada, dan beat **hanya satu** instance
- [ ] Kotak masuk approval menampilkan dokumen yang sedang berjalan
- [ ] Worker Celery hidup, antrean bersih

Baris keenam: kalau jadwal hilang, pengingat kepegawaian diam-diam berhenti — dan tidak ada yang menyadarinya sampai ada kontrak yang telat diperpanjang.

---

## Yang khas multi-tenant dan mudah terlewat

1. **Peta tenant ada di `public`**, terpisah dari data tenant
2. **Restore selektif per schema mungkin** — satu klien bisa dipulihkan tanpa mengganggu yang lain
3. **Verifikasi harus per tenant.** Satu tenant yang jalan bukan bukti semuanya jalan
4. **Migrasi per tenant** — keadaan migrasi bisa berbeda antar schema setelah kegagalan parsial

---

## Prosedur yang perlu dibuat

- [ ] Backup terjadwal + alert kalau gagal
- [ ] **Uji restore terjadwal** — backup yang belum pernah diuji restore bukan backup
- [ ] Runbook dengan kontak dan urutan tindakan
- [ ] RPO/RTO ditetapkan
- [ ] Latihan pemulihan setidaknya sekali
