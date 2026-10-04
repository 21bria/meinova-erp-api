# Desain Database

PostgreSQL 16 + **schema-per-tenant** lewat django-tenants. 168 model, satu database.

---

## Satu database, banyak schema

```
meinova_erp
├── public          ← tenants_client, tenants_domain, django_celery_beat
├── demo            ← seluruh tabel bisnis
├── klien_a         ← salinan struktur yang sama, data terpisah
└── klien_b
```

| | Isinya |
|---|---|
| `SHARED_APPS` | `tenants` + contrib + `corsheaders` + `django_celery_beat` |
| `TENANT_APPS` | **semua app bisnis** |

App baru **selalu** masuk `TENANT_APPS`.

Konsekuensi yang membentuk hampir semua hal lain:

1. **Isolasi data adalah properti database**, bukan kolom `tenant_id` yang harus diingat difilter. Tidak ada satu pun query di codebase ini yang menyaring per tenant — schema-nya yang berpindah.
2. **Migrasi berjalan per schema.** `migrate_schemas` menyentuh setiap tenant berurutan.
3. **Peta schema→domain ada di `public`.** Tanpa `tenants_client`/`tenants_domain`, schema tenant yang dipulihkan tidak bisa diakses siapa pun.
4. **Task Celery wajib `schema_context()`.** Pola rujukan: `run_attendance_import` — `schema_name` dioper sebagai argumen task, seluruh body dibungkus `with schema_context(schema_name):`.

Model deployment fleksibel: shared multi-tenant untuk SMB, atau dedicated/on-premise untuk enterprise — **dari codebase yang sama**.

---

## Empat pola desain yang berulang

Mengenali keempatnya cukup untuk membaca sebagian besar model di sini.

### 1 · Soft delete di mana-mana

Setiap turunan `BaseModel` punya `is_deleted` / `deleted_at` / `deleted_by`. Tidak ada endpoint hapus permanen; itu disengaja.

