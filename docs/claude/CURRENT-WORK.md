# CURRENT WORK

Handoff singkat untuk sesi berikutnya. **Bukan arsip.** Detail
implementasi, business rule final, invariant, dan known gap tinggal di
dokumen domain — berkas ini hanya menunjuk ke sana.

---

## Active Task

### HR Period Summary — drill-down audit + dwibahasa (17 Sep 2026)

Kontrak drill-down diperluas secara aditif (kode stabil `source_code`,
`detail_kind`, `aggregate.unit`, `duration_minutes`, jam `HH:MM` per
baris). Late/Early tetap kejadian; durasinya dari `late_minutes`/
`early_leave_minutes` milik resolver. `total` kini = accessor tabel
(memperbaiki selisih 0,99 vs 1,0 pada jam OT). `employee_id` di luar
populasi → 404, bukan angka → 400. Detail: `docs/claude/reports.md`
§ "Drill-down: kontrak audit". Frontend: `meinova-erp/docs/claude/dashboard.md`.
Test: `apps.reports.tests.hr.test_period_summary_drilldown`.
Belum: katalog kolom laporan HR lain (masih Inggris).
Verifikasi (17 Sep 2026, belum commit): drilldown 13/13; regresi 4 suite
Period Summary + `apps.self_service` 272/273 — satu merah = `SummaryTests`
8≠10 yang sudah ada (§6D self-service.md). UAT browser 79/81; 2 FAIL =
label periode "Agustus 2026 Bulanan" tetap Indonesia di mode EN
(`framework/core/utils/dashboard.ts`, sudah ada sebelumnya, di luar cakupan).
Demo: lembur berstatus `approved`, laporan hanya menghitung RECORDED → OT 0.

### My Workspace — personal context (C9 + C10, 17 Sep 2026)

- **C9 Jadwal Saya** selesai: `GET /api/me/schedule/`,
  `/hr/shift-calendar?mode=my`.
- **C10 Ajukan Cuti/Izin pribadi** selesai: `POST /api/me/leave-requests/`,
  `POST /api/me/attendance-permissions/`, CTA `...create?mode=my`.
  Jalur HR Cuti/Izin kini menolak `employee` di luar cakupan **izin
  tulis** (garis pelaporan tidak memberi hak create).
- **Lembur belum** (lubang create yang sama masih terbuka).
- Temuan terbuka yang butuh keputusan: `status` Cuti bisa ditulis via
  HR (RECORDED/APPROVED tanpa alur), `allow_outside_shift` bisa ditulis
  pemegang add, lampiran HR tanpa cek pemilik, dan
  `ROLE_AWARE_DATA_SCOPE` bawaan mati (cakupan tulis = gabungan semua role).

Detail: `docs/claude/self-service.md` §6D–§6E.

### Finance Core — FROZEN (2026-09-17)

`pnpm typecheck`: 97 → 85 error TS, 0 error baru, 0 error khas Finance.
Yang diperbaiki cuma berkas FE Finance: import `@framework` yang hilang,
dan tipe `AccountNode` yang disamakan. Sisa 8 error di Finance adalah cacat
template `*Workspace.vue` yang ada di semua modul. Aturan freeze dan
buktinya ada di `docs/claude/finance.md` § Freeze. **Berhenti di sini.**
Langkah berikutnya (Payroll → Finance) belum dimulai.

### Attendance List — date-range + performa query (SELESAI, diterima 2026-09-17)

Verifikasi yang diterima: test date-range 36/36, regresi attendance +
attendance_permission 126/126, frontend 265/265, error TS baru 0,
`manage.py check` bersih, `makemigrations --check` tanpa perubahan,
cek policy date-range 19/19, `filters.ts` identik byte dengan generator.

#### FOLLOW-UP — bukan bagian pekerjaan ini, belum dikerjakan

1. **Konsolidasi period policy.** `/api/hr/attendance` memakai
   `PeriodScopedListMixin`; `/api/me/attendance` masih punya implementasi
   date-range sendiri walau parameter dan batas 90 hari sama. Audit apakah
   keduanya bisa memakai canonical period policy yang sama **tanpa**
   mengubah semantik keamanan current-employee.
2. **Review otorisasi attendance.** User tanpa role assignment mendapat
   attendance *unrestricted* (`require_view_permission=False` + DataScope
   memperlakukan tanpa assignment sebagai unrestricted). Perilaku lama,
   sekarang dipin test. **Jangan ubah diam-diam** — butuh keputusan
   security tersendiri.
3. **Penyelarasan semantik overtime.** Overtime attendance mentah,
   `EmployeeOvertime`, overtime Reports, dan overtime Payroll butuh
   canonical policy tersendiri. Jangan diselesaikan sebagai bagian
   pekerjaan date-range.

### Multi-bahasa — Stage 4: cakupan EN/ID seluruh modul
Status: **SELESAI** — 9 Sep 2026. Nol migration, nol perubahan logika.

#### IMPLEMENTED

| Berkas | Perubahan |
|---|---|
| `apps/framework/introspection/schema.py` | `derive_i18n_namespace()` — namespace diturunkan dari `framework_module` (`hr/employees` → `hr.employees`). **Satu perubahan untuk 182 modul**; schema tetap boleh menyetel `i18n.namespace` sendiri dan nilai eksplisit selalu menang |
| `apps/framework/builders/dashboard.py` | default `period_filter(label=...)` "Periode" → "Period" |
| `apps/administration/api/overview/schema.py` | 21 label widget/kolom → Inggris |
| `apps/{hr,payroll}/api/dashboard/schema.py` | 61 label widget → Inggris |
| `apps/reports/api/hr/*/schema.py` (5) | 18 label + 16 `empty_text` → Inggris |
| `apps/payroll/api/{payroll_policies,payroll_run_employees,overtime_groups}/schema.py` | 15 label/placeholder → Inggris (prefiks "Bulanan -"/"Harian -" jadi "Monthly -"/"Daily -") |
| `apps/notifications/`, `apps/hr/`, `apps/payroll/` (opsi enum) | 61 label opsi → Inggris; **kode enum tidak disentuh** |

Kalimat Indonesianya tidak hilang — pindah utuh ke katalog frontend.

**Kenapa namespace diturunkan, bukan ditulis:** `framework_module` dan
namespace katalog menamai resource yang sama, cuma beda pemisah.
Menulisnya satu per satu di 182 schema berarti 182 kesempatan salah
ketik, dan yang salah ketik tidak menimbulkan error — modulnya cuma
diam-diam tidak pernah ikut diterjemahkan.

#### CONFIRMED — yang tidak bergerak

- **Nol migration.** `makemigrations --check` bersih.
- **Nama field, kode enum, dan nilai database tidak disentuh.** Yang
  berubah hanya `label`, `empty_text`, dan `placeholder`.
- Tidak ada kolom `name_id`/`name_en`, tidak ada tabel terjemahan.
- Data tenant (nama pegawai, perusahaan, departemen, lokasi, nomor
  dokumen) tidak pernah lewat katalog mana pun.
- Migration yang sempat ikut tersunting oleh replace massal sudah
  dikembalikan; berkas migration tidak boleh disunting.

#### TESTED

`manage.py check` bersih; `makemigrations --check` bersih.
`apps.accounts.tests.test_user_language` + `apps.workflow` 10/10 OK.
`apps.reports` + `apps.notifications` dijalankan dengan database test
baru. Verifikasi tampilan bilingual dilakukan di browser — detail di
entri Stage 4 repo frontend.

#### OPEN

- **Label enum yang tinggal di `choices` model** (`own`, `explicit`,
  `subject`, `submitter`, `preparer`, `sent`, `inherit`, `on`) masih
  berbahasa Indonesia di backend. Mengubahnya menghasilkan migration
  `AlterField` — di luar cakupan task presentasi ini. Pengguna English
  tetap terlayani: katalog `common.status.<kode>` menang atas label API.
- Label pada **respons** API (`services.py` laporan, deret chart) belum
  dilokalkan — itu isi respons, bukan ui-schema.
- `scope_label` di `workflow/api/definition/serializers.py` tetap tidak
  diterjemahkan — campuran nama tenant dengan kalimat sistem.
- Placeholder contoh "e.g. BPJS Kesehatan (Pegawai)" dibiarkan: nama
  lembaga Indonesia.

#### Catatan git

`apps/` kini **tracked**: 1.067 berkas untracked (termasuk 126
migration) dimasukkan ke index pada 9 Sep 2026. Belum ada commit.
Enam berkas catatan pribadi di root (`worker`, `trial_email`,
`prompt.txt`, `seed_data.txt`, `cek_mesin_finger.txt`,
`CLAUDE.backup.md`) sengaja dibiarkan untracked — `git clean -fd`
masih akan menghapusnya.

---

### Multi-bahasa — Stage 2A: label Workflow kembali ke bahasa Inggris
Status: **SELESAI** — 9 Sep 2026. Nol migration, nol perubahan logika
approval, nol nilai enum yang bergeser.

#### IMPLEMENTED

**Akar masalahnya bukan bug, melainkan asumsi yang kedaluwarsa.**
`apps/workflow/labels.py` ditulis waktu belum ada i18n sama sekali;
saat itu schema backend memang satu-satunya peta label terpusat yang
tersedia, jadi menerjemahkan di sana masuk akal. Yang tidak ikut
dipikirkan: **API tidak punya cara tahu bahasa pembacanya.** Hasilnya
setiap pengguna menerima Bahasa Indonesia — termasuk yang memilih
English — dan layar Workflow jadi satu-satunya bagian aplikasi yang
tidak menghiraukan pilihan bahasa orangnya.

| Berkas | Perubahan |
|---|---|
| `apps/workflow/labels.py` | 7 peta enum dikembalikan ke bahasa Inggris (approver type, scope, mode, workflow/instance/approval status, assignment type) |
| `apps/workflow/api/definition/serializers.py` | `scope_label` fallback `"Semua (global)"` → `"All (global)"` |

**Tidak ada berkas lain yang disentuh.** Keempat serializer dan kedua
schema yang memanggil `label_for()`/`choices()` tidak berubah sebaris
pun — mereka memang sudah membaca peta itu, dan sekarang peta itu
berbahasa Inggris.

#### CONFIRMED — yang tidak bergerak

- **Nilai enum tetap kode stabil.** `approver_type` tetap `"role"`,
  `approver_scope` tetap `"location"`, `status` tetap `"approved"`.
  Diverifikasi di payload API yang hidup: baris instance mengirim
  `status: "approved"` **dan** `status_label: "Approved"` —
  dua field, seperti sebelumnya.
- **Nol migration.** Peta ini hidup di luar `TextChoices`, jadi
  memperbaikinya tidak menerbitkan `AlterField`. `makemigrations`
  tidak diminta apa-apa.
- **Nol perubahan routing/approval.** `label_for()` hanya dipanggil
  dari `SerializerMethodField` dan `choices()`; tidak ada satu pun
  cabang logika yang membacanya.
- Satu label Indonesia memang **masih tertinggal di model**
  (`ApproverScope.TENANT = "tenant", "Seluruh Tenant"` di
  `models/step.py`). Sengaja tidak disentuh: memperbaikinya di model
  menerbitkan `AlterField` yang tidak mengubah satu byte pun data.
  Peta di `labels.py` menutupinya untuk jalur API — yang tersisa
  hanya `get_approver_scope_display()` di shell/admin.

#### TESTED

Diamati di aplikasi yang berjalan (Chrome headless + CDP), bukan dari
unit test:

| Layar | EN | ID |
|---|---|---|
| `/workflow/instances` status | Approved · Cancelled | Disetujui · Dibatalkan |
| `/workflow/steps` tipe penyetuju | Direct Manager · Role Holder | Atasan Langsung · Pemegang Peran |
| `/workflow/steps` cakupan | Company · Location | Perusahaan · Lokasi |
| `/workflow/steps` aktif | Active | Aktif |

**Nama step tetap apa adanya di kedua bahasa** — "Approved By (Atasan
Langsung)" adalah data tenant, dan ia memang tidak boleh ikut
diterjemahkan. Itu terbaca seperti kegagalan di log UAT; justru
sebaliknya.

`manage.py check` bersih.

#### OPEN

- **Label field (judul kolom) masih Indonesia untuk semua orang.**
  Berbeda dari label enum: yang ini ditulis langsung sebagai `label=`
  di `apps/workflow/api/*/schema.py` ("Alur Kerja", "Tipe Penyetuju",
  "Cakupan Peran", "Nama Tahap"). Gejalanya sama, permukaannya jauh
  lebih besar — dan **bukan hanya Workflow**: widget dashboard HR
  ("Jam Lembur", "Kehadiran Harian", "Lowongan Terbuka") datang dari
  schema backend dengan cara yang persis sama. Pantas jadi satu pass
  sendiri, bukan diselipkan di sini.
- `scope_label` tidak diterjemahkan frontend, dan itu disengaja:
  isinya campuran nama perusahaan/lokasi milik tenant dengan satu
  kalimat sistem. Memisahkannya berarti mengubah bentuk field.

---

### Multi-bahasa — Stage 2B/2C: format angka + UAT browser
Status: **SELESAI** — 9 Sep 2026. Sisi backend tidak berubah sama
sekali di tahap ini; dicatat di sini karena hasil UAT-nya membuktikan
kontrak backend Stage 1.

#### TESTED — dari browser sungguhan

`POST /auth/login/` → ganti bahasa → `PATCH /auth/me/` → refresh →
logout → login ulang. **16/16 pemeriksaan lulus.**

Yang paling berarti untuk sisi backend: **cookie `app_settings`
sengaja dipaksa ke `en` sebelum login ulang**, dan bahasanya tetap
kembali ke `id`. Itu membuktikan `User.language` yang menang, bukan
cookie browser — kontrak yang selama ini hanya diuji lewat unit test.

`GET /auth/me/` mengembalikan `language: "id"` sesudah diganti, dan
`"en"` sesudah dikembalikan. Rute tidak pernah memakai prefiks `/en`
atau `/id`.

`apps.accounts.tests.test_user_language` +
`apps.hr.tests.attendance_permission.test_permission_workflow` —
**20/20 OK** (189,3 s). `manage.py check` bersih.

Run pertamanya `FAILED (errors=1)` pada `tearDownClass` dengan
`out of shared memory / max_locks_per_transaction` — tabrakan dengan
run sesi lain, bukan kode. Kedua puluh test-nya sendiri lulus. Schema
`test` sisa dibersihkan lalu diulang bersih.

---

### Multi-bahasa (EN + ID) — fondasi
Status: **FRAMEWORK SELESAI, CAKUPAN BARU LAPIS BERSAMA.** 8 Sep 2026.
Sisi backend yang berubah **satu kolom preferensi**; nol perubahan pada
logika bisnis.

#### CONFIRMED

- **Tidak ada satu pun data bisnis yang diterjemahkan.** Nama pegawai,
  perusahaan, departemen, seksi, jabatan, lokasi, cost center, nomor
  dokumen, transaksi payroll/cuti/kehadiran/roster — semuanya tidak
  disentuh. Yang diterjemahkan hanya teks milik sistem, dan tempat
  tinggalnya di frontend (`app/i18n/locales/`), bukan di database.
- **Nilai enum tetap kode stabil.** `APPROVED` tetap `APPROVED` di
  API dan di database; yang diterjemahkan hanya labelnya, di layar.
  Tidak ada satu pun perbandingan yang memakai teks terjemahan.
- **Kontrak API tidak berubah bentuknya.** `MeSerializer` **menambah**
  satu field (`language`); tidak ada field yang diganti, dihapus, atau
  berubah artinya. Konsumen lama tidak terpengaruh.
- **Perilaku API tidak bergantung bahasa pemintanya.** Tidak ada
  `LocaleMiddleware`, tidak ada `Accept-Language` yang dibaca, tidak
  ada respons yang berbeda isi menurut bahasa. Bahasa dipilih dan
  dipakai **di klien**.
- **Zona waktu tidak ikut bergerak.** `TIME_ZONE` tetap `UTC`,
  `CELERY_TIMEZONE` tetap `Asia/Jakarta`. Diuji eksplisit.

#### IMPLEMENTED — backend

| Berkas | Perubahan |
|---|---|
| `config/settings/base.py` | `LANGUAGES = [("en", …), ("id", …)]` — sumber kebenaran daftar bahasa |
| `apps/accounts/models/user.py` | `User.language`, `choices=settings.LANGUAGES`, `default="en"` |
| `apps/accounts/migrations/0008_user_language.py` | `AddField` murni; tanpa data migration |
| `apps/accounts/api/auth/serializers.py` | `MeSerializer` +`language` (baca); `ProfileUpdateSerializer` +`language` (tulis) |

**Kenapa migration ini diperlukan:** preferensi bahasa harus ikut
orangnya, bukan ikut browsernya — orang yang login di komputer
rekannya harus mendapat bahasanya sendiri. Cookie saja tidak bisa
memberikan itu. Migration-nya `AddField` dengan default `"en"`: tidak
ada baris yang ditulis ulang, tidak ada FK yang berubah, dan seluruh
akun yang sudah ada tetap berbahasa Inggris sampai orangnya sendiri
mengubahnya.

#### TESTED

`apps/accounts/tests/test_user_language.py` — **10/10 OK** (84,8 s), tiap
skenario positif berpasangan dengan negatifnya: bahasa di luar daftar
ditolak 400 · `language` bukan jalan menaikkan wewenang
(`is_superuser` di payload yang sama diabaikan, jalur tulisnya tetap
`ProfileUpdateSerializer`) · PATCH satu kolom tidak menghapus nama/email
· yang tersimpan kode (`id`) bukan nama bahasanya · `TIME_ZONE` tidak
bergeser.

Regresi: `apps.accounts` **32/32 OK** (587,5 s) — termasuk
`test_data_scope_semantics` dan `test_view_permission_gate`, jadi
penambahan satu field ke `MeSerializer` tidak menggeser satu pun
perilaku cakupan data atau gerbang izin.

`manage.py check` bersih.

**Dua kegagalan pertama keduanya di test-nya, bukan di fiturnya**, dan
keduanya pantas dicatat karena akan berulang:

1. `APIClient()` polos mengirim `Host: testserver`, tidak cocok dengan
   domain tenant mana pun, jadi `TenantMainMiddleware` jatuh ke schema
   `public` — dan `auth_users` tidak ada di sana. Muncul sebagai
   `relation "auth_users" does not exist`, terbaca seperti migration
   yang belum jalan. Lebih jahat lagi: koneksinya **tetap** di
   `public` sesudahnya, jadi 8 test berikutnya ikut gagal di `setUp`.
   Pakai `APIClient(HTTP_HOST=self.tenant.get_primary_domain().domain)`.
2. Error validasi di API ini berbentuk amplop
   `{success, message, errors, status_code}`, bukan dict field datar
   bawaan DRF. Assertion-nya harus menunjuk `response.data["errors"]`.

#### OPEN

- **`apps/workflow/labels.py` mendahului fondasi ini dan sekarang
  bertabrakan dengannya.** Berkas itu menerjemahkan label enum workflow
  ke Bahasa Indonesia **di backend**, jadi label-label tersebut
  berbahasa Indonesia untuk **semua** pengguna — termasuk yang memilih
  English. Keputusannya benar untuk saat itu (belum ada i18n sama
  sekali); sekarang tempatnya sudah ada. Jalan keluarnya: kembalikan
  labelnya ke Inggris dan pindahkan terjemahannya ke katalog frontend
  `workflow.*` yang sudah disiapkan. **Sengaja belum dikerjakan** —
  itu perubahan pada 62 berkas hasil generate dan pantas jadi
  langkahnya sendiri.
- Pesan validasi/error DRF masih berbahasa campur (Indonesia di
  beberapa serializer, Inggris dari DRF). Belum ada mekanisme
  lokalisasi pesan error yang bisa dipakai ulang — lihat DEFERRED.
- Master seeded (jenis cuti, komponen payroll sistem) belum punya label
  terjemahan. Kode-nya sudah stabil, jadi jalur termurahnya adalah
  kunci katalog frontend per kode — belum dikerjakan.

#### DEFERRED — sengaja tidak dikerjakan di fase ini

- **Lokalisasi pesan error backend.** Butuh keputusan arsitektur
  tersendiri (`gettext` + `LocaleMiddleware`, atau kode error +
  katalog frontend). Menambahkannya sekarang berarti menyentuh setiap
  serializer sebelum ada satu pun mekanisme yang terbukti.
- **Kolom terjemahan di database.** Tidak ada satu pun yang
  ditambahkan, dan tidak ada `name_id` di mana pun. Kalau nanti master
  seeded memang butuh label tersimpan, polanya harus satu tabel
  terjemahan generik — bukan kolom ad-hoc di puluhan tabel.
- Master buatan tenant tetap tidak tersentuh.

---

