# Konvensi Penamaan Database

Diambil dari 168 model yang ada, bukan dari aturan yang diinginkan.

---

## Nama tabel — prefix per **kategori**, bukan per app Django

Ini yang paling sering salah dikira. Prefix tidak selalu sama dengan nama app.

| Prefix | Jumlah | Isi | App |
|---|---:|---|---|
| `master_` | 100 | seluruh master & referensi | `administration` |
| `hr_` | 37 | transaksional & data pegawai | `hr` |
| `accounts_` | 9 | RBAC, sesi, API key | `accounts` |
| `payroll_` | 7 | | `payroll` |
| `workflow_` | 6 | engine approval | `workflow` |
| `tenants_` | 4 | Client, Domain, Plan, Subscription | `tenants` |
| `imports_` | 3 | | `imports` |
| `uploads_` | 1 | | `uploads` |
| `auth_users` | 1 | model User kustom | `accounts` |

```python
class Meta:
    db_table = "hr_travel_request"
```

- `snake_case`, **singular** (`hr_employee`, bukan `hr_employees`)
- Nama tabel **selalu ditulis eksplisit** — jangan biarkan Django menurunkannya dari `<app>_<model>`, karena app `administration` akan menghasilkan `administration_*` yang menyimpang dari konvensi

!!! note "Kenapa `master_` dan bukan `administration_`"
    Kategorinya yang bermakna, bukan letak kodenya. `master_leave_type` langsung terbaca sebagai master; `administration_leave_type` cuma memberi tahu di app mana kodenya kebetulan tinggal.

!!! warning "Dua tabel bernama mirip, dan ini bukan salah ketik"
    `accounts_user_session` **dan** `master_user_session` sama-sama ada. Periksa mana yang benar-benar dipakai sebelum menyentuh salah satunya.

---

## Kolom

| Jenis | Pola | Contoh |
|---|---|---|
| Foreign key | `<entitas>` (Django menambahkan `_id`) | `company` → `company_id` |
| Boolean | `is_*` / `has_*` / `requires_*` / `allow_*` | `is_deleted`, `requires_contract`, `allow_self` |
| Tanggal | `*_date` | `start_date`, `join_date` |
| Timestamp | `*_at` | `created_at`, `applied_at` |
| Pelaku | `*_by` | `created_by`, `approved_by`, `acted_by` |
| Jumlah | `*_count` / `*_days` / `*_minutes` | `line_count`, `total_days`, `duration_minutes` |
| Urutan | `sequence` / `sort_order` | |

Kolom bawaan `BaseModel`: `created_at`, `created_by`, `updated_at`, `updated_by`, `is_deleted`, `deleted_at`, `deleted_by`.

`BaseReference` menambah: `code`, `name`, `description`, `sort_order`.

---

## Constraint — polanya wajib diikuti

```python
UniqueConstraint(
    fields=["company", "code"],
    condition=Q(is_deleted=False),
    name="uniq_active_hr_vehicle_company_code",
)
```

Format nama: **`uniq_active_<app>_<model>_<kolom>`**

`BaseReference` memakai placeholder supaya turunannya tidak bentrok:

```python
name="uniq_active_%(app_label)s_%(class)s_code"
```

!!! danger "`condition=Q(is_deleted=False)` bukan opsional"
    Tanpa itu, nilainya **terkunci selamanya** oleh record yang sudah di-soft-delete. Kode `LOC-01` yang dihapus tidak bisa dipakai lagi, dan tidak ada pesan yang menjelaskan kenapa.

Yang sengaja **tidak** dikondisikan, dan alasannya:

| Kolom | Alasan |
|---|---|
| `public_id` (UUID) | tidak pernah dipakai ulang |
| `ApiKey.hashed_key` | harus unik global **termasuk** yang sudah dicabut |
| `uniq_active_hr_rotation_period_sequence` | berlaku untuk **seluruh** baris rencana termasuk yang ditutup — nomor urut tidak pernah dipakai ulang |
| OneToOne (`OrganizationAssignment.employee`, dst.) | mengubahnya berarti mengganti `OneToOneField` jadi FK + constraint, dan itu mengubah accessor seperti `employee.organization` |

---

## Kode unik per company, bukan global

Konsekuensi paling penting dari struktur organisasi:

```python
name="uniq_core_location_company_code"    # (company, code), bukan code saja
```

Kena: Branch, Location, Division, Department, Section, Position, CostCenter.

!!! danger "Jangan pernah mencari entitas organisasi hanya dari `code`"
    Wajib disaring lewat induknya. Lihat `ORGANIZATION_CHAIN` di `apps/hr/imports/employee/resolver.py` — kode ambigu **ditolak, bukan ditebak**.

    Dan karena induk di master boleh kosong, penyaringannya memakai pola **"cocok dengan induk ATAU induknya null"**.

---

## Relasi

| | Pola |
|---|---|
| `on_delete` | `PROTECT` untuk master, `SET_NULL` untuk taut opsional, `CASCADE` untuk anak sejati |
| `related_name` | plural (`vehicles`), atau deskriptif untuk OneToOne (`employee_profile`) |

!!! warning "Accessor akun → pegawai adalah `user.employee_profile`"
    Bukan `user.employee`. `getattr` mengembalikan `None` tanpa error, jadi kesalahan ini **gagal diam** — pernah membuat "pegawainya sendiri" dan "atasan langsung" tidak pernah cocok di `EmployeeDataPolicy`, sehingga orang tidak bisa melihat riwayat gajinya sendiri.

`RotationPeriod.employee_leave` memakai `SET_NULL`: menghapus catatan cuti tidak boleh menghapus blok off dari jadwal.

---

## `ordering` di `Meta`

```python
class Meta:
    ordering = ["code"]
```

!!! warning "`ordering` di viewset menang atas `Meta.ordering`"
    DRF `OrderingFilter` memakai atribut viewset sebagai default, dan `order_by()` membuang urutan model. Mengubah salah satunya saja tidak cukup — lihat [Sorting](../05-api/Sorting.md#ordering-di-viewset-menang-atas-metaordering-model).

---

## Checklist model baru

- [ ] `db_table` eksplisit dengan prefix kategori yang benar
- [ ] Turunan `BaseModel` atau `BaseReference`
- [ ] `class Meta(BaseReference.Meta)` kalau turunan `BaseReference`
- [ ] `UniqueConstraint` + `condition=Q(is_deleted=False)`, nama mengikuti pola
- [ ] Kode organisasi unik **per company**
- [ ] `verbose_name` Inggris, `help_text` Indonesia
- [ ] Reexport di `models/__init__.py`
