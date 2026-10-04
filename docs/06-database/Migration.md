# Migration

Django migration **di atas django-tenants**. Perbedaannya bukan kosmetik — `python manage.py migrate` biasa **tidak cukup** dan bisa menyesatkan.

---

## Perintah

```bash
python manage.py makemigrations <app>

python manage.py migrate_schemas --shared        # SHARED_APPS → public
python manage.py migrate_schemas                 # SEMUA tenant schema
python manage.py migrate_schemas --schema=demo   # satu tenant
```

| Perintah | Menyentuh |
|---|---|
| `migrate_schemas --shared` | `public` saja |
| `migrate_schemas` | setiap schema tenant, **berurutan** |

Jumlah migrasi hari ini: `hr` 37 · `administration` 29 · `accounts` 7 · `imports` 6 · `workflow` 4 · `framework` 3 · `payroll` 3.

---

## `run_before` — jebakan yang menggagalkan tenant baru

!!! danger "Migrasi yang menyentuh model hasil rename WAJIB menyatakan `run_before`"
    Empat migrasi (`hr/0002`, `hr/0009`, `hr/0010`, `imports/0004`) menambah FK ke `administration.Site` — model yang dihapus oleh `administration/0011_rename_site_to_location` — tapi tidak satu pun menyatakan urutannya terhadap rename itu.

    Django bebas menjadwalkan rename lebih dulu. `imports/0004` memang kena: **penyediaan tenant baru gagal** dengan

    ```
    Related model 'administration.site' cannot be resolved
    ```

    Tiga sisanya cuma **kebetulan** terjadwal benar — dan menambah migrasi baru bisa mengubah urutannya kapan saja. Keempatnya sudah ditambal.

```python
class Migration(migrations.Migration):
    dependencies = [("hr", "0001_initial")]
    run_before = [("administration", "0011_rename_site_to_location")]
```

**Kenapa ini tidak pernah terlihat di mesin developer:** database lokal sudah lama ada dan migrasinya sudah jalan berurutan. Bug ini **hanya muncul saat replay dari nol** — yaitu saat klien baru di-provision.

Itu sebabnya "replay migrasi dari database kosong" layak jadi tahap CI tersendiri. Lihat [CI/CD](../07-deployment/CI-CD.md).

---

## Urutan aman untuk perubahan berisiko

### Menambah kolom NOT NULL

```
1. Tambah nullable
2. Isi datanya (RunPython)
3. Ketatkan jadi NOT NULL
```

Tiga migrasi, bukan satu. Migrasi yang menulis ulang tabel besar × puluhan tenant adalah jendela deploy yang tidak perlu.

### Mengganti nama model/kolom

```
1. Tambah yang baru berdampingan
2. Salin data
3. Pindahkan pemanggil (kode, schema, serializer, importer)
4. Hapus yang lama — setelah dipastikan tidak ada yang memakai
```

Rename `Site` → `Location` menyentuh model, kolom FK `site` → `location` di seluruh modul, dan empat migrasi lain. Importer employee **tetap menerima header `site`/`site_code` sebagai alias** supaya file klien lama jalan — itu bagian dari langkah 4 yang belum bisa diselesaikan.

### Mengganti unique polos jadi constraint terkondisi

```python
migrations.AlterField(...),                        # cabut unique=True
migrations.AddConstraint(
    model_name="location",
    constraint=models.UniqueConstraint(
        fields=["company", "code"],
        condition=models.Q(is_deleted=False),
        name="uniq_active_core_location_company_code",
    ),
),
```

Pola ini sudah dijalankan satu per satu untuk payroll, `Bank`, `Currency`, `Country`, `Menu`, `Role`, `Dashboard*`, `AttendanceImportProfile`.

---

## Migrasi data

```python
def forward(apps, schema_editor):
    Model = apps.get_model("hr", "Vehicle")     # historis, BUKAN import langsung
    ...

migrations.RunPython(forward, migrations.RunPython.noop)
```

- **Selalu `apps.get_model()`** — import langsung memakai definisi model *hari ini*, yang bisa sudah berbeda dari saat migrasi ini ditulis
- **Selalu sediakan `reverse_code`**, minimal `noop`
- **Migrasi data berjalan per tenant.** Untuk data besar, pikirkan durasinya × jumlah tenant

Contoh yang ada: `workflow/0002_migrate_framework_approval` memindahkan pengajuan yang sedang berjalan dari implementasi lama. `framework/0003` yang menghapus tabel lamanya **sengaja bergantung padanya** — tanpa dependency itu, urutannya ditentukan abjad nama app dan **pengajuan yang sedang berjalan terhapus sebelum sempat dipindah**.

---

## Migrasi data yang lebih baik jadi management command

Beberapa pemindahan tidak cocok jadi migrasi, dan sudah dibuat sebagai command:

| Command | Kenapa bukan migrasi |
|---|---|
| `migrate_roster_assignments` | **melewati yang ambigu** alih-alih menebak — butuh `--dry-run` dan laporan |
| `migrate_attendance_import_profiles` | idem |

Aturannya: kalau pemindahannya bisa gagal sebagian dan butuh diperiksa orang, jadikan command dengan `--dry-run`. Migrasi harus deterministik.

---

## Konflik

Dua branch yang sama-sama menambah migrasi di app yang sama **akan konflik** pada `dependencies`.

- Resolusinya **ganti nomor & `dependencies`**, bukan merge teks
- Jangan menyunting migrasi yang sudah di-merge — buat yang baru
- Kalau tahu ada branch lain menyentuh app yang sama, merge yang duluan selesai lalu rebase

---

## Rollback

```bash
python manage.py tenant_command migrate <app> <nomor> --schema=<tenant>
```

Per tenant. Untuk puluhan tenant, itu berarti loop — dan kegagalan di tengah meninggalkan keadaan migrasi yang **berbeda antar schema**.

!!! danger "Yang tidak bisa dimundurkan"
    - Migrasi yang **menghapus kolom** — datanya hilang
    - `RunPython` tanpa `reverse_code`
    - Rename berskala besar

    Jalan mundurnya hanya restore dari backup. **Dump manual sebelum migrasi yang menghapus atau mengganti nama kolom.**

---

## Checklist

- [ ] `makemigrations --check --dry-run` bersih sebelum commit
- [ ] Migrasi yang menyentuh model hasil rename menyatakan `run_before`
- [ ] Kolom NOT NULL baru dipecah tiga langkah
- [ ] `RunPython` memakai `apps.get_model()` + punya `reverse_code`
- [ ] Constraint unik dikondisikan ke `is_deleted`
- [ ] Diuji di **database kosong**, bukan cuma di lokal yang sudah lama ada
- [ ] Durasinya × jumlah tenant masih masuk akal
- [ ] Dicatat di deskripsi PR