### Katalog role — kembaran `*-SITE` dikonsolidasikan
Status: **SELESAI** — 15 Sep 2026. Migration
`accounts.0014_consolidate_site_roles`. **Bukan** perubahan arsitektur
authorization: nol perubahan pada `DataScopeService` atau kontrak
kewenangan.

`EXECUTIVE-SITE`→`EXECUTIVE`, `HR-ADMIN-SITE`→`HR-ADMIN`,
`HR-MANAGER-SITE`→`HR-MANAGER`, `KTT-SITE` di-rename `KTT`.

Sebabnya: bedanya dengan induknya memang **cuma cakupan** (daftar izinnya
sama persis), dan cakupan sudah tidak tinggal di `Role` — jadi sesudah
gelombang C keduanya tidak bisa dibedakan sama sekali. Dikerjakan
sebelum gelombang C, konsolidasi ini justru akan **melebarkan** akses
pemegangnya.

Kewenangan tidak dipindahkan: ia menempel pada `RoleAssignment`, jadi
mengganti `role_id` membawa mode, level, dan baris kewenangannya apa
adanya. Bentrokan pemegang ganda **ditinggalkan** (role sumber tetap
aktif) alih-alih ditebak.

**Bukti `demo`:** penugasan 37→37, baris kewenangan 30→30, digest
kewenangan-per-orang `cdf06f6d9423a6727a17151fbe54f007` **tidak
berubah**, nol duplikat, izin role target tidak bergeser, workflow
`HR-TR-SITE`/`HR-LEAVE-SITE` #5 tetap menemukan `SGA005`, seed idempoten
(dua kali jalan → cap identik). `test_role_catalogue.py` 10/10.

`ADMIN-DEPARTMENT` dan `ADMIN-SECTION` **belum disentuh** — keputusan
terpisah.

Detail: `docs/claude/role-authority.md` → "Pembersihan katalog role".

---

### Role Authority — FINAL WAVE C: skema cakupan lama dihapus
Status: **SELESAI** — 14 Sep 2026. Migration `accounts.0013_drop_legacy_data_scope`.

Rangkaian peralihan WHERE **ditutup**. Kolom `Role.data_scope_mode` /
`Role.data_scope_level` dan tabel `accounts_role_data_permission` /
`accounts_user_data_permission` tidak ada lagi. WHERE punya satu sumber:
kewenangan pada `RoleAssignment`.

| Langkah | Isi |
|---|---|
| C0 | Cacat classifier `CUTOVER_COMPLETE` diperbaiki — ia menuntut perbandingan lulus **dan** bahan bandingnya sudah tiada, dua syarat yang tidak bisa berlaku bersamaan |
| C1 | `demo` disahkan lewat perbandingan **hidup** sebelum apa pun dihapus: SAMA=232, GAINED=0, LOST=0, INTENDED_NARROWING=2 |
| C2 | 31 berkas test ditinjau satu per satu (bukan sapuan regex); 26 dikonversi, 4 berkas + 6 kelas dihapus, `test_authority_contract.py` dibuat |
| C3 | 2 service + 5 perintah peralihan dipensiunkan; diganti `audit_authority_hygiene` yang **tidak** bergantung skema lama |
| C4 | `Role.clean()`, `DataScopeMode`, kosakata seed, 49 sebutan prosa di 47 berkas. **`DataScopeLevel` tetap** |
| C5/C6 | `DeleteModel` ×2, `RemoveField` ×2, `RemoveConstraint` ×2 |

**Bukti pasca-penghapusan (`demo`, dibaca dari `information_schema`):**
tabel lama tidak ada, kolom lama tidak ada, penugasan **37**, baris
kewenangan **30**, digest keanggotaan
`8a6da25fc26a6e853564391d21e3f51f`, hygiene bersih — **sama persis**
dengan garis dasar pra-penghapusan.

**Yang menggantikan perkakas yang dipensiunkan:** `manage.py
audit_authority_hygiene` (+ `services/authority_hygiene.py`). Perkakas
lama menemukan penugasan tanpa kewenangan sebagai efek samping dari
pertanyaan yang punya tanggal kedaluwarsa; keadaan itu sendiri bisa
lahir besok dari kode baru, jadi pemeriksaannya dipisahkan dan
dipertahankan. Read-only, keluar bukan-nol kalau ada temuan.

**Tidak bisa dibalik.** Balikan bawaan migration mengembalikan kolom dan
tabel — kosong. Yang memulihkan akses cadangan database, bukan
`migrate ... 0012`.

**Penerapan produksi:** cadangkan → `audit_authority_hygiene` harus
bersih di tiap tenant → `migrate_schemas --tenant` → bandingkan jumlah
penugasan, baris kewenangan, dan digest. Tenant produksi **tidak ada**
di database pengembangan ini; verifikasinya persyaratan runbook, bukan
sesuatu yang bisa disimpulkan dari sini.

**Regresi:** accounts 166 OK; administration+uploads+reports+payroll 791
OK; hr+notifications+finance+scm 771 dijalankan dengan **6 merah** —
seluruhnya `apps/hr/tests/roster/test_roster_flow.py`, dan seluruhnya
**bom waktu tanggal**, bukan gelombang C. Fixture-nya mematok
`AS_OF = date(2026, 8, 1)` sementara penguncian segmen memakai
`timezone.localdate()`; sejak 2026-09-13 seluruh jadwalnya terkunci.
Dibuktikan dengan membekukan jam di 2026-08-05: **6 OK**. Belum
diperbaiki — perbaikannya menyentuh fixture Roster, di luar lingkup
gelombang C.

Detail lengkap: `docs/claude/role-authority.md` → "FINAL WAVE C".

---

### Role Authority — Stage 4J: kontrak test + pencabutan kopling struktural
Status: **SELESAI** — 13 Sep 2026. Nol migration. Skema lama masih utuh.

Dua penghalang gelombang C dicabut, plus utang test-nya dilunasi.

| Berkas | Perubahan |
|---|---|
| `apps/accounts/models/authority_types.py` | **baru** — `AuthorityResourceType`, rumah netral enum sumber daya |
| `apps/accounts/models/role_assignment.py` | `RoleAssignmentAuthority` memakai enum netral, tidak lagi meminjam dari model lama |
| `apps/accounts/models/data_permission.py` | `RoleDataPermission.ResourceType` tinggal alias |
| `apps/accounts/migrations/0011`, `0012` | **dibekukan** — `apps.get_model()` saja, nol impor aplikasi, nilai enum literal, salinan berdiri sendiri |
| `apps/accounts/tests/test_frozen_migrations.py` | **baru**, 10 test — statis + perilaku + schema tenant baru dari nol |
| 12 modul test (hr/payroll/reports/administration) | WHERE dinyatakan lewat `grant_role()`; 1 test kontrak lama dibalik |

**Nol migration dari pemindahan enum.** Nilai, label, dan urutannya
disalin persis, jadi autodetector tidak melihat selisih — tidak ada
`AlterField`, apalagi DDL.

**Kenapa pembekuan mendesak:** `django-tenants` memutar ulang seluruh
rantai migration untuk **tiap tenant baru**. Sesudah gelombang C
menghapus model lama, migration yang mengimpor service menggagalkan
pembuatan tenant — bukan sekadar riwayat.

**99 kegagalan fixture = 0.** Semuanya satu kelas: memberi role tanpa
menyebut WHERE, yang di bawah kontrak 4H memang gagal tertutup. WHERE
disalin dari deklarasi tiap fixture, tidak pernah dari nama role. Nol
defect produksi; nol assertion keamanan dilemahkan.

Detail: `docs/claude/role-authority.md` → "Stage 4J".

---

### Role Authority — Stage 4I: kesiapan penghapusan skema lama
Status: **SELESAI** — 13 Sep 2026. Nol migration. Skema lama **belum**
dihapus; yang dihapus ketergantungan non-runtime terakhir padanya.

| Berkas | Perubahan |
|---|---|
| `apps/accounts/api/data_permissions/` | **dihapus** — pohon read-only `RoleDataPermission` beserta rute dan modul schema-nya |
| `apps/accounts/api/urls.py` | rute `data-permissions/` dicabut |
| `apps/accounts/api/roles/{serializers,views}.py` | 4 field cakupan lama tidak dikirim lagi |
| `apps/accounts/management/commands/seed_data_scopes.py` | berhenti menulis `Role.data_scope_*` + `RoleDataPermission`; blok `EMPLOYEE` dan laporan "explicit tanpa baris" dibuang |
| `apps/hr/seeds/demo_org_scope.py` | `_ensure_bod_scope()` dibuang; `_ensure_roles()` tidak menulis kolom lama |
| `apps/accounts/management/commands/seed_legacy_scope_baseline.py` | **baru** — garis dasar lama, cutover-only, butuh `--apply` |
| `apps/accounts/management/commands/audit_legacy_retirement.py` | **baru** — inventaris read-only per tenant + vonis |
| `apps/accounts/services/cutover_audit.py` | `retirement_inventory()`, `classify_tenant()` |
| `apps/accounts/tests/test_legacy_schema_readiness.py` | **baru**, 22 test |
| FE `administration/security/` | tab "Data Permissions" + modulnya dihapus; layar Roles kehilangan 2 kolom, 2 filter, 2 field |

**Yang dijaga test, dan bentuk buktinya.** Seed produksi: nol sentuhan
ke tabel lama, nol `UPDATE` ke kolom lama — dari SQL yang benar-benar
dijalankan. `INSERT` sengaja **tidak** dihitung: selama kolomnya masih
ada di model, tiap baris `accounts_role` baru menyebutnya dengan bawaan
model, jadi menuntut nol `INSERT` berarti menuntut skemanya sudah
hilang — dan test yang tidak bisa hijau tidak menjaga apa pun. Yang
ditangkap sebagai gantinya keadaan sesudahnya: tidak satu pun role
berakhir dengan cakupan lama yang **dipilih**.

**Vonis tenant:** `demo` = `CUTOVER_READY` (37 penugasan, blank 0,
UDP aktif 0, `SAMA=232 GAINED=0 LOST=0 INTENDED_NARROWING=2`; masih ada
4 baris `RoleDataPermission` + 15 role bercakupan lama sebagai bahan
banding). Hanya ada satu tenant di lingkungan ini — perkakasnya yang
menggeneralisasi, bukan angkanya.

**Yang menahan gelombang C** (detail di dokumen domain):
`RoleAssignmentAuthority.resource_type` memakai enum milik
`RoleDataPermission`; migration 0011/0012 memanggil service yang hidup
sehingga pembuatan tenant baru akan gagal sesudah modelnya dihapus; 10
berkas test memakai `backfill_authority()` sebagai perbaikan fixture.

Detail: `docs/claude/role-authority.md` → "Stage 4I".

---

### Role Authority — Stage 4H: kontrak pembuatan penugasan
Status: **SELESAI.** 12 Sep 2026. Nol migration, nol kolom dihapus.

Ketergantungan terakhir pada model kewenangan lama dibuang. Sesudah 4G
runtime tidak membacanya sama sekali — tapi `Role.data_scope_*` dan
`RoleDataPermission` masih menentukan akses pada **satu momen**: saat
penugasan dibuat. Sekarang tidak lagi.

`Role` menjawab **WHAT** saja. WHERE dinyatakan pemanggil saat penugasan
dibuat. Yang tidak dinyatakan **tidak ada**.

#### Kontrak pembuatan — `roles: [id, ...]` tetap sah

| Bentuk entri | Artinya |
|---|---|
| `5`, `"5"`, objek `Role` | beri rolenya, **tanpa kewenangan** — lahir tertutup |
| `{"role": 5, "authority_mode": ..., "authority_level": ..., "authorities": [...]}` | beri rolenya **berikut** WHERE-nya, satu transaksi |

Boleh dicampur. Tidak ada bentuk yang diam-diam melebar: konfigurasi
yang belum selesai berakhir menutup. Penugasan yang **bertahan** tidak
pernah tersentuh — id telanjang berarti "tanpa kewenangan" hanya untuk
penugasan yang **baru**.

Kompatibilitas: kedua pemakai kontrak lama (`UserRolePanel` lewat
`/user-roles/save/`, dan `UserSerializer.roles`) tidak patah. Artinya
yang berubah, dan berubah ke arah tertutup.

#### UI — dua simpanan, dan itu aman

Langkah 1 (role) dan langkah 2 (kewenangan) tetap terpisah. Jendela di
antaranya sekarang **fail-closed**, bukan melebar, jadi tidak perlu
dijadikan atomik. Yang perlu diperbaiki justru pesannya: layar masih
mengatakan mode kosong "sementara mengikuti pengaturan cakupan lama
milik role ini" — benar sampai 4F, salah ke arah berbahaya sesudahnya.
Diganti peringatan amber, plus peringatan di langkah 1 yang menyebut
berapa role baru akan diberikan tanpa kewenangan.

#### Keputusan tiap pemanggil non-interaktif

| Pemanggil | Keputusan |
|---|---|
| `create_superadmin`, `security_roles` → SYSTEM-ADMIN | **fail closed** — penerimanya superuser, WHERE-nya tidak pernah dibaca |
| `security_roles` → EMPLOYEE | **EXPLICIT + `own`** |
| `payroll_uat` → FINANCE-MANAGER | **PLACEMENT/company** |
| `payroll_dashboard_uat` | **EXPLICIT + company**, sekarang atomik |
| `demo_*` seeds | tabel bersama `apps.accounts.seeds.role_authority` |
| `UserSerializer`, `.add()`/`.set()` | **fail closed** |

#### Yang dihapus

`apps/accounts/signals.py` + `AccountsConfig.ready()`,
`initialize_authority()`, `rederive_authority_for_roles()`, dan seluruh
panggilan `backfill_authority()` di seed produksi. Jebakan urutan seed
yang dilahirkan 4G hilang **bersama sebabnya** — tidak ada lagi yang
dibekukan dari `Role`, jadi tidak ada urutan yang perlu dijaga.

#### Bukti, bukan janji

`NoLegacyReadOnCreationTests` menangkap SQL yang benar-benar dijalankan
jalur pembuatan dan menolak yang menyentuh tabel/kolom lama. Role uji
sengaja dikonfigurasi `all` — kalau ada satu jalur yang masih
menurunkan, hasilnya tanpa batasan dan langsung ketahuan.

`SeedAuthorityAgreesWithLegacyConfigTests` menjaga `SEED_ROLE_AUTHORITY`
tetap sepakat dengan `seed_data_scopes`. Ia langsung berguna: menangkap
`HR-MANAGER-SITE` yang terlewat saat tabelnya ditulis.

#### Pernyataan yang sekarang benar

> `Role.data_scope_*` dan `RoleDataPermission` hanya dibaca perkakas
> migrasi/cutover dan kode kompatibilitas historis.

Detail: `docs/claude/role-authority.md` → "Stage 4H".

---

### Role Authority — Stage 4G: kosong dihapus, fallback legacy dibuang
Status: **SELESAI.** 12 Sep 2026. Satu migration data (0012), nol kolom
dihapus.

Lubang terakhir yang dicatat 4F ditutup. Rangkaiannya dulu pendek dan
seluruhnya normal: `Role` bawaannya `explicit` tanpa baris →
`assign_roles()` membuat penugasan `authority_mode` **kosong** → kosong
berarti "ikut `Role`" → arti **lama** `explicit` tanpa baris adalah
**tanpa batasan**. Role baru dibuat dari layar, diberikan dari layar,
membuka **seluruh tenant** sampai ada yang menjalankan backfill.

#### Ditutup dari dua sisi, dan keduanya perlu

| Sisi | Bagaimana |
|---|---|
| **Saat dibuat** | kewenangan diturunkan dari `Role` begitu penugasannya ada — di jalur mana pun |
| **Saat dibaca** | `authority_mode` kosong berarti **tertutup**, dengan `logger.warning` menyebut siapa dan role apa |

Satu sisi saja tidak cukup: yang pertama bisa dilewati jalur baru yang
ditulis orang besok, yang kedua tidak menolong penugasan yang sudah
kosong di tenant lama.

#### Kenapa lewat sinyal, bukan cuma lewat service

`User.roles` tetap M2M biasa: `user.roles.add(role)` menulis ke tabel
keanggotaan **tanpa melewati `assign_roles()` sama sekali**. Perintah
manajemen, seed, dan test memakai jalur itu. Menambal pemanggilnya
satu-satu adalah janji yang tidak bisa ditepati — `.add()` berikutnya
yang ditulis orang tidak tahu ada janji itu — jadi yang dijaga
**tabelnya**: `m2m_changed` `post_add` di `apps/accounts/signals.py`,
didaftarkan dari `AccountsConfig.ready()`.

`assign_roles()` tetap memanggil `initialize_authority()` sendiri:
`bulk_create` tidak membangkitkan sinyal apa pun.

Efek samping yang disadari: begitu ada pendengar `m2m_changed` pada
model through-nya, Django meninggalkan jalur `bulk_create` cepatnya
supaya bisa menyebutkan id yang ditambahkan. Itu memang harganya — dan
memang yang dibutuhkan.

#### Jebakan urutan yang lahir dari perbaikan ini

Karena kewenangan dibekukan **saat penugasan dibuat**, seed yang memberi
role lebih dulu lalu mengatur cakupan role-nya kemudian akan membekukan
nilai yang salah. `EMPLOYEE` contoh persisnya: `seed_security_roles`
memberikannya ke tiap akun, `seed_data_scopes` baru sesudahnya
menyatakan role itu terbatas pada data sendiri. Tanpa penanganan, setiap
pegawai memegang `EXPLICIT` tanpa baris — **tidak melihat apa pun,
termasuk datanya sendiri**.

Ditangani `rederive_authority_for_roles(role_ids)`: `seed_data_scopes`
mencatat role yang konfigurasinya benar-benar diubahnya (`touched`) dan
menurunkan ulang **hanya** penugasan role-role itu. Ia menimpa, dan itu
memang arti menjalankan seed cakupan. Dikunci `SeedOrderingTests`, yang
juga menyatakan bahwa `backfill_authority()` biasa **tidak** cukup —
jadi ini bukan masalah yang hilang sendiri.

#### Berkas

| Berkas | Perubahan |
|---|---|
| `apps/accounts/signals.py` | **baru** — `m2m_changed` `post_add` pada `User.roles.through`, dua arah |
| `apps/accounts/apps.py` | `ready()` mendaftarkan sinyalnya |
| `apps/accounts/services/authority_backfill.py` | `_derive()` jadi satu-satunya tempat pemetaan; `initialize_authority()`, `rederive_authority_for_roles()`, `backfill_authority()` memakainya bersama |
| `apps/accounts/services/role_assignment.py` | `assign_roles()` memanggil `initialize_authority()` sesudah `bulk_create` |
| `apps/accounts/scoping.py` | `_legacy_authority()` + `_legacy_bucket()` **dihapus**; impor `DataScopeMode` dihapus; kosong → `continue` + warning |
| `apps/accounts/migrations/0012_…` | `backfill_authority()` per tenant, idempoten, tidak menimpa |
| `apps/accounts/management/commands/seed_data_scopes.py` | mencatat `touched`, menurunkan ulang role yang diaturnya |
| `apps/payroll/management/commands/payroll_dashboard_uat.py` | gelombang A — tidak lagi menulis `RoleDataPermission`/`Role.data_scope_mode`; pakai `set_authority()` |
| `apps/accounts/api/data_permissions/` | gelombang A — rute `save/`, view, serializer, `_retired_save()` **dibuang** (bukan lagi 403); pohon baca tetap |

#### Gerbang `demo`

`SAMA=232 GAINED=0 LOST=0 INTENDED_NARROWING=2 SIAP` — sama persis
dengan 4D/4F. Keanggotaan **tidak bergeser**: 37 baris, md5
`81a86c977c3e6c4ad173cc9ace01ac2b`, identik sejak sebelum 4B.
`authority_mode` kosong = 0, `UserDataPermission` aktif = 0.

#### Masih terbuka (dilaporkan, bukan diselesaikan)

- **`Role.data_scope_*` masih load-bearing** sebagai sumber turunan saat
  penugasan dibuat. Menghapus kolomnya (gelombang C) berarti memindahkan
  pilihan nilai awal itu ke layar Role Assignment lebih dulu — kalau
  tidak, penugasan baru tidak punya apa pun untuk diturunkan dan setiap
  role baru jadi tertutup total.
- **~90 komentar** menulis "(`RoleDataPermission`)" sebagai singkatan
  untuk penyaringan per baris. Tidak ada yang membaca modelnya; yang
  salah cuma namanya. Dibiarkan — 90 berkas demi penggantian kata
  menambah risiko tanpa menambah keamanan.

Detail: `docs/claude/role-authority.md` → "Stage 4G".

---

### Role Authority — Stage 4F: pensiun permukaan kewenangan lama
Status: **SELESAI.** 12 Sep 2026. Nol kolom/tabel dihapus.

