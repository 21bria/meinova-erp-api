# Registry Modul

Daftar lengkap `framework_module` yang terdaftar di backend, beserta status halaman frontend-nya.

Ini **satu-satunya tempat** yang menjawab "apa yang sudah jadi?" secara menyeluruh. Angkanya diambil dari kode, bukan dari ingatan.

!!! note "Cara memperbarui halaman ini"
    ```bash
    # Backend — daftar module terdaftar
    grep -rh 'framework_module = "' apps --include='*.py' \
      | grep -v __pycache__ \
      | sed 's/.*framework_module = "//; s/"//' | sort -u

    # Frontend — daftar halaman yang ada
    find app/modules -name "page.vue" \
      | sed 's|app/modules/||; s|/page.vue||' | sort -u
    ```
    Selisihnya adalah modul yang perlu diregenerate — atau yang memang sengaja tidak punya halaman (lihat [Sengaja tanpa halaman](#sengaja-tanpa-halaman-sendiri)).

**Per hari verifikasi terakhir: 139 module backend, 121 halaman frontend.**

---

## Ringkasan per app

| App | Module BE | Halaman FE | Status |
|---|---:|---:|---|
| `administration` (organisasi, kalender, settings, audit) | 30 | 22 | ✅ |
| `accounts` (security) | 9 | 6 | ✅ |
| `hr` | 24 | 19 | ✅ |
| `references/*` (master referensi) | 62 | 60 | ✅ |
| `payroll` | 7 | 7 | 🟡 API sebagian |
| `workflow` | 4 | 4 | ✅ |
| `assets`, `finance`, `reports`, `scm` | 0 | 0 | 📋 Stub kosong |

---

## HR

Modul paling matang. Delapan item di sidebar, semuanya sudah ada backend-nya.

| Menu | `framework_module` | Model utama | FE |
|---|---|---|---|
| Dashboard | `hr/dashboard` | — (agregasi) | ✅ |
| Employees | `hr/employees` | `Employee` + sub-data | ✅ |
| Attendance | `hr/attendance` | `EmployeeAttendance` | ✅ |
| Leave | `hr/leave`, `hr/leave-balances` | `EmployeeLeave`, `LeaveBalance` | ✅ |
| Overtime | `hr/overtime` | `EmployeeOvertime` | ✅ |
| Travel Request | `hr/travel-requests` | `TravelRequest` | ✅ |
| Roster Schedule | `hr/site-rotations` | `SiteRotation`, `RotationPeriod` | ✅ |
| Roster Setup | `hr/roster-setups`, `hr/roster-setup-lines` | `RosterSetupRequest`, `RosterSetupLine` | ✅ |
| Roster Adjustment | `hr/roster-adjustments` | `RosterAdjustment` | ✅ |
| Rotation Credit | `hr/rotation-credits` | `RotationCreditTransaction`, `RotationCreditBalance` | ✅ |
| Employee Actions | `hr/employee-actions` | `EmployeeAction` | ✅ |
| Training | `hr/training`, `hr/training-participants` | `TrainingProgram`, `TrainingParticipant` | ✅ |
| Recruitment | `hr/recruitment`, `hr/candidates`, `hr/candidate-interviews` | `JobVacancy`, `Candidate`, `CandidateInterview` | ✅ |
| *(Masters)* Leave Policy | `hr/leave-policies` | `LeavePolicy` | ✅ |
| *(Masters)* Roster Policy | `hr/roster-policies` | `RosterPolicy` | ✅ |
| *(Masters)* Employee Action Policy | `hr/employee-action-policies` | `EmployeeActionPolicy` | ✅ |
| *(Masters)* Employee Data Policy | `hr/employee-data-policies` | `EmployeeDataPolicy` | ⚠️ belum digenerate |
| *(Masters)* Reminder Policy | `hr/reminder-policy` | | ✅ |

Alur bisnisnya: [Cuti](../09-business-flows/Leave-Request.md) · [Travel Request](../09-business-flows/Travel-Request.md) · [Roster](../09-business-flows/Roster-Management.md) · [Employee Action](../09-business-flows/Employee-Action.md)

---

## Administration

| Kelompok | Module | FE |
|---|---|---|
| **Organization** | `company`, `branch`, `location`, `division`, `department`, `section`, `position`, `cost-center`, `facility` | ✅ semua |
| **Calendar** | `fiscal-year`, `posting-period`, `holiday`, `work-calendar`, `roster-crew` | ✅ semua |
| **Currency** | `administration/currency` | ✅ |
| | `administration/currency/exchange-rate` | ⚠️ belum |
| **Numbering** | `numbering-sequence`, `document-series` | ⚠️ belum keduanya |
| **Notification** | `notification`, `notification-setting` | ⚠️ belum keduanya |
| **Settings** | `tenant-settings`, `print-settings`, `system-setting` | ✅ |
| | `tenant-setting`, `print-setting` (endpoint tunggal lama) | 🔒 jalur transisi, sengaja tanpa halaman |
| **Audit** | `administration/audit/audit-trail` | ✅ |
| **Dashboard modul** | `administration/dashboard` (paketnya `overview`) | ✅ |

!!! warning "Tenant & Print Setting: satu baris per company, bukan satu per tenant"
    Keduanya `OneToOneField(company)`, jadi tenant berisi dua belas perusahaan punya dua belas baris masing-masing. Layar `schema_type="setting"` lama hanya bisa menyunting **satu** record lewat `.first()` — perusahaan mana yang tersunting ditentukan urutan id, dan sebelas sisanya tidak punya jalan masuk sama sekali.

    Penggantinya CRUD biasa (`tenant-settings`, `print-settings`). Endpoint tunggal lamanya **tidak dihapus**, dibiarkan sebagai jalur transisi.

    `SystemSetting` memang satu baris per tenant (key/value global), jadi tetap satu form.

---

## Security (`apps/accounts`, tampil di bawah Administration)

| Module | FE | Catatan |
|---|---|---|
| `administration/security/users` | ✅ | komponennya **disunting tangan** di atas keluaran generator |
| `administration/security/roles` | ✅ | idem |
| `administration/security/permissions` | ✅ | idem |
| `administration/security/api-keys` | ✅ | |
| `administration/security/password-policy` | ✅ | |
| ~~`administration/security/data-permission`~~ | ❌ | **dihapus Stage 4I** — pohon read-only `RoleDataPermission`; cakupan yang berlaku ada di `user-role` |
| `administration/security/menu-permission` | 🔒 | tab ditulis tangan |
| `administration/security/role-permission` | 🔒 | tab ditulis tangan |
| `administration/security/user-role` | 🔒 | tab ditulis tangan |
| `administration/security/security-setting`, `session-setting` | ⚠️ | belum |

!!! danger "Ketiga tabel Security membawa kode yang tidak dihasilkan generator"
    Role gating, `notify`, dan label hapus yang menyebut nama barisnya. Meregenerate module-nya **menghapus ketiganya tanpa error** — tabelnya tetap jalan, cuma tombolnya muncul untuk peran yang seharusnya read-only. Ada komentar pengingat di kepala tiap berkas.

`endpoint` di schema ketiganya **wajib eksplisit**: module-nya `administration/security/…` tapi API-nya di bawah `/api/accounts/`.

---

## Workflow

Punya **menunya sendiri di sidebar**, bukan menumpang Administration. Kuncinya `moduleMenus.workflow` di `app/constants/menus.ts` — `AppSidebar.vue` memilih menu dari `route.path.split('/')[1]`, jadi nama kuncinya **wajib** persis `workflow` dan halamannya wajib ada di `app/pages/workflow/`.

| Module | Bentuk | FE |
|---|---|---|
| `workflow/definitions` | CRUD workspace + tabel step inline | ✅ digenerate |
| `workflow/steps` | CRUD | ✅ digenerate |
| `workflow/instances` | read-only | ✅ digenerate |
| `workflow/delegations` | CRUD | ✅ digenerate |
| `/workflow/inbox` | kotak masuk lintas modul | ✍️ ditulis tangan |
| `/workflow/submissions` | pengajuan sendiri | ✍️ ditulis tangan |
| `/workflow/instances/[id]` | detail + jejak persetujuan | ✍️ ditulis tangan |

`WorkflowInstanceViewSet` **harus tetap turunan `BaseMasterViewSet`** walau read-only (metode tulisnya dimatikan lewat `http_method_names`) — `framework_schema_view` hanya menemukan turunan base itu.

!!! note "Jejak persetujuan tidak bisa jadi tab custom"
    Generator `crud-workspace` meneruskan tab bertipe custom ke sebuah slot yang tidak diisi `page.vue`, jadi hasilnya kotak "belum tersambung" — lebih buruk daripada tidak ada. Karena itu tab `approvals` dicabut dari schema instance dan detailnya ditulis tangan (`WorkflowApprovalTrail.vue`, dipakai ulang ketiga halaman).

Item lama `/administration/workflow` sudah **dihapus** beserta halaman dan modulnya — endpoint-nya ikut hilang saat duplikat `administration.workflow` dibuang di BE.

---

## Payroll — 🟡 Partial

Model dan seed lengkap; API baru sebagian.

| Module | FE |
|---|---|
| `payroll/payroll-groups` | ✅ |
| `payroll/salary-grades`, `payroll/salary-levels` | ✅ |
| `payroll/allowance-templates`, `payroll/deduction-templates` | ✅ |
| `payroll/overtime-groups` | ✅ |
| `payroll/tax-statuses` | ✅ |

**Belum ada model payroll run**, jadi widget "Monthly Payroll" di dashboard sengaja tidak dibuat — bukan diisi angka contoh.

---

## Master referensi

62 module di bawah `references/`:

- `references/organization/*` — company-types, branch-types, location-types, facility-types
- `references/geography/*` — countries, provinces, cities
- `references/bank/*` — banks, bank-branches
- `references/hr/*` — 53 master (gender, religion, employment type, leave type, shift, skill, competency, KPI, dst.)

Sebagian besar referensi HR tinggal di satu **workspace bertab** (`/administration/master/hr`), bukan halaman terpisah. Kartu Master Hub menautkan langsung ke tabnya lewat `?group=&item=`.

!!! warning "Slug grup Master Hub bukan tebakan"
    `attendance-leave`, `skills-qualification`, `family-emergency`, `employee-separation`, `employee-training`. Nilai yang tidak dikenal **diabaikan dan jatuh ke tab pertama** — jadi tautan salah gagal tanpa suara. Periksa slug-nya terhadap `groups` di `Workspace.vue` setiap kali menambah kartu.

Belum jadi tab di workspace itu: `work-schedules` dan `transport-modes` (kartunya sementara menunjuk grup yang benar, bukan tab yang tepat).

---

## Sengaja tanpa halaman sendiri

Module ini punya endpoint dan schema, tapi **tidak** punya halaman FE — dan itu keputusan, bukan pekerjaan tertinggal.

| Module | Dipakai sebagai |
|---|---|
| `hr/rotation-periods` | tabel inline di dalam dokumen Roster Schedule |
| `hr/travel-request-purposes` | tabel inline di dalam Travel Request |
| `hr/travel-arrangements` | tabel inline di dalam Travel Request |
| `hr/roster-travel-days` | tabel inline di dalam Roster Policy |
| `administration/settings/tenant-setting`, `print-setting` | endpoint tunggal lama, jalur transisi |
| `administration/security/{menu,role,user}-*` | tab ditulis tangan |

!!! info "Konsekuensi tabel inline: semua kolom yang perlu diketik wajib `table=True`"
    Tidak ada dialog atau halaman kedua tempat mengisinya.

    Dan dua tabel yang membaca endpoint sama **wajib membawa salinan config field sendiri** — grid memilih kolom dari flag `table`, jadi mengubah flag di tempat akan ikut mengubah tabel yang satunya. Pola ini dipakai `Travel Arrangement` vs `Accommodation` yang keduanya `RotationTravel`.

---

## Perlu diregenerate / dibuat

Prioritas dari yang paling terasa:

| Module | Kondisi |
|---|---|
| `hr/employee-data-policies` | schema + endpoint jalan, halamannya belum digenerate |
| `administration/numbering/*` | deret nomor hanya bisa diubah lewat shell |
| `administration/notification/*` | `Notification` belum pernah diisi siapa pun — modelnya ada, penulisnya belum |
| `administration/currency/exchange-rate` | |
| `administration/security/{security,session}-setting` | |
| `references/hr/{employee-groups, document-types, transport-modes, accommodation-types, work-schedule-days}` | |
| `hr/site-rotations` | perlu **regenerate** — `schema.actions` sudah ditulis tapi module-nya belum diregenerate sejak generator mendukungnya |
| `hr/leave` | idem, tombol Submit/Approve belum muncul |

Halaman FE tanpa padanan module BE (kemungkinan **stale**, perlu diperiksa):
`administration/security/sessions`, `references/hr/employment-groups`, `references/hr/grades`, `references/hr/work-location-types`.

---

## Modul yang belum ada kodenya — 📋 Blueprint

Terdaftar di `INSTALLED_APPS` tapi isinya kosong: `assets`, `finance`, `reports`, `scm`.

Folder dokumentasi berikut **seluruhnya blueprint produk**, bukan rujukan implementasi:
`crm`, `fleet`, `fuel`, `inventory`, `laboratory`, `maintenance`, `mining`, `project`, `safety`, `analytics`, `asset`.

!!! note "Katalog aplikasi di beranda ikut menyaringnya"
    `APP_CATALOG` (`apps/administration/api/dashboard/catalog.py`) hanya memuat modul yang **punya halaman di Nuxt**. `finance` dan `scm` bertanda `COMING_SOON`; `assets` dan `reports` tidak terdaftar sama sekali karena belum punya rute — kartu yang mendarat di 404 lebih buruk daripada kartu yang tidak ada.

    Nambah modul = tambah satu baris di `APP_CATALOG`.