**Konsekuensinya setiap constraint unik wajib dikondisikan** — lihat [Naming Convention](Naming-Convention.md#constraint--polanya-wajib-diikuti).

### 2 · Effective-dated, bukan menimpa

Data yang punya sejarah tidak ditimpa — baris lama ditutup, baris baru berdiri.

| Model | Mekanisme |
|---|---|
| `PayrollAssignment` | `is_current` + `effective_from` / `effective_to` |
| `RotationPeriod` | `version_from` / `version_to` |
| `EmployeeAction` | transaksi terpisah dari keadaan (`EmploymentAssignment`) |

`EmployeeAction` adalah contoh paling jelas kenapa: kalau perpanjangan kontrak menimpa `contract_end`, pegawai yang sudah tiga kali diperpanjang lalu diangkat **terlihat seperti tidak pernah berkontrak**.

!!! note "`RotationPeriod`: nomor urut tidak pernah dipakai ulang"
    Constraint berlaku untuk seluruh baris termasuk yang ditutup, jadi nomor urut **berlubang** di versi berjalan. Itu benar — urutan tampilan ditentukan tanggal, nomor urut cuma identitas baris.

### 3 · Aturan sebagai data, dicocokkan berjenjang

Lima master mengikuti pola yang sama persis:

`WorkflowDefinition` · `LeavePolicy` · `RosterPolicy` · `EmployeeActionPolicy` · `EmployeeDataPolicy`

Masing-masing punya kolom cakupan (`company` / `branch` / `location` / `employee_group`), dicocokkan lewat **skor `specificity`** — bukan urutan baris.

!!! danger "Kosong berarti 'berlaku untuk semua', bukan 'tidak berlaku'"
    Jebakan yang sama di kelima master, dan di `RoleMenuPermission`/`RoleDataPermission`. **Role tanpa satu pun baris cakupan = tanpa batasan.**

### 4 · Ledger append-only untuk yang harus bisa diaudit

`RotationCreditTransaction`: `update()` dan `soft_delete()` **melempar**. Koreksi lewat `ADJUSTMENT_PLUS`/`MINUS`, pembatalan lewat `REVERSAL` yang menunjuk barisnya (satu kali, dijaga constraint).

`days` selalu positif — arahnya dari `entry_type`, karena dua cara menulis pengurangan yang sama membuat penjumlahannya bergantung mana yang kebetulan dipakai.

Saldo (`RotationCreditBalance`) **dihitung ulang dari ledger** tiap transaksi. Alasan yang sama dengan `LeaveBalance.used`: penjumlahan ulang tidak bisa hanyut.

---

## Denormalisasi yang disengaja

| Kolom | Kenapa | Yang menjaga konsistensinya |
|---|---|---|
| `LeaveBalance.used` | supaya bisa disortir & difilter di tabel | dijumlahkan ulang penuh oleh `EmployeeLeaveService` tiap perubahan |
| `RotationCreditBalance` | idem | dihitung ulang dari ledger |
| `EmployeeAttendance.company/branch/location` | penyaringan `RoleDataPermission` tanpa join berlapis | `EmployeeAttendanceService` saat create |
| `RotationPeriod.period_type` | kolom turunan dari `segment_type` | untuk pemanggil lama |

Aturannya: **denormalisasi selalu disertai satu tempat yang menghitungnya ulang**, dan perhitungannya penuh — bukan inkremental.

---

## Engine workflow tidak punya FK ke dokumen

`WorkflowInstance` menunjuk dokumen lewat `module` + `document_type` + `object_id` (**string**), bukan `GenericForeignKey`.

Kunci yang sama persis dengan kunci pencarian alurnya, dan engine jadi tidak perlu mengenal ContentType maupun model modul mana pun.

**Konsekuensinya tidak ada integritas referensial di level database.** Yang menjaganya: constraint `uq_workflow_open_instance` + kenyataan bahwa penghapusan dokumen selalu soft.

Risiko nyatanya: pembersihan data uji pernah meninggalkan pengajuan yatim yang **menahan pegawainya lewat FK ber-`PROTECT`**. Karena itu `reset_demo_data` menyaring lewat `subject_employee`/`submitted_by`, bukan hanya `object_id`.

---

## Struktur organisasi: hanya Company yang wajib

```
Company → Branch → Location → Division → Department → Section
        + Position / Job Level / Job Grade / Cost Center
```

Seluruh level di bawah Company **nullable dan boleh dilompati** — `Location.branch` boleh kosong. Satu struktur melayani UMKM satu kantor sampai tambang multi-lokasi.

**Location = lokasi kerja fisik**, dulu bernama Site. Bedanya dengan Branch: Branch unit administratif, Location tempat orang bekerja — absensi, shift, dan kalender libur menempel ke Location.

Konsekuensi desainnya: kode unik per company, dan penyaringan memakai pola "cocok dengan induk **ATAU** induknya null".

---

## Employee: identitas terpisah dari penempatan

`Employee` hanya identitas. Yang menentukan perilakunya di empat model terpisah:

| Model | Kardinalitas |
|---|---|
| `OrganizationAssignment` | OneToOne |
| `EmploymentAssignment` | OneToOne |
| `PayrollAssignment` | banyak, effective-dated |
| Bank / pendidikan / keluarga / dokumen / medis | banyak |

Memisahkannya begini yang membuat perubahan bisa punya tanggal berlaku, dan membuat `EmployeeDataPolicy` bisa menutup **sebagian** data pegawai tanpa menutup seluruh barisnya.

---

## Index

214 `models.Index` terdaftar. Lihat [Indexing](Indexing.md).

---

## Yang perlu disadari

- **`django_celery_beat` di `public`** — satu penjadwal untuk semua tenant, jadi tasknya sendiri yang menyebar per schema
- **`auth_users` di tenant schema** — akun hidup di dalam tenant; username yang sama di dua tenant adalah dua orang berbeda
- **`accounts_user_session` dan `master_user_session`** sama-sama ada; periksa mana yang dipakai
- **`EmployeeMovement`** (`apps/hr/models/employee_history.py`) tidak pernah punya migration — **kode mati**, jangan dihidupkan sebagai riwayat paralel