Audit + pengerasan deprecation. `UserDataPermission` tidak bisa ditulis
lagi dari jalur produksi (`save()` **dan** `bulk_create` — yang terakhir
tidak membangkitkan sinyal apa pun dan justru itu yang dipakai seed),
dengan `allow_user_data_permission_write()` sebagai pintu perkakas.
Permukaan penyuntingan lama ditutup: field cakupan Role jadi read-only,
`DataPermissionService.save()` menolak. Seed tidak lagi bergantung pada
propagasi legacy.

Rencana penghapusan tiga gelombang ditulis, **tidak** dijalankan.
Gelombang A dieksekusi di 4G.

Detail: `docs/claude/role-authority.md` → "Stage 4F".

---

### Role Authority — Stage 4E: administrasi kewenangan penugasan
Status: **SELESAI.** 11 Sep 2026. Nol migration, nol perubahan semantik.

WHERE sekarang bisa diatur dari layar, bukan cuma dari shell.

#### Dua pertanyaan, dua endpoint, dan urutannya disengaja

| Endpoint | Menjawab |
|---|---|
| `POST /api/accounts/user-roles/save/` | role apa — kontrak `roles: [id, ...]` **tidak berubah** |
| `GET /api/accounts/user-roles/authority/?user=` | kewenangan tiap penugasan + `resource_types` |
| `POST /api/accounts/user-roles/authority/` | kewenangan **satu** penugasan |

Digabung jadi satu simpanan, orang dipaksa menentukan kewenangan untuk
role yang belum diputuskan diberikan; dan kegagalan di tengah
menyisakan sebagian tersimpan tanpa ada yang tahu bagian mana. Karena
itu satu penugasan per permintaan.

#### Validasi (di service, bukan serializer)

| Mode | `authority_level` | baris |
|---|---|---|
| `UNRESTRICTED` | wajib kosong | wajib kosong |
| `PLACEMENT` | **wajib diisi** | wajib kosong |
| `EXPLICIT` | wajib kosong | **nol sah = tanpa kewenangan** |

Ditegakkan di service karena perintah manajemen dan seed menulis lewat
jalur yang sama; aturan yang cuma hidup di serializer tidak berlaku
bagi mereka.

Kewenangan **tidak bisa** ditempelkan ke role yang tidak dipegang —
kalau bisa, layar ini jadi pintu kedua untuk memberi role, dan pintu
kedua itu tidak melewati satu pun aturan pintu pertama.

#### Baris `own` dilindungi secara struktural

22 penugasan EMPLOYEE membawa baris `own`. Layar tidak menyodorkannya
(ia bukan pilihan organisasi), jadi penyimpanan yang "mengganti seluruh
daftar" akan **mencabut hak tiap orang atas datanya sendiri** dalam
satu kali Simpan. Karena itu jenis yang dilindungi dikeluarkan dari
rekonsiliasi sepenuhnya: klien tidak mengirimnya, server tidak
menghapusnya, dan ia dikembalikan di field `preserved` supaya layar
bisa menyatakan bahwa ia ada.

#### Layar

`UserRolePanel.vue` diperluas — bukan layar keamanan kedua. Dua
langkah bernomor: **1. Role yang dipegang** (centang, seperti
sebelumnya), lalu **2. Kewenangan tiap role**. Mode `EXPLICIT` tanpa
baris memunculkan peringatan kuning **"Tanpa kewenangan data."**
Penugasan yang `authority_mode`-nya kosong ditandai "belum ditentukan
— sementara mengikuti pengaturan cakupan lama milik role ini".

Pemilih nilai memakai 7 jenis yang punya konsumen nyata;
`warehouse`/`project`/`iup` **tidak** disodorkan — ketiganya ada di
enum tapi belum punya model yang dipetakan, jadi menawarkannya cuma
menjanjikan kewenangan yang tidak menyaring apa pun. Daftarnya datang
dari server (`resource_types`), bukan disalin di layar.

`Role.data_scope_mode` dan `RoleDataPermission` **tidak** dijadikan
antarmuka utama: keduanya menjawab "role ini umumnya seluas apa", jadi
menyuntingnya menggeser kewenangan setiap pemegangnya sekaligus.

#### Seed

`demo_org_scope`, `demo_workforce`, dan `demo_employees` memanggil
`backfill_authority()` di akhir. Penugasan hasil seed lahir dengan
`authority_mode` kosong, dan tenant yang menyisakannya ditolak
`audit_assignment_cutover` — seed yang tidak menurunkannya membuat
tenant peragaan gagal gerbangnya sendiri.

#### BUKTI — `demo`

Keanggotaan **37 baris, md5 `81a86c97…`** — identik sejak sebelum
Stage 4B. Gerbang cutover tetap `GAINED=0 LOST=0
INTENDED_NARROWING=2`, `SIAP`.

Baris kewenangan **30**: BOD 6 + EXECUTIVE 2 (hasil migrasi 4D) +
EMPLOYEE `own` 22.

---

### Role Authority — Stage 4D: peralihan WHERE ke kewenangan penugasan
Status: **SELESAI.** 11 Sep 2026. Dua penyempitan disengaja, nol pelebaran.

`DataScopeService` kini menghitung WHERE dari `RoleAssignment`, bukan
dari `Role`. `UserDataPermission` **tidak lagi dibaca saat runtime**.

#### Jalur baca sekarang

```
for_user(user, permission)
  -> _assignments_granting(user, permission)   # penugasan yang ROLE-nya
                                               # memberi izin itu
  -> per penugasan:
       kosong       -> _legacy_authority(role) + _legacy_bucket(role)
       UNRESTRICTED -> unrestricted
       PLACEMENT    -> _placement(user)[authority_level]
       EXPLICIT     -> _authority_bucket(assignment)
                       (nol baris -> tidak menyumbang apa pun)
  -> UNION antar penugasan; nol bucket -> denied
```

`ROLE_AWARE_DATA_SCOPE` artinya **tidak berubah**: ia tetap menentukan
apakah cakupan disaring ke penugasan yang memberi izin yang diminta.

#### Satu cacat nyata yang ditemukan test, bukan pengukuran

Jalur kompatibilitas `authority_mode` kosong sempat salah: modenya
diambil dari `Role`, tapi **bucket-nya dibaca dari penugasan** — yang
memang belum punya baris kalau belum di-backfill. Akibatnya role
`explicit` berbaris jatuh jadi `EXPLICIT` tanpa baris, lalu ditutup
oleh aturan fail-closed-nya sendiri. Jalur yang justru dibuat supaya
"tidak ada yang berubah" malah menutup semuanya.

`demo` tidak bisa memperlihatkannya — backfill menyisakan nol kosong,
dan gerbangnya menuntut kosong = 0. **Suite test yang menangkapnya**
(30 merah), dan itu memang satu-satunya yang bisa: jalur itu cuma ada
untuk keadaan yang `demo` sudah tidak punya. Diperbaiki dengan
`_legacy_bucket(role)`.

#### `demo.gmho` — sebelum dan sesudah

| | sebelum | sesudah |
|---|---|---|
| EXECUTIVE | `PLACEMENT`/company (MMR dari penempatan) | `EXPLICIT` {MMR, MLS} |
| EMPLOYEE | `EXPLICIT` {own} | `EXPLICIT` {own} |
| `UserDataPermission` | 1 baris (MLS) | **0** (soft-delete) |

MMR **dimaterialkan lebih dulu** dari penempatannya sebelum modenya
berubah — tanpa itu konversi akan mencabut kewenangan yang sedang
dipakai. Harganya disadari: `EXPLICIT` tidak lagi mengikuti penempatan
kalau `gmho` pindah company.

#### INTENDED_NARROWING — dua, keduanya kebocoran yang ditutup

1. `demo.gmho` + `payroll.view_payslip` + MLS
2. `demo.gmho` + `hr.view_attendancepermission` + MLS

Aturannya **atribusi, bukan daftar izin**: baris MLS diatribusikan ke
penugasan EXECUTIVE, jadi kewenangan MLS hanya berlaku untuk izin yang
diberi EXECUTIVE. Kedua izin di atas hanya diberi `EMPLOYEE` — dulu
ikut terbuka karena baris per-orang melebarkan setiap izin sekaligus.
Tidak satu pun izin ditambahkan ke EXECUTIVE untuk menghijaukan
perbandingan.

#### Perbandingan cakupan terhitung — `demo`

`SAMA=232  GAINED=0  LOST=0  INTENDED_NARROWING=2`, ditambah 6
`BERUBAH` yang **terbukti** setara: `company{2} OR company{3}` menjadi
`company{2,3}`, himpunan nilai yang diterima identik.

Perbandingan tingkat **baris** sengaja tidak dipakai sebagai gerbang:
ia sempat memulangkan 0/0 pada 270 kombinasi semata karena company MLS
kosong.

#### Alat yang bisa dipakai ulang

- `audit_assignment_cutover --schema X --expect-narrowing user:perm`
  — gerbang kesiapan + perbandingan cakupan, keluar bukan-nol kalau
  belum siap.
- `migrate_user_data_permission --schema X --user U --role R
  --resource-type T --resource-id N [--apply]` — sasarannya **disebut**,
  tidak ditebak.
- `backfill_assignment_authority --force` — sinkronisasi ulang sebelum
  peralihan.

#### Masih terbuka

`Role.data_scope_*`, `RoleDataPermission`, `UserDataPermission` masih
ada (sumber backfill + pembanding). `ADMIN-SECTION`,
`warehouse`/`project`/`iup`, dan konsolidasi role tetap terbuka.

---

### Role Authority — Stage 4D.0: audit kesiapan cutover
Status: **AUDIT SELESAI. Satu blocker tersisa.** 11 Sep 2026.
Nol perubahan produksi.

Simulator pembaca 4D ditulis **terpisah** dari `DataScopeService`
(`scratchpad/sim4d.py`, `audit4d_*.py`) — tidak satu baris pun kode
produksi diubah agar perbandingannya lulus.

#### Kesetaraan per penugasan — `demo`

**37 dari 37 penugasan setara.** Nol selisih mode, level, maupun baris.

| Blocker | Jumlah |
|---|---|
| `authority_mode` kosong | **0** |
| legacy EXPLICIT + nol `RoleDataPermission` | **0** role / **0** penugasan |
| assignment EXPLICIT + nol baris kewenangan | **0** |
| baris `UserDataPermission` | **1** |
| `resource_type` kewenangan tanpa konsumen | **0** baris (enum masih punya 3) |
| penugasan legacy ≠ baru | **0** |

#### Kenapa perbandingan tingkat BARIS menyesatkan

Membandingkan himpunan baris memberi **0 GAINED / 0 LOST** pada 270
kombinasi (30 akun × 9 resource) — dan angka itu **menipu**. Company
MLS di `demo` punya **nol pegawai dan nol data**, jadi baris
`UserDataPermission` milik `gmho` menunjuk company kosong. Yang diukur
jadi ketiadaan data, bukan kesetaraan aturan.

Yang benar membandingkan **cakupan terhitung**, dan itu tidak
tergantung isi tabel: **5 dari 150 kombinasi berbeda, seluruhnya
`demo.gmho`**, seluruhnya akibat baris yang belum dimigrasikan.

#### `gmho` → company MLS: bukti dan rekomendasi

| Izin | EXECUTIVE | EMPLOYEE | kalau MLS dipindah ke EXECUTIVE |
|---|---|---|---|
| `hr.view_candidate` | YA | tidak | pulih |
| `hr.view_employee` | YA | YA | pulih |
| `hr.view_employeedocument` | YA | YA | pulih |
| `hr.view_employeeleave` | YA | YA | pulih |
| `payroll.view_payslip` | **tidak** | YA | **tidak pulih — dan memang tidak boleh** |

Baris terakhir bukti kebocoran atribusi yang selama ini cuma bisa
dijelaskan dengan membaca kode. `EXECUTIVE` **tidak** memberi
`payroll.view_payslip`; `EMPLOYEE` memberi (untuk slip sendiri). Satu
baris `UserDataPermission` yang dimaksudkan untuk pengawasan eksekutif
MLS karena itu ikut membuka **seluruh slip gaji MLS** lewat role
`EMPLOYEE`-nya. Cakupan legacy `gmho` untuk `view_payslip` adalah
`company=3 + own` — company MMR dari penempatannya **tidak** muncul,
yang membuktikan akses itu datang semata dari baris per-orang.

**Rekomendasi (tidak dijalankan):** pindahkan ke penugasan
**EXECUTIVE** (`assignment#182`), bukan EMPLOYEE. Konsekuensinya harus
disadari: EXECUTIVE kini `PLACEMENT`/company, dan memuat dua company
menuntutnya jadi `EXPLICIT {MMR, MLS}` — cakupannya berhenti mengikuti
penempatan `gmho` kalau ia pindah company. Hilangnya akses slip gaji
MLS adalah **penyempitan yang disengaja**, bukan regresi.

#### `--force` sebelum perbandingan akhir

37 penugasan, 37 diturunkan ulang, 0 baris dibuat, 0 dibuang, PK dan
mode identik.

---

### Role Authority — Stage 4C: penyimpanan kewenangan + backfill
Status: **SELESAI.** 11 Sep 2026. Nol perubahan perilaku otorisasi.

Kewenangan per penugasan **disimpan**, belum dibaca. Sumber kebenaran
masih `Role`/`RoleDataPermission`/`UserDataPermission`; peralihan
pembacanya Stage 4D.

#### Model

`RoleAssignment` + `authority_mode` (`AuthorityMode`) dan
`authority_level`; anak `RoleAssignmentAuthority(assignment,
resource_type, resource_id)` dengan unik (assignment, type, id).

`AuthorityMode` sengaja bukan salinan `DataScopeMode`:
`PLACEMENT` menggantikan `own` — kata "own" sudah dipakai
`ResourceType.OWN` untuk gagasan yang sama sekali lain (data diri
sendiri), dan satu kata untuk dua arti adalah cara termurah membuat
orang salah membaca aturan keamanan.

#### Tiga keadaan, dan dua di antaranya mudah tertukar

| `authority_mode` | Arti |
|---|---|
| **kosong** | belum ditentukan — **ikut Role** (keadaan transisi) |
| `EXPLICIT` + **nol** baris | **tanpa kewenangan**, fail-closed |
| `UNRESTRICTED` / `PLACEMENT` / `EXPLICIT`+baris | sebagaimana namanya |

Kosong **bukan** sama dengan `EXPLICIT` tanpa baris. Yang satu "belum
diatur", yang satu lagi "memang tidak boleh apa-apa"; menyamakannya
akan mengunci orang dari pekerjaannya tanpa satu pun pesan. Penugasan
baru sesudah backfill sengaja dibiarkan kosong supaya tetap mengikuti
Role sampai 4D — `assign_roles()` **tidak** menyetel mode saat membuat
baris, karena itu akan membekukan konfigurasi role pada saat itu.

#### Peta backfill

| `Role.data_scope_mode` | kewenangan penugasan |
|---|---|
| `all` | `UNRESTRICTED` |
| `own` | `PLACEMENT`, level disalin |
| `explicit` | `EXPLICIT` + baris `RoleDataPermission` disalin ke tiap pemegang |

#### Selisih arti yang SENGAJA dibiarkan terlihat

`explicit` tanpa baris berarti **tanpa batasan** pada `Role`, dan
**tanpa kewenangan** pada penugasan. Backfill menyalin apa adanya —
**tidak** dipetakan jadi `UNRESTRICTED`. Menambalnya akan memindahkan
kebocorannya ke model baru secara diam-diam; dibiarkan terlihat supaya
4D bisa mengukurnya.

`demo`: **0 role** dan **0 penugasan** terdampak. Tapi
`Role.data_scope_mode` **default-nya `explicit`**, jadi role baru yang
dibuat tanpa mengatur cakupan lahir dalam keadaan itu — angkanya
snapshot, bukan sifat tetap. **Tiap tenant wajib diukur ulang tepat
sebelum cutover 4D.** Angkanya dilaporkan
`backfill_assignment_authority` sebagai `explicit_without_rows`.

#### Membeku sesudah diisi

Kewenangan yang sudah terisi tidak ikut berubah kalau Role disunting.
Tidak ada akibatnya di 4C (tidak ada pembaca), tapi role yang disunting
antara 4C dan 4D diam-diam tidak berlaku saat pembacanya dipindah.
Karena itu backfill juga jadi perintah:
`backfill_assignment_authority --force` untuk sinkronisasi ulang tepat
sebelum cutover.

#### BUKTI — `demo`

| | sebelum | sesudah |
|---|---|---|
| baris `auth_users_roles` | 37 | **37** |
| md5 `(id\|user_id\|role_id)` | `81a86c97…` | **`81a86c97…`** |
| pasangan user-izin | 4914 | **4914** |
| GAINED / LOST | — | **0 / 0** |

Backfill: 7 `UNRESTRICTED`, 6 `PLACEMENT` (2 company + 4 location),
24 `EXPLICIT`; **28 baris kewenangan** (BOD 2×3, EMPLOYEE 22×`own`);
`explicit_without_rows` = **0**; nol penugasan kosong tersisa.

Jalan kedua tanpa `--force`: 37 dilewati, nol perubahan. Dengan
`--force`: 37 diturunkan ulang, 0 dibuat, 0 dibuang, isi identik.

#### Catatan guard yang digeser

`test_the_membership_table_has_no_extra_columns_yet` dari Stage 4B
**gagal** di stage ini — memang tugasnya. Ia menuntut bentuk
`{id, user, role}` supaya penambahan kolom jadi keputusan yang
tercatat. Batasnya dinyatakan ulang di tempat 4C meletakkannya, dan
ditambah guard baru: `DataScopeService` **belum boleh** menyebut
`authority_*` maupun `RoleAssignmentAuthority`.

#### Masih terbuka (dilaporkan, tidak diselesaikan di 4C)

- `UserDataPermission` belum dimigrasikan.
- `ADMIN-SECTION` section-vs-location masih terbuka.
- `warehouse` / `project` / `iup` masih tanpa pemakai.
- Perilaku legacy `EXPLICIT`+nol = tanpa batasan masih berlaku di
  `DataScopeService` sampai 4D.

---

### Role Authority — Stage 4B: keanggotaan user-role jadi eksplisit
Status: **SELESAI.** 11 Sep 2026. Nol baris dipindahkan, nol kolom
ditambahkan, nol DDL.

Fondasi saja. `User.roles` yang tadinya M2B implisit kini melalui
`accounts.RoleAssignment` di atas tabel **yang sudah ada**,
`auth_users_roles`. Gunanya baru terasa di Stage 4C: kewenangan per
penugasan butuh tempat menempel, dan keanggotaan bikinan Django tidak
punya tempat itu. **Kewenangan belum ditambahkan di stage ini** —
dikunci test `test_the_membership_table_has_no_extra_columns_yet`.

#### Kenapa migration-nya berstatus saja

`0009` memakai `SeparateDatabaseAndState` dengan `database_operations`
kosong. Dijalankan apa adanya, `CreateModel` akan `CREATE TABLE` tabel
yang sudah berisi data, dan `AlterField` pada M2M akan **membuang lalu
membuat ulang tabelnya** — seluruh keanggotaan hilang. `sqlmigrate`
memulangkan `-- (no-op)`.

Yang membuatnya sah: model eksplisitnya dibuat identik dengan through
model bikinan Django — nama field `user`/`role`, `id` `BigAutoField`,
dan `unique_together` (bukan `UniqueConstraint`) supaya nama
constraint-nya sama. Selisih satu-satunya `related_name`, yang tidak
menyentuh skema.

#### Koreksi terhadap Stage 4A

Dugaan Stage 4A bahwa `.set()` membuang lalu membuat ulang baris yang
tetap dipegang **salah**. Django 6 dengan `clear=False` (bawaannya)
menghitung selisihnya sendiri; PK baris yang bertahan tidak berubah.
Dibuktikan langsung dan dikunci `RetainedRowTests`.

Yang memang rapuh bukan `.set()`, melainkan jalan id sampai ke sana.
`UserRoleService.save()` menelan id yang tidak bisa jadi angka lalu
menyaring sisanya dengan `filter(pk__in=...)` — dua-duanya membuang id
**diam-diam**. Karena daftar yang dikirim adalah daftar **utuh**, id
yang terbuang tidak berarti "abaikan" melainkan **"cabut role itu"**.
Satu id kedaluwarsa di layar, atau satu role yang baru di-soft-delete,
dan penyimpanan yang menjawab sukses justru mencabut kewenangan orang.

Sekarang id yang tidak dikenal **ditolak** (400), dan jawabannya
menyebut `added`/`removed`/`kept` — pencabutan kewenangan tidak boleh
jadi efek samping yang senyap.

#### Berkas

| Berkas | Perubahan |
|---|---|
| `apps/accounts/models/role_assignment.py` | **baru** — `RoleAssignment` |
| `apps/accounts/migrations/0009_...` | **baru** — status-saja |
| `apps/accounts/services/role_assignment.py` | **baru** — `assign_roles()` |
| `apps/accounts/models/user.py` | `through=` |
| `apps/accounts/api/user_roles/services.py` | lewat helper |
| `apps/accounts/api/user_roles/views.py` | `UnknownRoleError` → 400 |
| `apps/accounts/api/users/serializers.py` | dua `.set()` lewat helper |
| `apps/accounts/tests/test_role_assignment.py` | **baru** — 19 test |

Empat `.set()` di seed/UAT **ditinjau, sengaja dibiarkan**: semuanya
mengoper objek `Role` hasil resolusi kode, bukan input pengguna, jadi
tidak ada jalur pembuangan id diam-diam.

#### BUKTI — `demo`

| | sebelum | sesudah |
|---|---|---|
| baris `auth_users_roles` | 37 | **37** |
| md5 `(id\|user_id\|role_id)` | `81a86c97…` | **`81a86c97…`** |
| pasangan user-izin | 4914 | **4914** |
| akun bertambah akses | — | **0** |
| akun kehilangan akses | — | **0** |

`accounts` ada di `TENANT_APPS` saja — `public` tidak punya tabel ini,
jadi perbandingan di atas mencakup 100% baris keanggotaan.

#### REGRESI

| Suite | Hasil |
|---|---|
| `test_role_assignment` (baru) | **19/19 OK** |
| `apps.accounts.tests` | **92/92 OK** |
| `test_view_permission_gate` | **7/7 OK** |
| `apps.hr.tests.attendance_permission` | **64/64 OK** |
| `test_ho_leave_workflow` | **22/22 OK** |
| `test_leave_request_api` | **12/12 OK** |

`apps/workflow/tests.py` masih stub bawaan Django (0 test) — perilaku
approval diuji dari suite HR di atas, bukan dari sana.

---

### Enterprise Data Access Scope — Stage 3B.2: sisa permukaan baca
Status: **SELESAI. Dua YELLOW terakhir ditutup, dua BLOKIR dilaporkan,
regresi sah 594/594.** 10 Sep 2026. Nol migration.

#### Pelamar (`hr.Candidate`)

`Candidate` tidak menyimpan satu pun kolom organisasi. Yang
menghubungkannya ke organisasi **lowongan yang dilamarnya** — dan
`JobVacancy` memang membawa company/branch/location/division/department.
Relasinya sudah ada sejak awal; yang belum ada cuma pemakaiannya untuk
menjawab "pelamar siapa yang boleh saya lihat". Nol migration.

- `require_view_permission` → `hr.view_candidate`, izin yang **sudah
  ada** dan sudah dipegang 9 dari 30 akun `demo` (BOD, EXECUTIVE,
  HR-ADMIN/MANAGER beserta kembaran site-nya, HRGA). Tidak ada izin
  baru yang dibuat.
- `data_scope` lewat `vacancy__*`; `JobVacancy` dan
  `CandidateInterview` ikut, karena catatan wawancara memuat orang yang
  sama.
- **`vacancy` boleh kosong.** Pelamar lepas tidak punya jalur
  organisasi, dan `DATA_SCOPE_INCLUDE_NULL=False` membuatnya **tidak**
  terlihat bagi pemegang cakupan terbatas. Itu arah kegagalan yang
  benar: tidak adanya otoritas yang bisa dihitung tidak berarti
  terbuka.
- Berkas lamaran **tidak** dijaga terpisah — ia menyempit karena
  induknya menyempit (Stage 3B.1). Tidak ada satu pun nama model bisnis
  yang ditambahkan ke `apps/uploads`.

#### Riwayat import (`imports.ImportJob`)

**WHAT diturunkan dari sasarannya.** `ImportJob.module` menyimpan
`framework_module` resource yang diimpor, dan kunci itu sudah jadi
penghubung resmi antara layar, endpoint, dan izinnya (161 modul
terdaftar). Aturannya: boleh membaca riwayat import sebuah resource
kalau boleh membaca resource itu — yang mencegah pengimpor HR membaca
riwayat import Finance tanpa menciptakan satu izin lebar baru.

Sengaja **mencerminkan**, bukan lebih ketat: modul yang bacanya memang
terbuka tetap terbuka riwayatnya. Catatan tentang sebuah tabel tidak
boleh lebih rahasia daripada isi tabelnya.

**WHERE: TERBLOKIR.** `ImportJob` tidak punya kolom organisasi sama
sekali, dan `profile_code` disimpan sebagai teks — bukan FK ke
`ImportProfile` — jadi tidak bisa diandalkan sebagai jalur otoritas.
Yang berlaku sementara: **milik sendiri, atau modul yang boleh
dibaca.** Keduanya terbukti dari skema yang ada.

Otoritasnya dijawab `ImportJob.readable_for(user)` — hook baru di
`framework.authority` untuk model yang tidak dilayani viewset. Lewat
hook itulah `source_file` ikut menyempit, dan lewat itu pula
pengecualian `INHERIT_AUTHENTICATED` di `apps/uploads` **dihapus**.

#### IMPLEMENTED

| Berkas | Perubahan |
|---|---|
| `apps/hr/api/recruitment/scope.py` | **baru** — peta cakupan pelamar/lowongan/wawancara |
| `apps/hr/api/recruitment/views.py` | gerbang izin + cakupan untuk tiga viewset |
| `apps/framework/authority.py` | `model_for_module()`, `may_read_model()`, hook `readable_for()` |
| `apps/imports/authority.py` | **baru** — `readable_jobs()` |
| `apps/imports/models/job.py` | `readable_for()` |
| `apps/imports/api/views.py` | lima queryset `ImportJob` lewat satu jalur |
| `apps/uploads/services/access_service.py` | `INHERIT_AUTHENTICATED` dihapus |
| 9 registry lookup | cakupan + minimisasi payload |
| 10 berkas pemanggil `DataScopeService` | `required_permission` |

#### CONFIRMED — `demo`

Dropdown, mode role-aware, **0 akun bertambah di mana pun**:

| Lookup | total | menyempit |
|---|---|---|
| `employee-leaves` | 7 | **22/30** |
| `site-rotations` | 6 | **17/30** |
| `rotation-periods` | 152 | **17/30** |
| `numbering-sequences` | 22 | 4/30 |
| `fiscal-years` | 3 | 2/30 |

Dashboard HR tidak kehilangan satu baris pun (`hr.view_employee`
dipegang 30/30) — nol kehilangan tak disengaja.

`ImportJob` menyempit **0** di `demo`, dan itu benar: kedua modul yang
ada (`hr/leave-opening-balances`, `administration/calendar/work-calendar`)
sasarannya memang belum dijaga izin. Penyempitannya dibuktikan test
dengan modul yang **dijaga** (`payroll/payslips`).

#### CAKUPAN AKHIR

**Lookup — 113, UNKNOWN = 0**

| | Jumlah |
|---|---|
| SECURED | **22** |
| INTENTIONALLY GLOBAL | **89** |
| BLOCKED | **2** |

**Pemanggil `DataScopeService` — 39 nyata, UNCLASSIFIED = 0**

| | Jumlah |
|---|---|
| Berizin (business resource) | **31** |
| Intentionally global (kalender) | 4 |
| System / self | 2 |
| BLOCKED | 2 |

#### BLOCKED — dengan sebab strukturalnya

- **Dropdown `users`.** Satu lookup melayani **lima** konteks keamanan
  berbeda: penugasan role, approver workflow, delegasi, penerima
  notifikasi, dan penautan akun di form Employee. `accounts.view_user`
  dipegang SECURITY-ADMIN + SYSTEM-ADMIN saja (0 akun `demo`), jadi
  menjaganya dengan izin itu **mematikan penautan akun bagi HR-ADMIN**.
  Menyempitkannya lewat `employee_profile` justru membuang akun
  administrator yang tidak punya kartu pegawai. Tidak diperlemah,
  tidak diperketat sepihak: butuh keputusan pemisahan konteks.
- **`RosterSetupService._assert_scope`.** Yang diperiksa "boleh
  menyusun roster untuk lokasi ini", bukan "boleh membaca Location".
  Tidak ada izin model yang menyatakannya; memakai
  `administration.view_location` akan menjawab pertanyaan yang berbeda.
  Butuh gagasan "otoritas wilayah kerja" yang belum ada.
- **`workflow-definitions`** — mekanis, tapi ditahan pembekuan Workflow
  stage ini.

#### INTENTIONALLY GLOBAL — diperiksa, sengaja dibiarkan

- 82 lookup referensi + `document-series` + `posting-periods` (tidak
  punya kolom organisasi; konfigurasi tenant, bukan data orang).
- Kalender (3 lookup + 4 pemanggil): `allow_null=True` adalah semantik
  **keberlakuan**, bukan otoritas. Libur nasional berlaku untuk semua
  company; mutasinya tetap dijaga `ModelPermission`.
- **`external-visitors`** tetap se-tenant: pos jaga (`SECURITY-GATE`)
  tidak memegang `hr.view_externalvisitor`, jadi menjaganya akan
  mematikan pencarian tamu di meja depan. Yang **diperbaiki**
  payload-nya — `identity_number` dikeluarkan dari jawaban dropdown
  (masih bisa dicari, karena tamu menyodorkan kartunya), dan `email`
  serta `mobile` dikeluarkan dari pencarian.

#### REGRESI — hasil sah, dijalankan berurutan

Satu server PostgreSQL, satu proses test pada satu waktu, tiap suite
pada database yang dibuat ulang.

| Suite | Hasil |
|---|---|
| `apps.accounts.tests.test_read_surface_authority` | **14/14 OK** |
| `apps.accounts.tests.test_role_aware_scope` | **14/14 OK** |
| `apps.accounts.tests.test_view_permission_gate` | **7/7 OK** |
| `apps.uploads` | **13/13 OK** |
| `apps.hr.tests.policy` | **19/19 OK** |
| `apps.hr.tests.shift_calendar` | **142/142 OK** |
| `apps.hr.tests.leave.test_leave_access_control` | **23/23 OK** |
| `apps.hr.tests.attendance_permission` | **64/64 OK** |
| `apps.payroll.tests.test_dashboard_authority` | **7/7 OK** |
| `apps.reports` | **291/291 OK** |

`manage.py check` bersih; `makemigrations --check --dry-run` — nol
perubahan. Nol migration di sepanjang stage ini.

#### SATU REGRESI NYATA — ditemukan dan diperbaiki

`apps.reports.tests.hr.test_manpower_movement.IdentityTests.
test_identitas_tertutup_untuk_akun_bercakupan` menuntut
`report.variance == 0` bagi akun bercakupan terbatas, yaitu
**Opening + Join + In − Out − Exit == Closing**. Ia gagal.

Sebabnya perubahan Stage 3B saya sendiri. Laporan Manpower Movement
menghitung populasi (Opening/Closing) dari `Employee`, tetapi barisnya
dari `EmployeeAction`, dan `_inside_ids` saya beri
`hr.view_employeeaction` — padahal `population_queryset()` memakai
`hr.view_employee`. **Satu laporan jadi menuntut dua izin yang tidak
berhubungan** (30/30 akun `demo` memegang yang pertama, 9/30 yang
kedua). Pemegang salah satu saja menerima laporan yang identitasnya
tidak tertutup: headcount bergerak sementara barisnya nol, tanpa satu
pun pesan kesalahan. Kegagalan diam — jenis yang paling mahal.

Diperbaiki di `manpower_movement/services.py` `_inside_ids`, kini
`view_permission_for(Employee)`. Baris `EmployeeAction` di laporan ini
bukan resource yang dipajang tersendiri melainkan **fakta pergerakan
turunan di dalam semesta otoritas populasi** yang sudah dijaga
`population_queryset()`. Satu laporan, satu kemampuan bisnis, satu
izin. Gerbang tidak dilemahkan dan fixture tidak disentuh.

Sesudahnya, **enam scope site di lima laporan HR seluruhnya bermuara
pada satu izin bisnis, `hr.view_employee`** — Manpower Movement
satu-satunya yang pernah terbelah.

#### KEGAGALAN SUMBER DAYA — bukan PASS, bukan FAIL

`apps.hr.tests.attendance_permission` pernah memulangkan 16 error
`setUpClass`/`tearDownClass` berbunyi `psycopg.errors.OutOfMemory: out
of shared memory` saat `DROP SCHEMA CASCADE`. Nol assertion aplikasi
terlibat.

Sebabnya terukur, bukan diterka: satu schema tenant memuat **2226
relasi**, dan `DROP SCHEMA CASCADE` mengunci ACCESS EXCLUSIVE tiap
satunya di dalam **satu** transaksi. Seluruh kolam server cuma
`max_locks_per_transaction (64) × max_connections (100) = 6400` slot.
Satu drop muat dengan sisa lega; **dua drop bersamaan tidak**. Itu
sebabnya error ini cuma muncul pada batch yang berbagi server dengan
run lain.

`max_locks_per_transaction` **tidak** dinaikkan: itu butuh restart
server, dan aritmetikanya sudah mengatakan berurutan saja cukup.
Dijalankan sendirian, suite yang sama lulus **64/64**, sesuai baseline.

#### YELLOW

- `file_url` → `/media/...` hanya dilayani Django saat `DEBUG=True`;
  `config/settings/production.py` menyetel `DEBUG=False`, jadi **tidak
  ada jalur produksi** di dalam kode ini yang menyajikannya. Yang perlu
  dijaga: `base.py` memakai `DEBUG` default **`True`**, jadi produksi
  yang lupa menyetel `DEBUG=0` di env akan membuka seluruh `/media/`.
  Penyajian media oleh nginx/CDN di luar repo ini dan belum diaudit.

---

### Enterprise Data Access Scope — Stage 3B.1: otoritas lampiran
Status: **RED lampiran DITUTUP.** 10 Sep 2026. Nol migration.

#### Sebabnya, tepat

`UploadedFileViewSet.get_queryset()` memulangkan
`UploadedFile.objects.active()` apa adanya. Tidak ada izin, tidak ada
cakupan, tidak ada pemilik: **22 berkas terbaca seluruh 30 akun** di
`demo`, lengkap dengan `public_id`-nya, dan `download/` melayani siapa
pun yang memegangnya. Endpoint daftarnya sendiri yang membagikan
`public_id` itu.

#### Inventaris (3B.1-1) — 9 field menunjuk `UploadedFile`

| Model | Field | Tipe | Relasi balik | Izin induk | Cakupan | Kelompok |
|---|---|---|---|---|---|---|
| `hr.EmployeeDocument` | uploaded_file | 1:1 PROTECT | **tidak ada** | YA | YA | field_document |
| `hr.EmployeeMedicalEvent` | uploaded_file | 1:1 PROTECT | **tidak ada** | YA | YA | field_medical |
| `hr.EmployeeCertificate` | uploaded_file | 1:1 PROTECT | **tidak ada** | – | YA | – |
| `hr.EmployeeTraining` | uploaded_file | 1:1 PROTECT | **tidak ada** | – | YA | – |
| `hr.EmployeeLeave` | uploaded_file | 1:1 PROTECT | **tidak ada** | – | YA | – |
| `hr.AttendancePermission` | supporting_document | 1:1 PROTECT | **tidak ada** | – | YA | – |
| `hr.Candidate` | resume_file | 1:1 PROTECT | **tidak ada** | – | – | – |
| `hr.AttendanceLog` | photo | FK SET_NULL | ada | tanpa viewset | – | – |
| `imports.ImportJob` | source_file | FK PROTECT | ada | tanpa viewset | – | – |

**Tujuh dari sembilan memakai `related_name="+"`** — relasi baliknya
tidak ada sama sekali, `berkas.employeedocument` bukan atribut. Itu
sebabnya induknya dicari dari sisi bisnisnya, dan sebabnya **tidak ada
schema change**: yang kurang accessor-nya, bukan relasinya.

#### IMPLEMENTED

| Berkas | Peran |
|---|---|
| `apps/framework/authority.py` | **baru** — `readable_queryset(model, user)`: baris yang boleh dibaca, diturunkan dari deklarasi viewset model itu (izin + cakupan + kelompok data) |
| `apps/uploads/services/access_service.py` | **baru** — `FileAccessService`: induk ditemukan dari `_meta`, bukan daftar tangan |
| `apps/uploads/api/views.py` | `get_queryset()` menyaring; `destroy`/`replace` menuntut hak tulis |

`apps/uploads` tidak tahu apa pun tentang HR, payroll, atau nama role
mana pun — dan `framework.authority` membaca deklarasi yang **sudah**
ada di viewset, bukan daftar kedua yang harus dijaga tetap sepakat.

Aturannya: **tertaut → otoritas induknya; belum tertaut → hanya
pengunggahnya.** Aturan kedua berhenti sendiri begitu berkasnya
menempel (`~attached & uploaded_by=saya`), bukan lewat penanda terpisah
yang bisa lupa dimatikan.

**Induk ganda: irisannya, bukan gabungannya.** Skema mengizinkan satu
berkas ditunjuk beberapa model (nol kasus di `demo`, tapi tidak
dilarang). "Cukup satu induk yang boleh" akan membuat induk terlonggar
menurunkan derajat berkas yang menempel di tempat paling rahasia.

#### CONFIRMED — `demo`

**22 → 7 untuk seluruh 30 akun non-superuser; 0 akun bertambah.**
Sisa 7 adalah berkas milik `imports.ImportJob`, yang endpoint-nya
sendiri `IsAuthenticated` tanpa cakupan — kelonggaran itu milik
`ImportJob` dan ditutup di sana, bukan di sini. 15 berkas yang belum
tertaut seluruhnya milik `admin` (superuser), jadi tidak satu pun akun
biasa melihatnya.

#### TESTED

`apps/uploads/tests/test_file_authority.py` — **13/13 OK** (84 s),
seluruh 17 butir 3B.1-12, hijau di percobaan pertama.

| Batch | Isi | Hasil |
|---|---|---|
| A | uploads, data_scope_semantics, view_permission_gate, role_aware_authority, role_aware_scope, `hr.tests.policy` | **81/81 OK** (1201 s) |
| B | attendance_permission (64), import absensi, leave_access_control, payroll dashboard authority, payroll run summary | **167/167 OK** (4572 s) |

**248 test, nol gagal, nol kill.** `manage.py check` bersih;
`makemigrations --check --dry-run` → "No changes detected".

#### OPEN — YELLOW

- **`/api/imports/jobs/`** `IsAuthenticated` tanpa cakupan: setiap
  akun melihat seluruh job import dan nama berkasnya. Endpoint lain,
  bukan RED stage ini.
- **`hr.Candidate`** tanpa izin maupun cakupan → berkas lamaran
  mewarisi "siapa pun yang login". Pewarisannya benar; celahnya milik
  `CandidateViewSet`.
- **`file_url` / `thumbnail_url`** memulangkan path `/media/...`.
  Django hanya melayaninya saat `DEBUG=True`, jadi ini paparan dev,
  bukan produksi — tapi di dev ia melewati seluruh lapisan di atas.
- **Mutasi lampiran BLOKIR (disengaja).** Mengganti/menghapus berkas
  yang **sudah** tertaut ditolak seluruhnya lewat `/api/uploads/`;
  menurunkan izin mutasi induknya butuh keputusan tersendiri.
- `is_public` **tidak punya arti otorisasi apa pun** hari ini:
  `UploadedFileQuerySet.public()` tidak pernah dipanggil, tidak ada
  endpoint atau storage yang membacanya. Tidak dipakai, tidak
  diperluas.

---

### Enterprise Data Access Scope — Stage 3B: permukaan baca
Status: **SEBAGIAN. Group 1–4 dikerjakan; lookup transaksional dan
lampiran masih terbuka.** 9 Sep 2026. Nol migration.

#### Inventaris (3B-1) — dihitung dari URLconf yang termuat, bukan grep

| Permukaan | Jumlah | Terjaga izin | Bercakupan |
|---|---|---|---|
| Lookup | 113 | 3 (sesudah 3B) | 12 |
| Viewset | 177 | 10 | 38 |
| `APIView` lain (dashboard/report/drilldown) | 99 | 0 | — |
| `@action` baca | 24 | — | — |
| Pemanggil `DataScopeService.filter()` | 34 | 12 (sesudah 3B) | — |

Klasifikasi 113 lookup — ditentukan dari **modelnya**, dan yang tidak
masuk daftar mana pun jatuh ke UNKNOWN, bukan diam-diam dianggap
referensi:

| Kelompok | Jumlah | Bercakupan |
|---|---|---|
| Referensi global (negara, mata uang, klasifikasi) | 82 | 0 — disengaja |
| Referensi organisasi (company/location/…) | 9 | **9** |
| Transaksional | 14 | 2 |
| Sensitif (orang) | 4 | **1** (sesudah 3B) |
| Kalender — keberlakuan sengaja global | 3 | 0 — disengaja |
| Sistem | 1 | 0 |
| UNKNOWN | **0** | — |

#### IMPLEMENTED

| Berkas | Perubahan |
|---|---|
| `apps/accounts/permissions.py` | `view_permission_for(model)` — **satu-satunya** tempat `app_label.view_model` dibentuk; `required_view_permission(view)` memanggilnya |
| `apps/payroll/scoping.py` | `scope_run_employees()` mengirim izin — celah yang dikonfirmasi Stage 3A |
| `apps/payroll/api/dashboard/services.py` | `periods()`, `runs()` per izin |
| `apps/reports/api/hr/*/services.py` (5 laporan) | populasi laporan per `hr.view_employee` |
| `apps/hr/imports/attendance/resolver.py` | `can_touch()` per izin — termasuk hubung-singkat `unrestricted`-nya |
| `apps/hr/api/employee/views/employee.py` | dropdown pegawai memakai izin yang sama dengan tabelnya |
| `apps/notifications/recipients.py` | otoritas **penerima**, per izin |
| `apps/framework/lookup/base.py` | `BaseLookup.require_view_permission` — opt-in, bawaan mati |
| `apps/payroll/api/payroll_{runs,periods}/lookup/registry.py` | dropdown run & periode menuntut izin yang sama dengan tabelnya |
| `apps/hr/api/lookup/registry.py` | dropdown `employee-leaves` diberi cakupan + izin |
| `apps/accounts/seeds/security_roles.py` | `payroll.payrollperiod` ditambahkan ke lima role yang sudah memegang `payroll.payrollrun` |

#### CONFIRMED — dashboard payroll, tenant `demo`

Tiga permukaan, `lama → role-aware → role-aware+seed`:

| Akun | Role | periode | run | baris |
|---|---|---|---|---|
| `demo.homanager` | EMPLOYEE + FINANCE-MANAGER | 8→0→**8** | 8→8→8 | 2→2→2 |
| `demo.gmho` | EMPLOYEE + EXECUTIVE | 8→0→0 | 8→**0** | 2→**0** |
| `demo.bod1` | BOD + EMPLOYEE | 8→0→0 | 8→**0** | 0→0 |
| `demo.hrga` | HRGA | 8→0→0 | 8→**0** | 1→**0** |
| `demo.opr1` | EMPLOYEE | 8→0→0 | 8→**0** | 1→**0** |

Kolom periode adalah alasan seed diubah: tanpa `payroll.payrollperiod`,
**setiap** operator payroll membuka dashboard dengan pemilih periode
kosong. Itu kehilangan yang tidak disengaja siapa pun — bukan
penyempitan keamanan — dan diperbaiki di tempat yang benar: izinnya.

#### SECURITY NARROWING — disengaja, bukan kecelakaan

- Daftar run payroll berhenti terbaca BOD, EXECUTIVE, HRGA, dan pegawai
  biasa (8 → 0). Mereka tidak memegang `payroll.view_payrollrun`.
- Angka payroll per orang di dashboard berhenti terbaca EXECUTIVE,
  HRGA, dan pegawai biasa. Slip miliknya sendiri **tidak** terpengaruh
  — itu `payroll.view_payslip`, dan pegawai memegangnya.
- Dropdown cuti pegawai berhenti mengirim seluruh tenant.

#### INTENTIONALLY GLOBAL — diperiksa, sengaja dibiarkan

- **82 lookup referensi** (negara, mata uang, jenis dokumen,
  klasifikasi). Menuntut `view_*` di sini berarti memberi setiap orang
  izin baca puluhan model hanya supaya dropdown negara muncul.
- **Kalender (3 lookup + `CalendarScopedViewSetMixin`).** `allow_null=
  True` adalah semantik **keberlakuan** — libur nasional berlaku untuk
  semua company. Menambahkan izin di sini akan menghapus libur nasional
  dari layar 22 dari 30 akun. Otoritas mutasinya tetap dijaga
  `ModelPermission`; kedua sumbu itu sengaja tidak disatukan.

#### TESTED

| Batch | Isi | Hasil |
|---|---|---|
| payroll | `test_dashboard_authority` (**baru**, 7), `test_payroll_run_summary` (11), `test_dashboard` (31) | **49/49 OK** (1276 s) |
| laporan | `apps.reports` seluruhnya | **291/291 OK** (4865 s) |
| accounts + policy | data_scope_semantics, view_permission_gate, role_aware_authority, role_aware_scope, `apps.hr.tests.policy`, notifications | **93/93 OK** (1175 s) |
| HR + kalender | attendance_permission (64), attendance import, leave_access_control, roster_setup_scope, calendar | 233 test, 1 gagal (fixture) |
| HR — import absensi, sesudah fixture diperbaiki | `apps.hr.tests.attendance` | **62/62 OK** (1278 s) |

**666 test, nol gagal tersisa, nol kill.**

`manage.py check` bersih; `makemigrations --check --dry-run` → "No
changes detected".

**Empat fixture test diperbaiki, bukan gerbangnya.** Semuanya bentuk
yang sama: role dibuat dengan baris cakupan tapi **tanpa satu izin
pun**, keadaan yang tidak pernah ada di produksi (setiap role yang
diseed memegang `hr.view_employee`; setiap meja payroll memegang izin
baca payroll). Yang paling menyesatkan di antaranya:
`test_csv_cannot_reach_employees_outside_the_scope` tetap **hijau**
karena semua barisnya ditolak, sementara pasangan positifnya merah —
test negatif yang lulus karena mesinnya menolak semuanya.

#### CONFIRMED — kesiapan rilis (3B-18)

`audit_role_aware_coverage --surfaces` kini menghitung **baris**, bukan
hanya bentuk cakupan, dan memisahkan dua jenis kehilangan:

* **TIDAK BERWENANG** — akun tidak memegang izinnya. Hilangnya memang
  maksud perubahannya.
* **SEMPIT** — akun memegang izinnya, tapi cakupan role pemberinya
  lebih sempit. Ini yang harus dibaca orang sebelum rilis.

Di `demo`, sesudah seed dijalankan: **0 akun bertambah**, **0 akun
"SEMPIT"**, 68 akun "TIDAK BERWENANG". `demo.homanager`
(FINANCE-MANAGER) tidak kehilangan satu baris pun di permukaan mana
pun.

#### OPEN — RED

- **`UploadedFileViewSet` (`/api/uploads/`).** `IsAuthenticated`, tanpa
  `data_scope`, tanpa `require_view_permission`, querysetnya
  `UploadedFile.objects.active()` tanpa penyaringan pemilik. Di `demo`
  **22 berkas terbaca seluruh 30 akun**, dan `download/` melayani
  siapa pun yang memegang `public_id` — yang dibagikan endpoint
  daftarnya sendiri. Hari ini belum ada dokumen pegawai yang
  membawa berkas (0 dari 78), jadi tidak ada data orang yang bocor
  **sekarang**; permukaannya tetap terbuka.
  **Tidak diperbaiki**, dan sengaja: otoritas yang benar adalah "boleh
  membaca berkas kalau boleh membaca record yang menunjuknya" — relasi
  balik yang tidak bisa dinyatakan `data_scope`, dan menebaknya
  (`uploaded_by=saya`) akan mencabut akses HR ke dokumen pegawai.
  Butuh keputusan.

#### OPEN — YELLOW

- 12 lookup transaksional belum bercakupan (`site-rotations`,
  `rotation-periods`, `visitor-requests`, `job-vacancies`,
  `training-programs`, `workflow-definitions`, `numbering-sequences`,
  `fiscal-years`, `posting-periods`, `document-series`,
  `roster-plans`, `rotation-segments`). Enam di antaranya punya kolom
  organisasi langsung dan bisa dikerjakan mekanis; sisanya perlu
  keputusan.
- 3 lookup sensitif belum bercakupan: `users` (31 baris),
  `external-visitors`, `candidates`. Ketiganya **tidak punya** kolom
  organisasi, jadi cakupannya harus diturunkan lewat relasi — bukan
  perubahan mekanis.
- 22 pemanggil `DataScopeService.filter()` lain (dashboard HR,
  administration overview, roster, shift calendar, travel, leave,
  calendar resolver) masih memakai cakupan gabungan.

#### DEFERRED

- Atribusi `UserDataPermission` — **masih terbuka**, tidak disentuh
  Stage 3B. Satu baris masih melebarkan setiap izin pemegangnya.
- `ROLE_AWARE_DATA_SCOPE` tetap `False` di `base.py`.

---

### Enterprise Data Access Scope — Stage 3A.1: komposisi aturan kelompok data
Status: **SELESAI. 3A-7 dan 3A-8 dibuka.** 9 Sep 2026. Nol migration.

#### Sebab yang lama, tepat di satu tempat

`EmployeeDataVisibility.visible_employees_q()` menilai aturan satu per
satu dari yang paling khusus; begitu satu aturan **berlaku untuk
semua**, ia menyetel `prior_covers_all` lalu `break`. Aturan global
kedua tidak pernah dinilai. Jalur kedua punya penyakit yang sama:
`match()` memulangkan `max(specificity)` — **satu** baris — dan
`can_view()` hanya menilai baris itu.

Jadi dua baris global untuk satu kelompok bukan "dua role boleh",
melainkan "role di baris pertama boleh, baris kedua tidak berlaku",
tanpa satu pesan pun.

#### IMPLEMENTED

| Berkas | Perubahan |
|---|---|
| `apps/hr/api/employee/visibility.py` | `match()` → `matches()` (seluruh baris di tingkat teratas); `can_view()` menilai semuanya dan cukup satu yang membolehkan; `visible_employees_q()` mengelompokkan baris menurut **sasaran** lalu OR di dalam sasaran |
| `apps/administration/models/references/employee_data_policy.py` | `clean()` memvalidasi `subject` terhadap `EmployeeDataSubject.values`, bukan `SUBJECT_ACTION_TYPES` |
| `apps/administration/seeds/reference/employee_data_policy.py` | baris per-kelompok boleh lebih dari satu + `EDP-PAYROLL-FINANCE`, `EDP-DOCUMENT-ADMIN`, `EDP-DOCUMENT-MANAGER` |

Aturannya: **OR di dalam sasaran yang sama, menutupi antar-sasaran.**
Sasaran = `(company, location, employee_group)`. Skor 4/2/1 bersifat
injektif, jadi dua baris berskor sama pasti mengisi field sasaran yang
sama — dan karena keduanya cocok untuk pegawai yang sama, nilainya pun
sama. Itu yang membuat kedua jalur (`matches()` dan
`visible_employees_q()`) tetap sepakat.

**Penutupan antar-sasaran sengaja tidak diubah.** Baris `company=A`
memang dimaksudkan mencabut jangkauan baris global di Company A — itu
satu-satunya bentuk "tidak boleh" yang dipunyai master ini. Menyatukan
seluruh baris dengan OR akan mengubah tiap pencabutan itu jadi izin,
diam-diam. Dikunci `test_a_narrower_rule_still_shadows_the_global_one`.

**Nol schema change.** `role` tetap FK tunggal; yang menyusun
gabungannya barisnya. `makemigrations --check` → "No changes detected".

#### Bug yang ikut ketemu: kelompok `field_*` tidak bisa disunting dari UI

`clean()` memeriksa `subject not in SUBJECT_ACTION_TYPES`, dan kamus itu
cuma memuat empat kelompok **riwayat**. Seluruh kelompok `field_*` —
termasuk `field_payroll`, `field_bank`, `field_medical` yang barisnya
sudah diseed — ditolak validasi. Seed lolos karena `objects.create()`
tidak memanggil `full_clean()`; layar setting tidak, karena
`BaseMasterService` selalu memanggilnya. Tanpa perbaikan ini, baris
`field_document` yang diminta 3A.1-4 tidak bisa dibuat lewat jalur
normal sama sekali.

#### CONFIRMED — terukur di tenant `demo`, seed dijalankan lalu di-rollback

**Dokumen pegawai (3A-8).** Irisan cakupan role-aware × kelompok data,
lewat peta yang persis dipakai `EmployeeDocumentViewSet`:

| Akun | Role | dokumen terbaca |
|---|---|---|
| `demo.bod1` | BOD + EMPLOYEE | 78 → **0** |
| `demo.gmho` | EMPLOYEE + EXECUTIVE | 78 → **0** |
| `demo.homanager` | EMPLOYEE + FINANCE-MANAGER | 3 → **3** |
| `demo.opr1` | EMPLOYEE | 3 → **3** |

Di lapisan policy saja, **26 dari 30 akun** turun dari 48 pegawai
(seluruh tenant) ke 1 (dirinya sendiri). Yang tidak berubah adalah
pemegang cakupan `own` yang memang sudah hanya melihat berkasnya.

**Payroll per orang (3A-7).** Irisan yang sama pada slip dan rincian
run:

| Akun | slip | rincian run |
|---|---|---|
| `demo.homanager` (FINANCE-MANAGER) | 0 → **3** | 2 → **76** |
| `demo.gmho` (EXECUTIVE) | 0 → 0 | 2 → 2 |
| `demo.bod1` (BOD) | 0 → 0 | 0 → 0 |
| `demo.opr1` (EMPLOYEE) | 0 → 0 | 1 → 1 |

Persis angka yang dilaporkan terhenti di Stage 3A ("2 dari 76").
Direksi dan Executive tidak bergerak — Business Decision #2 tetap.

#### TESTED

**252 test, nol gagal, nol kill.**

| Batch | Isi | Hasil |
|---|---|---|
| `apps.hr.tests.policy` | komposisi 11, role 4, pemetaan kelompok 4 | **19/19 OK** (203 s) |
| accounts | data_scope_semantics, view_permission_gate, role_aware_authority, role_aware_scope | **49/49 OK** (1033 s) |
| payroll + akses HR | payroll_run_summary, payroll dashboard, leave_access_control, roster_setup_scope, calendar_scoping, calendar_scope | **120/120 OK** (2257 s) |
| `apps.hr.tests.attendance_permission` | tak tersentuh, dijalankan utuh | **64/64 OK** (1772 s) |

`manage.py check` bersih; `makemigrations --check --dry-run` → "No
changes detected".

`test_a_second_global_rule_never_takes_effect` **dibalik** jadi
`test_a_second_global_rule_takes_effect`. Test itu memang ditulis untuk
dibalik: "kalau merah, artinya kemampuan multi-role sudah ditambahkan —
dan catatannya yang harus diperbarui, bukan testnya."

#### KNOWN LIMITATION

- `scope_run_employees()` (dashboard/summary payroll) memanggil
  `DataScopeService.filter()` **tanpa** `required_permission`, jadi di
  jalur itu peminjaman lintas-role masih ada. Itu Stage 3B, bukan
  regresi 3A.1 — terlihat pada `demo.gmho` yang tetap membaca 2 rincian
  run.
- Satu kelompok data masih hanya bisa dibatasi per sasaran, bukan per
  kombinasi role×sasaran yang berbeda-beda. Yang dibuka 3A.1 adalah
  **banyak role di satu sasaran**.

---

### Enterprise Data Access Scope — Stage 3A: otoritas per-izin
Status: **INTI SELESAI. DUA BUTIR TERBLOKIR, dilaporkan bukan diakali.**
9 Sep 2026. Nol migration.

#### IMPLEMENTED

| Berkas | Perubahan |
|---|---|
| `apps/accounts/scoping.py` | `for_user(user, *, permission=)`, `_build(user, *, permission=)`, `_roles_granting()`, `filter(..., required_permission=)`, `role_aware_enabled()`; cache jadi dict per-izin |
| `apps/accounts/permissions.py` | `required_view_permission(view)` — **satu-satunya** tempat nama izin baca dibentuk; `_may_read()` ikut memakainya |
| `apps/framework/views/master.py` | `filter_queryset()` mengirim `required_view_permission(self)` |
| `config/settings/base.py` | `ROLE_AWARE_DATA_SCOPE`, default **False** |
| `config/settings/local.py` | dinyalakan untuk dev sesudah cakupannya dibuktikan |
| `apps/accounts/management/commands/audit_role_aware_coverage.py` | **baru** — siapa yang menyempit/hilang sebelum saklarnya disentuh |

Kontraknya: `akses = UNION atas role yang memberi izin itu, dari
(izin role × cakupan role itu)`. Role yang tidak memberi izinnya tidak
menyumbang cakupan.

**Bertahap, dan itu yang membuatnya aman.** Cakupan hanya menyempit
kalau pemanggilnya mengirim `required_permission`. Hari ini yang
mengirimkannya **satu**: `BaseMasterViewSet.filter_queryset()`, dan
hanya untuk 10 resource ber-`require_view_permission`. Dua puluh empat
pemanggil lain — lookup, dashboard, report, importer, kalender —
berperilaku persis seperti sebelumnya. Itu Stage 3B.

#### CONFIRMED — terukur di tenant `demo`

`manage.py tenant_command audit_role_aware_coverage --schema=demo`:
**13 akun menyempit, 0 akun kehilangan akses.** Karena itu saklarnya
dinyalakan di dev; produksi tetap `False` sampai perintah yang sama
dijalankan di tenant-nya dan hasilnya juga nol "HILANG".

Baris yang terbaca, sebelum → sesudah:

| Akun | Role | payslip | run-employee |
|---|---|---|---|
| `demo.homanager` | EMPLOYEE + FINANCE-MANAGER | 3 → **3** | 76 → **76** |
| `demo.gmho` | EMPLOYEE + EXECUTIVE | 3 → **0** | 76 → **0** |
| `demo.bod1` | BOD + EMPLOYEE | 3 → **0** | 76 → **0** |
| `demo.gmsite` | EMPLOYEE + EXECUTIVE-SITE | 0 → 0 | 18 → **0** |

Direksi dan Executive berhenti membaca payroll per orang — cakupan
seluas apa pun tanpa izin payroll sekarang berarti nol baris. Meja yang
memang memegang izinnya tidak kehilangan satu baris pun.

#### TESTED

- `apps/accounts/tests/test_role_aware_scope.py` — **14/14 OK**,
  matriks A–J, tiap skenario dijalankan di **kedua** mode
- `apps/hr/tests/policy/test_employee_data_policy_roles.py` — **4/4 OK**
- `test_role_aware_authority.py` (Stage 2) diarahkan ke API produksi,
  bukan lagi ke tiruannya
- Regresi gabungan **121/121 OK** (3444 s): `test_data_scope_semantics`
  (15), `test_view_permission_gate` (7), `test_role_aware_authority`
  (13), `test_role_aware_scope` (14), `apps.hr.tests.policy`,
  `apps.hr.tests.attendance_permission` (64)
- `roster_setup_scope`, `calendar_access`, `leave_access_control` —
  **88/88 OK**
- `apps/payroll/tests/test_payroll_run_summary.py` — **11/11 OK**
  (372 s) sesudah fixture-nya diperbaiki. Sempat 12 galat: role
  fixture-nya memang tidak pernah menyatakan `payroll.view_payrollrun`,
  jadi `get_object()` memulangkan 404. Yang ditambal fixture-nya
  (`view_payrollrun` + `view_payrollrunemployee` untuk **kedua** role);
  tidak ada assertion cakupan yang dilonggarkan.

#### GAGAL, TIDAK BERHUBUNGAN — dilaporkan, bukan didiamkan

- Batch payroll penuh **dibunuh** di ~118 test (`exit=137`, SIGKILL)
  tanpa satu pun assertion merah. Itu kehabisan sumber daya mesin, dan
  bukan hasil test — jangan dibaca sebagai hijau maupun merah.
- `apps/accounts/tests/test_user_language.py` merah di `setUp`-nya
  sendiri: `relation "auth_users" does not exist`. Berkas itu datang
  dari sesi paralel bersama `accounts/0008_user_language`, hanya
  menyentuh `/api/accounts/auth/me/`, dan tidak memanggil satu pun jalur
  cakupan. Di luar Stage 3A.

#### TERBLOKIR — 3A-7 & 3A-8, sebab yang sama

**`EmployeeDataPolicy` hanya bisa membolehkan satu role per kelompok
data.** `role` sebuah FK tunggal, dan `visible_employees_q()` berhenti
(`prior_covers_all` → `break`) sesudah aturan global pertama. Aturan
global kedua **tidak pernah dinilai** — tanpa satu pesan pun.
Dibuktikan: `test_a_second_global_rule_never_takes_effect`.

Akibatnya:

- **3A-8 (`hr.employeedocument`)** — "swalayan + HR-MANAGER" bisa
  ditulis satu baris; "**dan** HR-ADMIN" tidak. Membuat barisnya
  sekarang justru mencabut baca dari HR-ADMIN — meja yang mengarsipkan
  dokumen itu (ia memegang add/change/delete). Tidak dikerjakan.
- **3A-7 (FINANCE-MANAGER)** — izinnya sudah **cukup** sejak Stage 1
  (`view_payslip`, `view_payrollrun`, `view_payrollrunemployee`,
  `hr.view_employee`), dan cakupannya kini benar (own/Company).
  Yang tersisa: aturan `field_payroll` menyebut `HR-MANAGER` saja,
  jadi rinciannya tetap terhenti di **2 dari 76**. Menambah baris
  kedua tidak berlaku; mengganti role di baris yang ada akan mencabut
  HR-MANAGER. **Tidak ada izin baru yang diseed** — yang kurang bukan
  izin.

Jalan keluarnya butuh keputusan: `EmployeeDataPolicy.role` (FK) →
M2M, atau satu baris per role dengan `visible_employees_q()` yang
menggabungkan aturan setingkat alih-alih berhenti di yang pertama.
Keduanya mengubah semantik policy, dan 3A-8 melarang menciptakannya
sendiri.

#### KNOWN LIMITATION

`UserDataPermission` tetap tanpa atribusi: satu baris masih melebarkan
**setiap** izin pemegangnya. Dikunci
`test_a_user_row_still_widens_every_permission`. Batasnya ada batasnya —
baris itu melebarkan cakupan, bukan memberi izin
(`test_a_user_row_cannot_grant_a_permission_the_user_lacks`).

#### DEFERRED

- Atribusi `UserDataPermission` (butuh kolom baru)
- Role-aware untuk lookup/dashboard/report/export/importer — Stage 3B
- Pencabutan jalur lama + `ROLE_AWARE_DATA_SCOPE`, sesudah 3B
- Enterprise Workflow Authority / Option C

---

### Enterprise Data Access Scope — Stage 2: audit otoritas role-aware
Status: **AUDIT SELESAI. NOL BARIS KODE PRODUKSI DIUBAH.** 9 Sep 2026.
Yang bertambah satu berkas test: `apps/accounts/tests/test_role_aware_authority.py`
— **13/13 OK** (354 s).

#### CONFIRMED — peminjaman lintas-role itu nyata, dan strukturnya

`DataScopeService.filter(queryset, peta, user)`. **Tidak ada satu
argumen pun yang menyebut izin**, dan ~25 pemanggilnya (viewset,
lookup, dashboard, report, notifikasi, importer, kalender) tidak satu
pun mengirimkannya. Cakupan dihitung sekali per orang, disimpan di
`_data_scope_cache`, lalu dipakai ulang untuk resource apa pun. Jadi
izin dari Role A memang berjalan sejauh gabungan cakupan **seluruh**
role — bukan gejala satu akun demo, melainkan bentuk API-nya.

Diuji dari empat arah: payroll, rekening bank (untuk membuktikan ini
bukan kekhususan payroll), satu role `all` yang membuat izin tak
berhubungan jadi se-tenant, dan pemeriksaan langsung pada objek
cakupannya.

#### CONFIRMED — tidak ada lapis izin per-objek

Seluruh codebase hanya punya satu `has_object_permission`, dan itu di
`apps/workflow/`. Perlindungan baris **seluruhnya** dari penyaringan
queryset di `filter_queryset()`; `get_object()` aman hanya karena DRF
memanggil `filter_queryset(get_queryset())`.

#### CONFIRMED — "own" adalah dua hal berbeda dengan satu nama

- `Role.data_scope_mode = "own"` → **penempatan organisasi**, sedalam
  `data_scope_level`.
- `RoleDataPermission.resource_type = "own"` → **barisnya sendiri**,
  lewat `user_id`.

`DataScopeLevel` **tidak punya** pilihan "diri sendiri", jadi mode
`own` tidak mungkin berarti "hanya barisku". Mekanisme baris-sendiri
sudah terpasang luas: **29 resource** punya kunci `own` di petanya.
Satu-satunya role di `demo` yang memakainya: `EMPLOYEE`.

#### CONFIRMED — lapis ketiga sudah role-aware, dan sudah terbukti

`EmployeeDataPolicy` + `EmployeeDataSubjectMixin` menjawab "**jenis**
data siapa" dengan kosakata yang persis dibutuhkan kontrak target:
`role`, `allow_self`, `allow_manager` + `manager_levels`,
`allow_department_head`, dicakup per company/location/employee_group,
dipilih lewat `specificity`. **Polanya tidak perlu ditemukan — sudah
jalan di produksi**, hanya untuk pertanyaan yang berbeda.

Di `demo` ada 5 baris, semuanya menyebut `HR-MANAGER`.

#### CONFIRMED — akibatnya terukur, dan tidak seragam

| Resource | punya `data_subject`? | `demo.gmho` terbaca |
|---|---|---|
| `hr.employeedocument` | **tidak** | **78 / 78** |
| `hr.employeebankaccount` | ya | 0 / 26 |
| `hr.employeemedicalevent` | ya | 0 / 18 |
| `hr.payrollassignment` | ya | 0 / 44 |
| `payroll.payslip` | ya | 0 / 3 |

`demo.gmho` memegang `EMPLOYEE` (yang memberi `view_*` demi swalayan)
dan `EXECUTIVE` (cakupan `own`/Company). Di mana lapis ketiga
kebetulan **tidak** dikonfigurasi — tidak ada baris `field_document` —
peminjaman itu terbaca utuh: **seluruh 78 dokumen pegawai di tenant**.

Bukan kemunduran dari Stage 1: sebelum gerbang baca ada, dokumen itu
terbuka untuk siapa pun yang bisa login. Yang ditunjukkannya bahwa
penutupnya hari ini adalah **konfigurasi yang kebetulan ada**, bukan
kontrak.

#### CONFIRMED — dua akibat operasional yang perlu keputusan

- `demo.homanager` (FINANCE-MANAGER, meja kedua alur payroll) membuka
  header run **8/8** tapi rincian per orang hanya **2 dari 76** —
  `field_payroll` hanya menyebut `HR-MANAGER`. Ia menyetujui angka
  yang tidak bisa ia buka.
- `UserDataPermission` **tidak punya kolom apa pun** untuk atribusi
  (hanya `user`, `resource_type`, `resource_id`). Di `demo`,
  `demo.gmho` punya satu baris `company=MLS` yang jelas dimaksudkan
  untuk kewenangan EXECUTIVE-nya — dan baris itu ikut memperluas
  **setiap** izin yang ia pegang, termasuk yang datang dari EMPLOYEE.

#### CONFIRMED — kontrak yang benar bisa dihitung tanpa migration

`Role` sudah punya `permissions` **dan** `data_scope_mode`/`level`;
`RoleDataPermission` sudah ber-FK ke `role`. Jadi otoritas per-role =
menggabungkan dua hal yang sudah bertetangga di satu tabel.

Dibuktikan, bukan diargumenkan: `role_aware_scope()` di berkas test
menyaring role berdasarkan izin lalu menyerahkannya ke
`DataScopeService.filter()` **yang asli**. Hasilnya benar untuk seluruh
skenario — slip berhenti di baris sendiri, dua fungsi tetap di dua
lebar, `all` milik satu role tidak menular, dan izin yang tidak
dipegang menghasilkan nol baris. Tidak satu kolom baru pun dipakai.

Yang **tidak** bisa dinyatakan tanpa migration: atribusi
`UserDataPermission`.

#### OPEN — keputusan bisnis, bukan tebakan teknis

1. Boleh/tidak `FINANCE-MANAGER` membuka payroll per orang.
2. Boleh/tidak `BOD`/`EXECUTIVE` membuka payroll per orang.
3. `hr.employeedocument` tanpa aturan `field_document` — dibiarkan
   terbuka, atau dibuatkan aturannya.
4. Kalau `UserDataPermission` harus bisa diatribusikan, ke apa:
   role, modul, atau izin.

#### Koreksi angka Stage 1

Catatan Stage 1 menyebut `demo.gmsite` "membaca slip 19 orang
se-site". Itu ekstrapolasi dari jumlah **pegawai**, bukan hitungan
slip, dan mengabaikan lapis `data_subject`. Terukur: tenant `demo`
punya 3 slip, `demo.gmsite` melihat **0**. Mekanismenya tetap nyata
dan terlihat jauh lebih tajam pada `hr.employeedocument` di tabel di
atas.

---

### Enterprise Data Access Scope — Stage 1: izin baca (`view_*`)
Status: **SELESAI DAN HIJAU.** 8 Sep 2026. Regresi 475/483 — 8 error
sisanya milik berkas `test_user_language.py` (pekerjaan sesi lain yang
sedang berjalan), bukan gerbang ini.

**Yang ditutup.** `ModelPermission` mengembalikan `True` untuk seluruh
SAFE_METHOD, dan tidak ada satu baris pun di codebase yang pernah
membentuk nama izin `view_*`. Jadi kontrak "izin + cakupan" cuma benar
setengahnya: cakupan menjawab **baris siapa**, tidak ada yang menjawab
**jenis data apa**. Kebetulan berada di satu lokasi cukup untuk membuka
slip gaji orang di lokasi itu.

**Kenapa opt-in, bukan global.** Diukur, bukan dikira: pada 20 model
payroll di balik endpoint, **hanya SYSTEM-ADMIN** yang memegang `view_*`
— bukan HR-ADMIN, bukan FINANCE-MANAGER. `EMPLOYEE` (22 pemegang) punya
7 dari 152. Menyalakan penjagaan baca serentak mengunci setiap operator
payroll dari payroll.

`BaseMasterViewSet.require_view_permission` bawaannya `False`;
dinyalakan pada 10 resource yang isinya sendiri rahasia — `hr.employee`,
4 tabel anak kartu pegawai (bank, dokumen, medis, penempatan payroll),
dan 5 tabel payroll per-orang (slip, run, run-employee, input, BPJS).
Wajib berpasangan dengan `data_scope`; dijaga
`test_view_permission_gate`, bukan kesepakatan lisan.

**Temuan yang ikut ditutup.** `payroll.bpjsenrollment` berbaris per
pegawai (nomor kepesertaan BPJS = identitas nasional) dan **tidak punya
`data_scope` sama sekali** — siapa pun yang bisa login membaca nomor
kepesertaan seluruh tenant. Sekarang bercakupan `EMPLOYEE_CHILD_SCOPE`.

**Dua role yang sebelumnya tanpa batasan, sekarang menyatakan diri.**
- `FINANCE-MANAGER`: `explicit` + 0 baris (= tanpa batasan) → `own` /
  **Company**. Terukur di demo: `demo.homanager` turun dari 48/48
  pegawai jadi **46/48** — dua orang company MNI keluar dari
  jangkauannya.
- `SECURITY-GATE`: `explicit` + 0 baris → `own` / **Location**.
  0 pemegang, jadi tanpa dampak berjalan. Izinnya sengaja berhenti di
  `hr.employee` — satpam perlu tahu siapa penerima tamunya, bukan berapa
  gajinya.

`own`, bukan `explicit` berisi baris company: `explicit` gagal ke arah
**terbuka** begitu barisnya terhapus. `own` tanpa penempatan memberi nol
akses. Multi-company ditangani `UserDataPermission` per orang — baris per
orang selalu menambah — jadi pengecualiannya tercatat atas nama
orangnya, bukan tersembunyi di role yang dipakai bersama.

**Urutan menyalakan, jangan dibalik.** `seed_security_roles` **atau**
`seed_data_scopes` dulu (keduanya memanggil `apply_read_grants()`), baru
penjagaannya berlaku. Dipanggil dari dua tempat karena sebagian
penerimanya lahir di seed lain — `HR-*-SITE` di `seed_data_scopes`,
`FINANCE-MANAGER`/`KTT-SITE` di `seed_workflows` — dan siapa yang boleh
membuka payroll tidak boleh bergantung pada urutan perintah.
Sudah dijalankan di tenant `demo`: **+35 izin baca**, idempoten.

Saklar: `ENFORCE_VIEW_PERMISSIONS` (default `True`), terpisah dari
`ENFORCE_MODEL_PERMISSIONS` supaya tenant yang seed-nya belum diperbarui
bisa mematikan penjagaan baca tanpa ikut membuka izin tulis.

**Nol migration.** Tidak ada perubahan model.

**TERBUKA — bukan lupa, tapi belum diputuskan**
- **Cakupan masih per-orang, bukan per-role.** Izin dari role A memakai
  cakupan role B. Perbaikannya cakupan yang sadar-role — keputusan
  arsitektur tersendiri, diaudit penuh di Stage 2.

  **Koreksi angka:** catatan pertama di sini menyebut `demo.gmsite`
  "membaca slip 19 orang se-site". Itu ekstrapolasi dari jumlah
  **pegawai** selokasi, bukan hasil hitung slip. Yang terukur: tenant
  `demo` baru punya 3 slip, dan `demo.gmsite` melihat **0** dari 3 —
  slipnya kebetulan bukan di lokasinya. Mekanismenya tetap nyata dan
  justru lebih tajam terlihat pada dua akun lain; lihat Stage 2.
- Lapisan lookup (`BaseLookupView`) masih `IsAuthenticated` saja.
- `BOD`/`EXECUTIVE`/`EXECUTIVE-SITE` kehilangan baca payroll yang
  selama ini mereka punya secara implisit. **Tidak diberikan otomatis**
  — apakah direksi boleh membuka slip gaji per orang adalah keputusan
  bisnis, bukan tebakan seed.
- `EMPLOYEE` kehilangan baca `hr.payrollassignment`. Slipnya tetap
  terbaca.
- Aturan `explicit` + 0 baris = tanpa batasan **belum diubah** (Stage 2).
  Di `demo` sekarang tidak ada lagi role yang masuk kelas itu.

---

### Enterprise Data Access Scope — audit (Phase 2)
Status: **AUDIT SELESAI.** 8 Sep 2026. Stage 1-nya sudah dikerjakan —
lihat bagian di atas.

#### CONFIRMED — dibuktikan dari kode + tenant `demo`

- **Kontrak enterprise baru separuh ada.** `PERMISSION (apa) + SCOPE (di
  mana)` — bagian *di mana* berjalan; bagian *apa* **hanya berlaku untuk
  tulis**. `ModelPermission.has_permission()` mengembalikan `True` untuk
  seluruh `SAFE_METHODS`, dan **tidak ada satu pun pemeriksaan izin
  `view_*` di seluruh codebase**. Jadi cakupan baris adalah
  satu-satunya yang membatasi baca hari ini.
- **`EXPLICIT` + nol baris = tanpa batasan** (bukan tanpa akses), dan
  **satu role `all` membatalkan pembatasan seluruh role tetangganya**.
  Keduanya gagal ke arah terbuka, dan keduanya tidak berbunyi.
- **`OWN` gagal ke arah aman**: penempatan kosong → `denied`, tidak
  pernah dilonggarkan.
- **`UserDataPermission` selalu menambah** — tidak bisa mempersempit
  role, tidak bisa menimpa `all`.
- **Cakupan bersifat per-orang, bukan per-role.** `for_user()` meng-OR
  seluruh role, jadi satu role `all` melebarkan data **seluruh modul**,
  termasuk modul yang role itu tidak ada urusannya.
- **Cakupan tidak bisa ditembus lewat id langsung.** `filter_queryset()`
  menutup list, retrieve, export, update, dan delete sekaligus.

#### Angka cakupan — koreksi atas Phase 1

Angka "50/115 lookup" dan "36/77 viewset" di catatan sebelumnya
**berasal dari grep dan salah**. Hasil introspeksi sungguhan:

| Permukaan | Total | Bercakupan | Tanpa cakupan | Yang *bisa* dicakup |
|---|---|---|---|---|
| Master ViewSet | 76 | 33 | 43 | **12** |
| Lookup terdaftar | 113 | 11 | 102 | **16** |

86 lookup sisanya memang data referensi (gender, bank, geografi, tarif
pajak, konfigurasi BPJS) — **global yang disengaja**, bukan kelalaian.
`/api/hr/employees/lookup/` (dirujuk 30 schema, yang paling sensitif)
**sudah bercakupan**, begitu juga kesembilan lookup organisasi.

#### Blast radius `EXPLICIT`-nol → DENY

Disimulasikan per pengguna: **2 role, 1 pengguna** (`demo.homanager`,
`UNRESTRICTED` → `[{'own': True}]`). Sisanya tidak bergerak.

**Tapi perubahannya tetap DIBLOKIR**, dan bukan oleh angka itu: hanya
**2 dari 8** jenis dokumen berworkflow yang menyatakan
`workflow_document` (`leave_request`, `payroll_run`). Enam sisanya —
termasuk `attendance_permission` — membuat approver mendapat baris di
kotak masuk untuk dokumen yang **tidak bisa ia buka**. Mempersempit
cakupan sekarang memperluas masalah itu.

#### TESTED

`apps/accounts/tests/test_data_scope_semantics.py` — **15/15 OK**
(397,7 s). Karakterisasi murni: mengunci perilaku yang berlaku hari ini
terhadap `scoping.py` yang **tidak disentuh**, tiap skenario dengan
assertion negatif. Termasuk ketiga aturan yang gagal ke arah terbuka —
supaya perubahannya nanti tidak bisa terjadi diam-diam.

Regresi Phase 1 diulang sesudahnya: `apps.hr.tests.attendance_permission`
**64/64 OK** (1662,0 s). `manage.py check` bersih ·
`makemigrations --check` **No changes detected**.

#### OPEN — dicatat, sengaja tidak diperbaiki

- **MERAH — baca tidak punya gerbang izin sama sekali.** "Punya cakupan
  Company A tapi tidak punya `payroll.view_*` → tidak boleh membaca
  payroll Company A" **tidak berlaku hari ini**
- `FINANCE-MANAGER` (nol izin, nol baris) dan `SECURITY-GATE` (7 izin,
  nol baris) tanpa batasan karena kelalaian
- 6 dari 8 dokumen berworkflow tanpa `workflow_document`;
  `register_route` untuk `attendance_permission` juga belum ada
- 12 viewset + 16 lookup yang bisa dicakup tapi belum
- **10 salinan peta cakupan pegawai** (`framework`, HR, notifications,
  5 report service)
- `ui-schema` + `framework_schema_view` bersifat `AllowAny` — metadata
  model terbaca tanpa login (bukan baris data)
- `ADMIN-DEPARTMENT` bermode `own`/**location** meski namanya menyebut
  departemen, dan identik dengan `ADMIN-SECTION`

#### DEFERRED

- **Enterprise Workflow Authority / Option C — BELUM DIIMPLEMENTASIKAN.**
  Urutannya berubah karena audit ini: **gerbang izin baca harus
  ditutup lebih dulu**, kalau tidak Option C membangun wewenang di atas
  fondasi yang memberi *di mana* tanpa pernah memeriksa *apa*
- Perubahan semantik `EXPLICIT`-nol → DENY, menunggu prasyarat di atas
- Cakupan yang sadar-role (bukan per-orang) — mengubah bentuk sistem

**Yang belum bisa dijawab tanpa pemilik aturannya:** maksud bisnis
`FINANCE-MANAGER` dan `SECURITY-GATE`. Menebaknya berarti mengarang
cakupan; itu sebabnya Stage 1 tidak dijalankan.

---

### Workflow — cakupan meja Role Holder (`approver_scope`)
Status: **Phase 1 SELESAI** — 8 Sep 2026. Yang berubah **satu nilai
konfigurasi**; tidak ada arsitektur yang disentuh.

**Temuan UAT browser.** Izin Bimo Nugroho (Jakarta HO) menerbitkan dua
kotak tanda tangan di meja HR — Hesti (HO) dan Eko (site) — lalu Eko
`SKIPPED` begitu Hesti menyetujui. **ANY-ONE-nya benar**; yang salah
satu tingkat sebelumnya: Eko tidak pernah berwenang atas pegawai HO.

**Akar masalahnya konfigurasi, bukan engine.** Meja itu
`approver_scope = COMPANY`, jadi resolver memang menarik seluruh
pemegang `HR-ADMIN` se-company. Diubah ke `LOCATION`, dan selesai.

#### Yang sekarang CONFIRMED

- **Alur izin kehadiran dua tahap**, dan berhenti di dua. Tidak ada
  meja HR Manager ketiga.
  `Employee → Atasan Langsung → HR Admin pada Location → Approved`
- Tahap 2: `ApproverType.ROLE`, role **`HR-ADMIN`**, `approver_scope =
  LOCATION`, `is_required=True`, `approval_mode = ANY`,
  `fallback_role = HR-MANAGER` (se-company, jaring pengaman untuk
  lokasi yang belum punya HR Admin; pelebarannya tercatat sebagai
  `HR_MANAGER_FALLBACK`, bukan diam).
- **Satu alur cukup untuk HO dan site.** Yang membuatnya bisa: HR site
  dan HR kantor pusat memang memegang **kode role yang sama**, dan yang
  memisahkan keduanya penempatan organisasinya. Terbukti di tenant
  `demo`: Bimo (JKT-HO) → **Hesti saja**; Ahmad (SAGEA-MINE) → **Eko
  saja**. Tidak perlu alur kedua, tidak perlu role kedua.
- **Cakupan meja hari ini = penempatan organisasi calon approver**
  (`_role_holders()` menyaring `organization__<scope>_id`).
  `DataScopeService` **belum** dipakai resolver, dan itu keadaan yang
  disengaja untuk fase ini.
- **ANY-ONE tidak berubah.** Beberapa HR Admin pada lokasi yang sama →
  semua dapat baris; satu menyetujui, sisanya `SKIPPED`, mejanya
  selesai satu kali.
- **Wewenang ditegakkan server-side.** Orang di luar cakupan tidak
  punya baris keputusan sama sekali. Baris milik orang lain ditolak
  `check_right()` → `ValidationError({"workflow": …})` → **HTTP 400**
  (bukan 403 — itu kontrak yang memang berlaku, dan tidak diubah).
- **Riwayat tidak bergeser.** Approver dibekukan saat submit.
  `APRM-2026-000017` diperiksa lewat sidik jari SHA-256 atas seluruh
  baris keputusan + metadata: **identik** sebelum dan sesudah
  `seed_workflows` dijalankan ulang. Metadatanya masih menyebut
  `resolved_scope = company` — dokumen lama tetap merekam cakupan yang
  berlaku saat ia diputuskan.

#### Seed vs layar: keduanya sempat saling membatalkan

Nilai `LOCATION` sudah lebih dulu diubah **tangan** lewat layar Workflow
di tenant `demo`, sementara seed masih `COMPANY`. `_write()` memakai
`update_or_create(defaults=…)`, jadi `seed_workflows` berikutnya akan
mengembalikannya **tanpa pesan apa pun**. Seed sekarang disamakan, dan
sudah diverifikasi: sesudah `seed_workflows` dijalankan ulang,
`approver_scope` tetap `location`.

#### Role `*-SITE` — TIDAK dipindah, dan ini alasannya

Rencana awal memindahkan Eko dari `HR-ADMIN` ke `HR-ADMIN-SITE`
(mode `own`/`location`) **dibatalkan**. Bukan karena role-nya salah —
melainkan karena `HR-ADMIN`/`HR-MANAGER` dirujuk **13 step di 10 alur**,
dan **5 di antaranya ber-`scope=location` tanpa cadangan sama sekali**:

```
HR-LEAVE-SITE     #2 HR Admin Site Review        HR-ADMIN    location  (none)
HR-LEAVE-SITE     #4 HR Manager Site Approval    HR-MANAGER  location  (none)
HR-TR-SITE        #2 HR Admin Site Review        HR-ADMIN    location  (none)
HR-TR-SITE        #4 HR Manager Site Approval    HR-MANAGER  location  (none)
HR-ROSTER-SETUP   #3 Approved By (HR Mgr Site)   HR-MANAGER  location  (none)
```

Memindahkan pemegangnya mengosongkan kelima meja itu dan membuat cuti,
travel request, dan roster setup site **tidak bisa diajukan sama
sekali**. `demo_workforce.py` mencatat bahwa pendekatan itu memang
pernah dicoba lalu direvert dengan gejala persis itu.

**Pelajarannya bukan "role-nya redundan".** `HR-ADMIN-SITE` /
`HR-MANAGER-SITE` / `EXECUTIVE-SITE` punya semantik DataScope yang
nyata (`own` pada level tertentu). Yang terbukti: **penugasan pemegang
role tidak boleh diubah setempat tanpa membaca seluruh graf workflow.**
Status: **AUDIT / KEEP AS-IS.** Tidak ada konsolidasi di Phase 1.

#### Dua konsep cakupan, sengaja masih terpisah

```
A. DATA VISIBILITY                    B. WORKFLOW ELIGIBILITY
   RoleDataPermission                    WorkflowStep.approver_scope
   UserDataPermission                    + penempatan pegawai subjek
   Role.data_scope_mode                  + OrganizationAssignment calon
        -> DataScopeService                   -> candidate Role Holder
        -> queryset/layar
```

Keduanya menjawab pertanyaan yang berbeda dan **belum disatukan**.
Penyatuannya (Option C) adalah pekerjaan berikutnya dan **belum
diimplementasikan**.

#### Hasil regresi (8 Sep 2026, database test terisolasi, sekuensial)

| Suite | Hasil | Waktu |
|---|---|---|
| `apps.hr.tests.attendance_permission` | **64/64 OK** | 1918,8 s |
| `test_ho_leave_workflow` + `test_roster_setup_scope` + `travel_request` | **140/140 OK** | 2500,1 s |
| `test_leave_access_control` + `test_calendar_access` + `test_calendar_scoping` | **70/70 OK** | 1050,8 s |
| **Total** | **274/274 OK** | — |

`manage.py check` bersih · `makemigrations --check` **No changes
detected** · frontend `pnpm build` **exit 0** (30,2 MB) dua kali.

#### Label Bahasa Indonesia — display only

Peta terpusat `apps/workflow/labels.py`, dipakai schema (dropdown +
kolom) dan serializer (`*_label`). **Sengaja bukan di
`models.TextChoices`** — label `TextChoices` ikut state migration, dan
`makemigrations --check` yang bersih adalah buktinya display-only.
Nilai enum/API/database **tidak berubah satu huruf pun**: `manager`,
`role`, `location`, `any`. 62 berkas modul frontend diregenerate.

---

### Attendance Permission (Izin Kehadiran)
Status: **DONE (backend)** — 7 Sep 2026. Frontend belum digenerate.

Izin kehadiran yang bukan cuti — terlambat, pulang cepat, keluar
sementara, tidak masuk sehari — sebagai domain tersendiri di dalam modul
Attendance. **Bukan** `LeaveType` baru: cuti punya saldo, entitlement,
carry over, dan go-live date; izin tidak punya satu pun dari semuanya.

**Yang tidak berubah, dan itu inti desainnya.** `late_minutes` tidak
berkurang satu menit pun karena ada izin. Yang berubah klasifikasinya,
dan itu ditulis di kolom terpisah (`excused_late_minutes`,
`excused_early_leave_minutes`, `permission_minutes`,
`is_excused_absence`, `permission_state`) — sehingga "terlambat 2 jam
karena izin" dan "terlambat 2 jam tanpa izin" tetap dua baris yang
angkanya sama dan perlakuannya berbeda. Pelajaran yang sama dengan
`leave_required_days` vs `leave_required_override`.

**Yang dipakai ulang, bukan dibuat lagi:** engine `apps/workflow`
(alur `HR-ATT-PERMISSION`, Atasan Langsung → HR, configurable lewat
layar), `shift_span()` untuk shift malam, `scheduled_work_days()` untuk
hari libur/blok off, framework import/upload/audit, dan arsitektur
payroll policy.

**Tiga keputusan yang menahan diri:**

1. **Status presensi tetap `ABSENT` + `is_excused_absence`**, bukan
   `AttendanceStatus.PERMIT`. Menggeser statusnya akan mengeluarkan
   hari itu dari potongan payroll **diam-diam** — dan dibayar atau
   tidak adalah keputusan kebijakan, bukan efek samping kolom status.
2. **Bawaan perlakuan payroll `INFORMATION_ONLY`, bukan PAID.** Izin
   yang disetujui menyatakan ketidakhadirannya sah, bukan bahwa
   perusahaan membayarnya. Konsekuensinya: tabel `PayrollPermissionRule`
   yang kosong **tidak menggeser satu rupiah pun** dari baseline
   sekarang; yang bertambah cuma angka di `PeriodFacts` plus temuan yang
   menyebut jenis izin mana yang belum punya aturan.
3. **Locking memakai `PayrollPeriod` FINALIZED**, tanpa model periode
   presensi baru — dua tabel periode berarti dua jawaban untuk satu
   pertanyaan.

**Yang belum ada:** layar FE (schema backend sudah lengkap), layar
`PayrollPermissionRule` (barisnya baru bisa diisi lewat shell/admin),
dashboard monitoring, notifikasi keputusan ke pengaju, dan **alur
adjustment untuk periode terkunci** — pesan penolakannya menunjuk
Attendance Adjustment yang masih berupa item menu tanpa layar.

Detail lengkap: `docs/claude/hr/attendance-permission.md`.

**Seed wajib diulang di tiap tenant:** `migrate_schemas --tenant`,
`seed_administration --only=numbering` (deret APRM), `seed_workflows`,
`seed_menus`, dan **`seed_security_roles`** — permission
`add_attendancepermission` lahir bersama modelnya, dan gejala lupanya
403 di layar yang seharusnya boleh.

---

### Payroll — Business Decision #2: ketidakhadiran mengurangi penghasilan
Status: **CLOSED** — 7 Sep 2026. Keputusan bisnisnya disetujui dan
mesinnya menyesuaikan.

**Yang ditemukan:** mesin **belum** menerapkannya. Alpa dan cuti tidak
dibayar sudah punya baris sendiri, sudah terbaca, sudah tidak pernah
dihitung dua kali, dan pembaginya sudah kebijakan perusahaan — tapi
keduanya berdiri sebagai **potongan** sesudah penghasilan ditutup, jadi
gross dan dasar pajak menyebut gaji yang tidak pernah didapat. Ada test
yang justru menjaga perilaku itu (`TaxableBaseTest`), ditulis waktu
pertanyaannya masih terbuka.

**Yang diubah — agregasinya, bukan bentuk barisnya.** Baris
`ABSENT`/`UNPAID-LEAVE` tetap `component_type = deduction` bermagnitudo
**positif**, kontrak tanda yang sama dengan seluruh potongan lain.
`_settle_earnings()` mengurangkannya dari gross dan taxable,
`_settle_totals()` mengeluarkannya dari `total_deduction` — pasangan
itu yang membuatnya terhitung tepat sekali. `net_pay` tidak bergeser
satu rupiah pun.

Percobaan pertama membalik tandanya jadi baris `earning` negatif.
Itu **salah**: ia diam-diam ikut membalik baris potongan biasa yang
kebetulan berbasis per hari alpa (denda, cicilan), dan membuat baris
lama di database tidak lagi sebanding dengan baris baru. Ketahuan dari
tiga test regresi yang memang menjaga kontrak itu.

**Satu hal tersisa OPEN:** basis `per_absent_day` yang dipakai tenant
untuk **denda** (hukuman di atas gaji yang hilang) sekarang ikut
mengurangi gross dan taxable, padahal denda memang uang yang ditahan.
Tidak ada kolom yang membedakannya, dan menambah flag adalah keputusan
kebijakan yang belum diambil.

Detailnya di backend: `docs/claude/payroll.md` → Ketidakhadiran
(Business Decision #2).

---

**Payroll — Business Decision #5 selesai.** Calendar Scope & Import
sudah ditutup dan tidak disentuh lagi.

### Calendar Scope & Import

**Status: DONE** (backend + frontend) — 5 Sep 2026.

Master kalender tidak lagi diduplikasi per company. `WorkCalendar` dan
`Holiday` sekarang punya `scope`; `company` boleh kosong dan kosong
berarti **berlaku untuk semua**, termasuk perusahaan yang dibuat
kemudian — tanpa import ulang.

- **Resolver terpusat** `CalendarResolver`
  (`apps/administration/services/calendar_resolver.py`).
  `LeaveDayCalculator` mendelegasikan kepadanya; Attendance, Leave,
  Payroll, Reports, dan Shift Calendar ikut lewat sana. Presedensi:
  override pegawai → LOCATION → COMPANY → GLOBAL → Senin–Jumat.
  Hari libur **digabung**, bukan dipilih yang paling spesifik.
- **Import Work Calendar & Holiday** lewat framework import yang sudah
  ada — bukan engine baru. Preview menandai NEW/UPDATE; tidak ada
  penimpaan yang diam. Satu baris GLOBAL tetap satu record.
- **External sync**: kolom + abstraction + gerbang review sudah ada dan
  berlaku (baris `PENDING` tidak dibaca resolver). **Provider
  Google/Government/ICS sengaja belum ditulis** — lihat calendar.md.
- **Duplikat lama tidak digabung otomatis.**
  `collapse_calendar_duplicates` (dry-run bawaannya) yang
  melakukannya, dan itu keputusan: penggabungan mengubah hari kerja,
  jadi tidak boleh ikut `migrate` saat deploy.

Detail lengkap: `docs/claude/calendar.md`.

**Regresi akhir: 83 test OK** (`apps.administration.tests.calendar` +
`apps.hr.tests.roster.test_leave_day_calculator`, 1001,9 detik) — nol
gagal, nol error, nol dilewati. Dijalankan **ulang sesudah** perbaikan
wiring Celery, bukan sebelumnya.

**UAT browser + API: LULUS** (tenant `demo`, 5 Sep 2026).
`scripts/uat/calendar-scope.mjs` di repo Nuxt — 33/33, dan
`scripts/uat/holiday-import-confirm.mjs` — 9/9 untuk alur import
sampai worker: Upload → Preview → Confirm → `run_import.delay()` →
Celery → baris terlihat di tabel Holiday sebagai `GLOBAL / All
Companies`, satu baris. Unggah ulang berkas yang sama menghasilkan
`created=0 updated=1` — tidak ada duplikat.

Collapse sudah **dijalankan di demo**: work calendar 9→7, holiday
15→9, dan tiap libur nasional kini satu baris. Hari kerja & hari libur
efektif tiap company/location **tidak berubah sama sekali**; 8
employment assignment dipindah ke keeper, **0 FK putus**.

Empat temuan UAT yang tidak tertangkap unit test:

1. **Rute import mati.** `app/pages/administration/calendar.vue` +
   direktori `calendar/` membuat Nuxt memperlakukan workspace sebagai
   layout induk, jadi kedua layar import diam-diam merender halaman
   Calendar. Diperbaiki jadi `calendar/index.vue` — konvensi yang
   sudah dipakai `hr/leave-opening-balances/`.
2. **Collapse pecah di jalur upgrade yang didokumentasikan sendiri.**
   Seed baru (menerbitkan GLOBAL) lalu collapse → tabrakan constraint,
   dan berhentinya **di tengah**. Ditambah jalur `ADOPT` + 3 test.
3. **Dua peringatan `PERIKSA`** untuk resolusi yang berubah tanpa
   baris disunting: (a) sesudah digabung ada dua baris GLOBAL
   ber-`is_default` dan pemenangnya ditentukan id terkecil; (b)
   company yang masih memegang kalender COMPANY lain membuat kalender
   itu **menang** atas GLOBAL yang baru dipromosikan. Keduanya
   **tidak** diselesaikan otomatis — operator yang memutuskan.
   Rinciannya di `calendar.md`.
4. **`.delay()` tidak pernah sampai ke broker.** `config/__init__.py`
   **hilang dari working tree** (isinya sendiri sudah benar sejak
   commit pertama), jadi `@shared_task` terdaftar pada app Celery
   bawaan dan setiap dispatch dari proses web gagal `[Errno 61]
   Connection refused` **padahal Redis sehat**. Sempat salah
   didiagnosis sebagai koneksi basi. **Bukan bug Calendar** — seluruh
   importer terdampak. Berkasnya dipulihkan; worker juga wajib
   di-restart saat importer baru mendarat. Duduk perkaranya di
   `architecture.md` § *Task Queue & Cache*.

**Yang harus dijalankan di tiap tenant lama** (belum otomatis):

```
python manage.py migrate_schemas --tenant
python manage.py tenant_command seed_import_profiles --schema=<t>
python manage.py tenant_command collapse_calendar_duplicates --schema=<t>
# baca laporannya — terutama baris PERIKSA/SKIP/EXCEPTION — baru --apply
```

**Worker Celery wajib ikut di-restart saat deploy.** Worker lama tidak
mengenal importer baru dan job-nya berakhir `failed` dengan pesan
`No importer registered for module '...'` — job-nya sampai ke worker,
jadi gejalanya bukan antrian macet melainkan import yang gagal diam.
Terkena saat UAT ini.

### Payroll — Business Decision #5: beban perusahaan

**Status: DONE** — 5 Sep 2026.

Iuran yang dibayar perusahaan tidak lagi menumpang kolom potongan
pegawai. Sumbunya sendiri (`PayrollComponentType.EMPLOYER_CONTRIBUTION`),
dikonfigurasi lewat `DeductionTemplateLine.is_employer_cost`. `net_pay`,
`gross_earning`, dasar PPh21, dan `tax_amount` **tidak bergerak sama
sekali** — `_settle_totals` dan `_tax` tidak diubah satu baris pun,
karena penyaring `component_type` yang sudah ada mengecualikannya
sendiri. `Total Payroll Cost = Gross + Employer Contribution`, bukan
Net. Dashboard mendapat kartu *Beban Perusahaan* dan *Total Biaya
Payroll*.

**Keputusan bisnis baru yang lahir dari sini** (belum diambil, dan
tidak boleh diputuskan terpisah dari #4/PPh21): premi perusahaan yang
diperlakukan sebagai penghasilan kena pajak pegawai — lazimnya
JKK/JKM. Hari ini tidak satu pun komponen beban perusahaan menyentuh
`taxable_earning`.

Detail: `docs/claude/payroll.md` → Beban perusahaan.

### Payroll — baseline per 5 Sep 2026: stable

- **270 payroll test OK** (`python manage.py test apps.payroll`, ~75 menit)
- Business Decision **#1–#5 selesai** (prorata gaji pokok · potongan
  absen & cuti tidak dibayar · aturan hitung tunjangan · lembur
  bertingkat · beban perusahaan)
- **Payroll Policy per assignment** + **daily payroll**
  (`daily_rate × paid_days`) implemented
- **Salary Change hotfix** fixed — kenaikan gaji membawa seluruh
  konfigurasi payroll, dan menyisakan tepat satu baris berjalan
- **Payroll Dashboard** VERIFIED (backend + frontend) — `/payroll/dashboard`, menu Payroll → Dashboard
- **Rekap run** tidak lagi membocorkan angka di luar cakupan pembacanya
- **PPh21 masih PROVISIONAL** — bukan production rule final

Detail: `docs/claude/payroll.md`.

### Keputusan yang masih terbuka sebelum Payroll boleh dinyatakan production-ready

Selama satu pun masih terbuka, Payroll **tidak** production-ready.
Jangan menebaknya; tanyakan, lalu tulis jawabannya di `payroll.md`.

| # | Yang belum diputuskan |
| --- | --- |
| #2 | Absen mengurangi **penghasilan** atau menambah **potongan**? Menentukan dasar PPh21 — tidak boleh diputuskan terpisah dari #4 |
| #3 | Komponen BPJS yang dipotong dari pegawai, persentase, dan plafonnya (angka yang diseed sekarang **data peragaan**) |
| #4 | Metode PPh21 produksi — biaya jabatan? TER PP 58/2023? perhitungan akhir tahun? `PayrollTaxBracket` **tidak diubah** sampai ini diputuskan |
| #7 | Siapa yang menyetujui payroll (`PAY-RUN-STD` dua meja adalah bawaan, bukan kebijakan) |
| sub #4 | **Basis reset tingkat lembur** — per hari lembur atau total jam sebulan. `tier_basis` tanpa bawaan; yang belum menyatakannya ditolak validasi |
| sub Policy | **Daily paid leave** — pekerja harian pada hari cuti yang disetujui: dibayar atau tidak. `pay_paid_leave` tanpa bawaan; kebijakan harian yang belum memilih ditolak validasi run |
| baru | Dasar **`% of Basic` untuk pegawai harian** — gaji sebulan yang tercatat, atau upah harian yang terbentuk periode itu |
| baru | **Premi perusahaan yang jadi penghasilan kena pajak pegawai** (lazimnya JKK/JKM). Hari ini beban perusahaan tidak menyentuh `taxable_earning` sama sekali — tidak boleh diputuskan terpisah dari #4 |

Daftar lengkap beserta alasannya: `docs/claude/payroll.md` →
BUSINESS DECISION REQUIRED.

**Business Decision #3A — arsitektur BPJS: DONE (backend).** BPJS jadi konsep kelas satu (`BpjsProgram`,
`BpjsRule` bertanggal berlaku yang mengikat sisi pegawai & perusahaan
dalam satu baris, komposisi dasar aman-versi, `BpjsEnrollment`
bertanggal berlaku). Aturannya menumpang mesin hitung yang sudah ada
lewat objek berbentuk baris — **tidak ada mesin hitung kedua**. Enam
keputusan yang diambil ada di `payroll.md` → Arsitektur BPJS.

**Belum diputuskan dan tidak boleh ditebak:** tarif, plafon, pegawai
harian, prorata masuk/keluar, cuti tidak dibayar, premi tanggungan,
pembulatan, dan pajak premi perusahaan (yang terakhir tetap terikat
#4).

**Business Decision #3B.1 — infrastruktur regulasi dinamis: DONE
(backend).** Nilai regulasi jadi data bertanggal berlaku, bukan
konstanta mesin hitung. Yang lahir: `BpjsRiskClass` (identitas, tanpa
angka), `BpjsProgram.uses_risk_class`, `risk_class` pada aturan dan
kepesertaan dengan resolusi **ketat** (COMPANY+kelas persis →
GLOBAL+kelas persis → ERROR, tanpa jatuh-tempo ke aturan umum dan tanpa
pinjam-tarif antar kelas), kemampuan dasar iuran pegawai harian
(`daily_basic_method`/`daily_basic_factor`, tanpa bawaan pengali), dan
`BpjsRuleService.close_and_publish()` yang menutup-dan-menerbitkan
dalam satu transaksi. `is_active` tidak lagi bisa dipakai sebagai
saklar sejarah. Detailnya di `payroll.md` → Infrastruktur regulasi
dinamis.

**Business Decision #3B.2 — konfigurasi statuter terverifikasi: DONE
sebagian (backend).** Diterbitkan lewat `bpjs_publish_statutory`
(dry-run bawaannya, tanpa migration, tanpa seed): JHT 2%/3,7%; JP
1%/2% berplafon 11.086.300 berlaku 1 Mar 2026; JKK per lima kelas
risiko 0,10/0,40/0,75/1,13/1,60% (**pasca-rekomposisi**); JKM 0,30%.
Dasar iuran = gaji pokok + kode tunjangan tetap yang **ditulis
operator**. Harian ×25 hanya untuk JKK/JKM/JHT; JP memakai komposisi
tanpa cara harian karena PP 45/2015 tidak mengaturnya. Detailnya di
`payroll.md` → Konfigurasi statuter terverifikasi.

**Pemetaan tunjangan tetap per perusahaan: DONE (backend).** Tanpa
model baru dan tanpa migration — arsitektur #3A sudah menanggungnya
(`BpjsRule.company` nullable, resolusi COMPANY → GLOBAL, komposisi
dasar berversi). Yang dibatasi cuma penerbitnya: `--fixed-allowance`
dulu se-tenant. Sekarang cakupan **wajib** disebut (`--global` atau
`--company=KODE`, tidak boleh keduanya), kode tunjangan yang tidak ada
**menolak** publikasi, dan kode komposisi per perusahaan diberi sufiks
(`UPAH-BPJS-H25-MMR`) supaya versinya berdiri sendiri. Basis tunjangan
ditampilkan di dry-run tapi **tidak dipakai menilai** — tidak ada flag
tunjangan-tetap-statuter yang disetujui, jadi pemetaannya tetap ditulis
operator. Detailnya di `payroll.md` → Pemetaan tunjangan tetap per
perusahaan.

**Masih OPEN sesudah #3B.2:** tarif dan komposisi upah **JKN** (hanya
plafon 12.000.000 yang terverifikasi; programnya ada tanpa aturan);
**JKP** (pendanaannya terverifikasi, cara penagihannya belum — butuh
tagihan BPJS sungguhan); harian & borongan JP; borongan JKK/JKM/JHT
(butuh rata-rata 3/12 bulan yang belum ada di model); batas bawah JKN
regional (UMP/UMK per wilayah, tidak terwakili kalau satu company
melintasi beberapa wilayah upah minimum); prorata masuk/keluar; cuti
tidak dibayar; pembulatan; PPh21 dan pajak premi perusahaan (#4).

**#3B.2 masih OPEN — sisa angkanya.** Tarif, plafon, lantai, tarif
per kelas risiko, pengali harian, JKP, prorata masuk/keluar, cuti tidak
dibayar, premi tanggungan, pembulatan khas BPJS. Tidak satu pun boleh
ditebak dari repo ini.

**#3B: matriks keputusan sudah jadi, statusnya OPEN.** Isinya register
keputusan yang sedang dipakai; jawabannya belum ada. Perilaku hari ini
untuk masuk/keluar tengah periode dan cuti tidak dibayar **bukan
kebijakan yang disetujui** — ia cuma mempertahankan baseline tanpa
menebak. Tarif dan plafon peragaan **tidak boleh** dinaikkan jadi
konfigurasi produksi. Implementasi menunggu baseline regulasi yang
terverifikasi plus keputusan bisnis yang eksplisit.

**Cutover belum dijalankan di tenant mana pun.** Migration hanya
menerbitkan tabelnya; tidak satu baris data pun berpindah otomatis dan
tidak satu baris Deduction Template pun dinonaktifkan otomatis. Yang
memindahkannya `bpjs_migrate_templates` (dry-run bawaannya), dengan
pemetaan program yang **ditulis operator** dan gerbang selisih-nol yang
membatalkan cutover kalau ada satu rupiah pun berubah.

**Tenant `demo` belum bisa di-cutover, dan bukan karena BPJS.** Dry-run
menolak dengan 24 baris berubah. Kontrol yang menghitung ulang run
terbuka **tanpa perubahan BPJS apa pun** menghasilkan 24 baris yang
sama persis dengan angka yang sama — jadi cutover-nya sendiri
berselisih **nol**, dan yang menolak adalah selisih yang sudah ada
sebelumnya antara angka tersimpan dan hasil hitung ulang (13 baris
hanya `employer_contribution`, warisan keputusan #5 yang belum pernah
dihitung ulang sejak kolomnya ada; 11 baris ikut net/potongan).
Gerbangnya benar menolak. Yang perlu dibereskan lebih dulu run
terbukanya, bukan gerbangnya.

**Kandidat pekerjaan berikutnya:** kartu & kolom **Employee BPJS**,
yang sekarang tinggal satu kartu di `schema.py` + satu kategori di
`services.COMPOSITION` — identitas authoritative-nya sudah ada
(`PayrollComponentSource.BPJS`).

---

## Pending / Next

### Payroll

- Laporan **Bank Transfer** dan **Tax Report** — dua item menu yang
  belum punya halaman
- **Komponen employer (BPJS bagian perusahaan)** — belum ada kolom yang
  memisahkan beban perusahaan dari potongan pegawai; menyatukannya di
  satu kolom membuat laporan biaya tenaga kerja salah. Ini juga yang
  membuat Dashboard tidak punya kartu Employer Contribution / Total
  Payroll Cost
- **Importer Payroll Input** (schema `import` belum diisi)
- **THR / bonus tahunan** sebagai perhitungan tersendiri; hari ini lewat
  `PayrollInput` bertipe Incentive pada run `off_cycle`
- **Payroll belum memakai resolver Feature Applicability** — langkahnya
  sudah tertulis di `docs/claude/hr/employee-group.md`

Rinciannya: `docs/claude/payroll.md` → "Yang belum ada".

### HR / Roster / Shift

- **Crew/Team Calendar** dan **Location Calendar** — resolver per
  pegawai sudah benar, agregasi + endpoint-nya belum ada
- **Bulk assign shift dari layar** — service-nya sudah menerima banyak
  pegawai, belum ada action/endpoint
- **Pola shift belum tersimpan** — Set Shift Pattern menulis hasilnya,
  bukan polanya. Rumah wajarnya `RosterPolicy`, kolom master baru =
  keputusan tersendiri
- **Perputaran mengulang dari awal di tiap blok kerja** — yang berlanjut
  antarblok belum ada (disengaja)
- **Approval untuk penyesuaian shift belum ada**
- **Jeda minimum tidak diperiksa pada `OVERRIDE`** — disengaja, tapi
  tetap lubang kalau perusahaan memutuskan sebaliknya
- **Split-by-supervisor untuk dokumen Roster Setup batch** belum ada;
  memecah dokumen masih pekerjaan tangan
- UAT browser Roster Assignment & Travel Request (penyaring Feature
  Applicability) belum

Rinciannya: `docs/claude/hr/shift-calendar.md` → "Belum ada / NEXT",
`docs/claude/hr/roster.md`.

### Attendance

- **`AttendanceDeviceEmployee` dan `AttendanceDevice` belum punya
  endpoint & layar CRUD** — diisi lewat seed/Django admin
- **Reprocess dari `AttendanceLog`** belum ada; tabelnya sudah terisi
- **Jalur import lama** (`/api/hr/attendance/import/…`,
  `AttendanceImportProfile`) masih hidup tanpa device mapping/scope;
  belum dihapus
- **`EmployeeAttendance.shift` baru diisi seed** — importer masih
  membiarkannya kosong
- UAT pengecualian di site belum bisa dijalankan: `ATT-MMR-SITE`
  mematikan kedua ambang cuti (0/0). Itu **konfigurasi hidup**, bukan
  bug — sisi HO sudah terbukti jalan
- UAT browser layar Attendance Import belum

Rinciannya: `docs/claude/hr/attendance-import.md`.

### Reports

- **Contract Expiry** — As Of Date yang bisa dipilih (butuh tipe filter
  tanggal baru di runtime dashboard FE); contract completeness;
  Probation Expiry; riwayat perpanjangan
- **Manpower Summary** — headcount as-of & tren per bulan (butuh riwayat
  penempatan); breakdown per Section/Position/Job Level
- **Manpower Movement** — filter Department/Section/Group/Type tidak
  ikut menentukan mutasi masuk/keluar; penempatan baris Join/Exit dibaca
  dari keadaan sekarang; employee importer masih menembus penjagaan
  penempatan; Transfer In/Out kosong untuk periode sebelum penjagaan
  berlaku (permanen). Frontend & UAT browser belum
- **Manpower Trend** belum dikerjakan — komposisi organisasi lampau baru
  bisa dijawab untuk periode yang mutasinya sudah berdokumen
- Belum dikerjakan, masing-masing task terpisah: Leave Balance,
  Attendance Exception, Overtime, Turnover, Position/Vacancy,
  Contractor Workforce

Rinciannya: `docs/claude/reports.md` → "Known limitation / NEXT".

### Workflow / Scope — NEXT (Phase 2, belum dimulai)

Phase 1 sudah menutup kasus Attendance Permission dengan konfigurasi.
Yang tersisa memang butuh keputusan arsitektur, dan **jangan dikerjakan
sebagai perbaikan setempat**:

1. **Wewenang lintas penempatan.** Hari ini cakupan meja Role Holder =
   penempatan calon approver, dan `OrganizationAssignment` itu
   **OneToOne** — jadi "HR Manager duduk di HO tapi berwenang atas
   seluruh site Company A" tidak bisa dinyatakan sama sekali. Yang
   terdampak: HR Manager korporat, GM multi-company, Procurement
   multi-company, BOD. Data Permission sudah bisa menyatakannya; meja
   approval belum membacanya
2. **Option C** (organizational matching **+** authority matching) —
   opsi yang direkomendasikan audit, **belum diimplementasikan**. Dua
   syarat yang tidak bisa ditawar kalau nanti dikerjakan: (a) "role
   tanpa baris cakupan = tanpa batasan" **tidak boleh** diterjemahkan
   jadi "eligible di mana saja"; (b) cakupan dibaca dari **role yang
   disebut step-nya**, bukan `for_user()` yang meng-OR seluruh role
3. **Verifikasi ketujuh nilai `ApproverScope`** terhadap resolver satu
   per satu — bukan terhadap dropdown. `cost_center` ada di
   `DataScopeLevel` tapi **tidak ada** di `ApproverScope`
4. **Graf ketergantungan role sebelum menyentuh penugasan siapa pun.**
   Phase 1 nyaris mengosongkan 5 meja tanpa cadangan karena melihat
   satu alur saja. Yang dibutuhkan: laporan "role X dipakai step mana,
   dengan cakupan apa, dengan cadangan apa" sebelum satu pemegang pun
   dipindahkan

### Enterprise Data Scope — NEXT (Phase 2 Stage 1, menunggu keputusan)

Berurutan. Stage 2 tidak boleh dimulai sebelum Stage 1 hijau.

**Stage 1 — SELESAI 8 Sep 2026.** Rinciannya di bagian "Enterprise Data
Access Scope — Stage 1" di atas.
1. ~~Nyatakan maksud cakupan `FINANCE-MANAGER` dan `SECURITY-GATE`~~ —
   maksudnya ditetapkan pemilik aturan, lalu diseed: keduanya `own`
   (Company / Location)
2. ~~Gerbang izin pada jalur baca (`view_*`)~~ — naik dari Stage 3 ke
   Stage 1 karena ternyata **ini** lubang terbesarnya, bukan
   `EXPLICIT`-nol
3. ~~`data_scope` untuk `payroll.bpjsenrollment`~~
4. ~~Satukan salinan peta cakupan pegawai~~ — ternyata sudah disatukan
   lebih dulu jadi `EMPLOYEE_SCOPE` / `EMPLOYEE_CHILD_SCOPE`

**Stage 1 — sisa yang belum dikerjakan**
5. Tambahkan `workflow_document` pada 6 viewset dokumen berworkflow
   yang belum punya, plus `register_route` untuk `attendance_permission`
6. Tambahkan `data_scope` pada viewset + lookup yang terbukti bisa
   dicakup — satu per satu dengan alasannya, **bukan** disapu rata

**Stage 2 — sesudah sisa Stage 1 hijau**
7. `EXPLICIT`-nol → tidak memberi apa-apa, di belakang flag settings,
   dengan test karakterisasi dibalik pada commit yang sama

**Stage 3 — keputusan arsitektur tersendiri**
8. Cakupan yang sadar-role, bukan per-orang. Sudah ada contoh
   konkretnya (`demo.gmsite`) — lihat bagian Stage 1
9. Penjagaan izin untuk lapisan lookup (`BaseLookupView`)

Tidak ada migration untuk Stage 1–2.

### Security — temuan terbuka (dari audit 8 Sep 2026)

Sengaja **tidak** diperbaiki di Phase 1: mencampur perbaikan cakupan
keamanan dengan UAT Attendance Permission membuat keduanya sulit
dibuktikan terpisah.

- ~~**`FINANCE-MANAGER` tanpa batasan karena kelalaian**~~ — **DITUTUP
  8 Sep 2026** (Stage 1). Sekarang `own`/Company; `demo.homanager`
  turun dari 48/48 pegawai jadi 46/48
- ~~**`SECURITY-GATE` sama**~~ — **DITUTUP 8 Sep 2026** (Stage 1).
  Sekarang `own`/Location, izinnya berhenti di `hr.employee`
- **BARU: `payroll.bpjsenrollment` tanpa `data_scope`** — baris per
  pegawai berisi nomor kepesertaan BPJS, terbaca seluruh tenant oleh
  siapa pun yang bisa login. **DITUTUP 8 Sep 2026** (Stage 1)
- ~~**Baca tidak dijaga izin sama sekali**~~ — **DITUTUP SEBAGIAN**
  8 Sep 2026: 10 resource sensitif sekarang menuntut `view_*` **dan**
  cakupan. Sisanya sengaja tetap terbuka (dropdown lintas modul)
- **"EXPLICIT + nol baris = tanpa batasan"** berlaku di dua mesin
  sekaligus (data `scoping.py`, menu `access.py`). Konsekuensinya
  urutan seed menentukan keamanan: `seed_workflows` membuat role
  telanjang, dan sebelum `seed_data_scopes` dijalankan role itu
  se-tenant
- **Cakupan belum menyeluruh** — 50 dari 115 kelas lookup dan 36 dari
  77 master viewset yang menyatakan `data_scope`; bawaannya `None` =
  tidak disaring. Dropdown adalah jalur bocor yang paling mudah
  terlewat
- **`ADMIN-DEPARTMENT` bermode `own`/`location`, bukan `/department`**
  — namanya menjanjikan satu departemen, cakupannya satu lokasi.
  Izin model dan menunya **identik** dengan `ADMIN-SECTION` (20 rute,
  nol selisih); yang membedakan keduanya hari ini cuma meja mana yang
  mereka pegang di alur
- **Penempatan bisa memberi akses baca yang ditolak Data Permission** —
  `_widen_for_workflow_participants()` melebarkan queryset untuk
  peserta alur, dan keanggotaan itu ditentukan penempatan, bukan
  cakupan. (Tidak berlaku untuk Attendance Permission: viewset-nya
  tidak menyatakan `workflow_document`.)

### Framework / Security

- **`Employee.is_active` masih bisa dimatikan tanpa `termination_date`**
  — Manpower Movement kebal, Manpower Summary membacanya, jadi dua layar
  bisa berbeda tanpa penjelasan. Menguncinya keputusan tersendiri
- **UserDataPermission belum punya UI**
- Branch/Department/Section masih bisa punya label ambigu
- **Metrik Leave di HR Period Summary terikat jadwal kerja** — group
  `attendance=False` + `leave=True` masuk laporan tapi kolom cutinya
  nol. Melepasnya merombak invariant
  `Scheduled = Present + Absent + Leave`; jangan dikerjakan diam-diam
- **Employee Group redesign** — pernah disebut sebagai kemungkinan,
  belum pernah dispesifikasikan. Bukan task aktif

---

## Recently Completed

Enam terakhir saja, untuk handoff. Selebihnya sudah tinggal di dokumen
domain dan tidak perlu diulang di sini.

- **Calendar Scope & Import** — DONE (backend + frontend), 5 Sep 2026.
  `WorkCalendar`/`Holiday` bercakupan GLOBAL/COMPANY/LOCATION
  (+ SELECTED_COMPANIES untuk Holiday), resolusi terpusat di
  `CalendarResolver`, import lewat framework import existing, fondasi
  sync eksternal berpagar review. **59 test baru OK**; regresi hijau:
  488 (Leave + Roster + Reports) dan 59 (Payroll proration & potongan
  absen). UAT browser 33/33; collapse sudah diterapkan di tenant demo.
  Detail: `docs/claude/calendar.md`.
- **HOTFIX rekap payroll run** — DONE (backend), 5 Sep 2026.
  `/payroll-runs/<id>/summary/` menjumlahkan agregatnya sendiri tanpa
  lewat `filter_queryset()`, jadi akun tanpa akses gaji tetap membaca
  total se-run. Sekarang seluruh angkanya lewat
  `payable_run_employees()` di `apps/payroll/scoping.py`.
  Detail: `docs/claude/payroll.md`.
- **Payroll Dashboard** — VERIFIED (backend + frontend), 5 Sep 2026.
  Rutenya `/payroll/dashboard` (menu Payroll → Dashboard; `/payroll`
  mengoper ke sana). `lines()` sekarang memakai
  `scope_run_employees()` bersama, bukan salinan petanya sendiri. UAT
  browser 44/44 (`scripts/uat/payroll-dashboard.mjs` di repo Nuxt,
  akunnya dari `payroll_dashboard_uat`) —
  menemukan dan menutup baris daftar yang terender `<nuxtlink>` alih-
  alih `<a href>`, jadi seluruh temuan "Perlu Ditindaklanjuti" tidak
  bisa diklik. 30 test dashboard OK.
  Detail: `docs/claude/payroll.md`.
- **Payroll Dashboard** — DONE (backend + frontend), 4 Sep 2026. Layar
  operasional yang membaca hasil run, tidak menghitung ulang; filternya
  dokumen (period/run), bukan rentang tanggal.
  Detail: `docs/claude/payroll.md`.
- **HOTFIX Employee Action Salary Change** — DONE (backend), 4 Sep 2026.
  `payroll_policy` + `daily_rate` kini ikut tersalin ke assignment baru,
  dan baris lama ditutup **sebelum** yang baru terbit (invariant satu
  baris `is_current` per pegawai). Detail: `docs/claude/payroll.md`.
- **Payroll Policy** — DONE (backend + frontend), 4 Sep 2026. Kebijakan
  bisa ditentukan per `PayrollAssignment` dengan fallback perusahaan;
  daily payroll didukung. Detail: `docs/claude/payroll.md`.
- **Business Decision #1–#4** — DONE (backend), 3 Sep 2026. Prorata gaji
  pokok, potongan absen & cuti tidak dibayar, aturan hitung tunjangan,
  lembur bertingkat. Detail: `docs/claude/payroll.md`.
---

## Documentation Rule

`CURRENT-WORK.md` hanya menyimpan:

- task aktif
- pending / next
- status ringkas pekerjaan terbaru
- pointer ke dokumen domain

Detail implementasi final harus berada di dokumen domain.

Jika task selesai:

1. update dokumen domain
2. verifikasi knowledge final sudah tersimpan di sana
3. ringkas task di `CURRENT-WORK`
4. hapus kronologi debugging dan superseded detail

**Yang tidak boleh tinggal di berkas ini:** kronologi debugging, cerita
bagaimana bug ditemukan, output command panjang, daftar test case
detail, UAT browser detail, daftar berkas implementasi, kronologi
migrasi/seed, correction-of-correction, superseded design, task DONE
lama, dan penjelasan arsitektur panjang yang sudah ada di dokumen
domain. Jangan mempertahankan informasi hanya karena pernah penting.
