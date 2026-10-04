# Proposal — Site Employee Roster Management

Status: **usulan, belum dikerjakan**. Dokumen ini hasil audit codebase per
2026-08-12 plus rancangan yang diminta. Tidak ada satu baris source code pun
yang diubah sampai proposal ini disetujui.

Cakupan: Roster Policy → Employee Roster Setup → Generator → Preview →
Approval → Baseline → Adjustment → Rotation Credit → Travel Day Rules.

Di luar cakupan dan **dianggap final**: struktur organisasi (Company/Branch/
Location/Facility/Department/Section), Employee, Role/Permission/Authorization,
data scope, flow leave HO, attendance, payroll.

---

## 0. Ringkasan audit — apa yang sudah ada

Modul roster **bukan lahan kosong**. Yang sudah berjalan di produksi:

| Yang sudah ada | Berkas | Perannya sekarang |
|---|---|---|
| `RosterPolicy` + `RosterTravelDay` | `apps/administration/models/references/roster_policy.py` | Aturan **per site**: hari perjalanan per Point of Hire, rasio konversi kerja:off, tenggat pengajuan. **Belum memuat pola siklus.** |
| `RosterCrew` | `apps/administration/models/calendar.py` | Gelombang/kru: `work_schedule` (pola) + `cycle_start_date` (jangkar, **per crew**) |
| `WorkSchedule` (`schedule_type=ROSTER`) | `references/hr_attendance.py` | Pemegang pola `cycle_work_days` / `cycle_off_days` |
| `EmploymentAssignment` | `apps/hr/models/employment.py` | Assignment pegawai — sudah punya `roster_crew`, `roster_start_override`, `travel_days_override`, `point_of_hire`, `working_calendar` |
| `SiteRotation` | `apps/hr/models/rotation.py` | Header jadwal roster per pegawai: pola disalin, `start_date`, `cycle_count`, `end_date`, `status` |
| `RotationPeriod` | idem | Baris segmen WORK/OFF, `sequence`, `total_days`, `is_manual_override`, `purpose`, `employee_leave` |
| `RotationPeriodGenerator` | `apps/hr/api/site_rotation/generator.py` | **Fungsi murni** tanpa DB: `build()`, `summarize()`, `cycles_until()`, `next_cycle_start()` |
| `RosterPolicyResolver` | `apps/hr/api/site_rotation/policy.py` | Pencocokan policy berjenjang (`specificity`), `travel_days_for()`, `ratio_for()` |
| `SiteRotationService` | `apps/hr/api/site_rotation/services.py` | `generate_periods`, `extend_periods`, `regenerate_from`, `shift_from`, `extend_period`, `adjust_by_ratio`, `build_schedule_warnings` |
| `TravelRequest` + `TravelArrangement` | `apps/hr/models/travel_request.py` | Dokumen pengajuan kepulangan + **tanggal penerbangan aktual** per etape |
| Engine workflow | `apps/workflow/` | `WorkflowDefinition/Step/Instance/Approval`, registry `on_complete` + `register_route` |
| Penomoran | `NumberingSequence`/`DocumentSeries` | Deret `hr/site_rotation` (prefix `RST`) sudah diseed |
| Audit | `administration.AuditTrail` | `action/module/object_type/object_id/before/after/user/ip` — modelnya ada, **belum dipakai service mana pun** |

### Yang tidak ada, dan itulah pekerjaannya

1. **Roster Policy tidak membawa pola siklus.** Pola ada di `WorkSchedule` →
   `RosterCrew`. Akibatnya "4:2 / 5:2 / 6:2 / 8:2 configurable" hari ini
   berarti bikin `WorkSchedule` baru + `RosterCrew` baru, dua master untuk
   satu konsep.
2. **Current Cycle Start milik crew, bukan pegawai.** Per-pegawai baru ada
   sebagai *override* (`roster_start_override`), dan itu terbalik dari yang
   diminta.
3. **Tidak ada `roster_start_basis`.** Jangkar selalu diartikan sebagai hari
   pertama blok kerja.
4. **Tidak ada mode Preview.** `after_create` langsung menulis baris periode ke
   DB (`SiteRotationService.after_create` → `generate_periods`).
5. **Tidak ada approval.** `SiteRotationStatus` sudah mendefinisikan
   DRAFT/SUBMITTED/APPROVED/REJECTED, tapi **tidak ada yang memakainya** —
   tidak ada `WorkflowDefinition` untuk `site_rotation`, tidak ada
   `register_completion`, tidak ada endpoint submit.
6. **Tidak ada baseline.** Baris periode disunting di tempat
   (`is_manual_override`), jadi "jadwal yang disetujui" tidak bisa dibedakan
   dari "jadwal setelah lima kali digeser".
7. **Tidak ada dokumen Adjustment.** `adjust_by_ratio()` menghitung dan
   langsung memutasi jadwal — tanpa dokumen, tanpa approval, tanpa jejak
   alasan.
8. **Tidak ada Rotation Credit sama sekali.** Rasio konversi ada, tapi
   hasilnya langsung jadi perpanjangan blok, bukan saldo.
9. **Tidak ada rolling horizon.** `cycle_count` manual, dipagari
   `MAX_CYCLE_COUNT = 24`; tidak ada yang memperpanjang otomatis.
10. **Tidak ada bulk setup.** Satu dokumen dibuat satu-satu.
11. **Belum ada test sama sekali** (`tests.py` kosong di seluruh repo).

### Dua catatan yang membentuk desain di bawah

- **Segmen travel pernah dihapus, dan alasannya masih berlaku sebagian.**
  `RotationTravel` dulu menempel ke blok jadwal lalu dibuang karena menyimpan
  **tanggal penerbangan dan tiket** di dua tempat. Yang saya usulkan di bawah
  bukan itu: segmen `TRAVEL_OUT`/`TRAVEL_IN` adalah **pita kalender rencana**
  tanpa nomor tiket, moda, maupun akomodasi. Aturan kerasnya: segmen roster
  tidak pernah menyimpan kolom booking — itu tetap milik `TravelArrangement`.
- **`RosterPolicy` punya constraint `uniq_active_rosterpolicy_target`
  `(company, location)`** — satu policy per site. Kalau policy jadi pembawa
  pola (6:2 dan 8:2 hidup berdampingan di Gebe), constraint itu **harus
  dicabut**. Lihat pertanyaan terbuka #1.

---

## 0b. Keputusan terkunci — 12 Agustus 2026

Tiga pertanyaan terbuka sudah dijawab. Detail lengkapnya di bawah; §3, §5, §12,
dan §15 dibaca dengan ketiga keputusan ini berlaku.

---

### Keputusan 1 — `RosterPolicy` jadi pembawa pola siklus

**Disetujui.** Policy memuat pola (`cycle_work_days`/`cycle_off_days`),
`roster_start_basis`, aturan travel, dan aturan credit. Pegawai menunjuknya
lewat `EmploymentAssignment.roster_policy`. Tidak ada formula yang membaca
nama atau kode policy.

#### 1a. Constraint yang dicabut, dan penggantinya

`uniq_active_rosterpolicy_target (company, location)` **dicabut** — Gebe harus
bisa punya `GBE-6-2` dan `GBE-8-2` berdampingan.

Tapi constraint itu dulu menjaga sesuatu yang nyata: kalau dua aturan
sama-sama cocok, hari perjalanan seseorang jadi bergantung pada nomor id di
database. Yang mencabutnya harus menggantikan penjagaan itu, bukan
menghilangkannya. Penggantinya kolom baru `is_default`:

```python
models.UniqueConstraint(
    fields=["company", "location"],
    condition=Q(is_deleted=False) & Q(is_default=True),
    name="uniq_active_rosterpolicy_default",
)
```

Satu site boleh punya banyak policy, tapi **hanya satu yang jadi bawaan**.
Migrasi mengisi `is_default=True` untuk seluruh baris yang ada sekarang —
karena constraint lama menjamin cuma ada satu per site, tidak ada ambiguitas
yang lahir saat upgrade.

#### 1b. Dua peran policy, dan cuma satu yang boleh menghasilkan jadwal

| Peran | Cara ditemukan | Dipakai untuk |
|---|---|---|
| **Pola roster pegawai** | `EmploymentAssignment.roster_policy`, **eksplisit** | Generate rencana. Tidak ada fallback |
| **Aturan site** | `is_default=True` + specificity (perilaku `RosterPolicyResolver` sekarang) | Travel days & tenggat pengajuan untuk pegawai yang belum punya policy; nilai awal di form |

`RosterPolicyResolver` diperluas jadi:

```python
RosterPolicyResolver.policy_for(employee) -> ResolvedPolicy(policy, source)
#   source="assignment"  → boleh dipakai generator
#   source="site_default"→ HANYA untuk travel days / prefill form
#   source=None          → pegawai HO, generator tidak menyentuhnya
```

Pemisahan ini yang membuat aturan M ("Employee HO tanpa Roster Policy tidak
diproses Roster Generator sama sekali") ditegakkan strukturnya, bukan lewat
`if` di banyak tempat: generator cuma menerima `source="assignment"`.

#### 1c. Pola tetap nullable, dan itu disengaja

`cycle_work_days`/`cycle_off_days` pada policy **nullable**. Baris
`RosterPolicy` yang sudah diseed hari ini (mis. `GBE-STD`) tidak memuat pola,
dan migrasi **tidak akan mengarangnya** — mengisi 42/14 untuk site yang belum
tentu memakainya persis kesalahan yang sudah tercatat di CLAUDE.md soal
`SICK-STD` 30 hari: angka karangan di master lebih berbahaya daripada tidak ada
angka, karena orang menganggapnya sudah divalidasi.

Yang menjaga: `EmploymentAssignment.clean()` menolak policy tanpa pola.

> Roster Policy GBE-STD belum mengisi pola siklus (Work/Off Days), jadi tidak
> bisa dipakai sebagai roster pegawai. Isi polanya di master, atau pilih
> policy lain.

Jadi policy tanpa pola tetap sah dan tetap berfungsi sebagai aturan site — ia
cuma tidak bisa ditugaskan ke pegawai.

#### 1d. Tiga sumber pola tidak boleh bertengkar

Sekarang ada `roster_policy` (baru), `roster_crew.work_schedule` (lama), dan
`work_schedule` (lama) yang sama-sama menyimpan pola. Urutan kuasanya dibalik
dari yang berlaku sekarang:

**Roster Policy yang menentukan; Roster Crew dan Work Schedule mengikutinya.**

`EmploymentAssignment.clean()` menolak kalau `roster_policy` dan `roster_crew`
sama-sama terisi tapi polanya berbeda, dengan pesan yang menyebut kedua angka —
pola yang sama persis dengan pemeriksaan `work_schedule` vs
`roster_crew.work_schedule` yang sudah ada. Bukan dilonggarkan diam-diam:
pegawai yang policy-nya 8:2 sementara crew-nya 6:2 akan menghasilkan jadwal dan
perhitungan cuti yang berbeda, dan tidak ada satu layar pun yang
memperlihatkannya.

`RosterCrew` **tetap ada** sebagai pengelompokan gelombang, dan
`cycle_start_date`-nya turun jadi **saran** (`autofill` di form), bukan sumber.
Mencabutnya sekarang berarti menyentuh `LeaveDayCalculator.resolve_roster()`
yang sudah jalan.

#### 1e. Migrasi assignment: command, bukan data migration

Data migration **hanya** mengisi
`roster_cycle_start = roster_start_override or roster_crew.cycle_start_date`.
Pemetaan ke `roster_policy` lewat perintah tersendiri:

```
python manage.py tenant_command migrate_roster_assignments --schema=demo [--dry-run]
```

Aman diulang, melaporkan per pegawai policy mana yang dipilih dan kenapa, dan
**menolak menebak** kalau tidak ada policy dengan pola yang cocok — pegawainya
dilaporkan sebagai belum termigrasi, bukan dipaksakan ke policy terdekat.
Polanya sama dengan `migrate_attendance_import_profiles` yang sudah ada.

---

### Keputusan 2 — Segmen `TRAVEL_OUT` / `TRAVEL_IN` dimaterialisasi

**Disetujui.** Bentuk siklusnya persis seperti di konsep:

```
WORK → TRAVEL_OUT → FIELD_BREAK → TRAVEL_IN → WORK berikutnya
```

#### 2a. Kenapa ini bukan pengulangan `RotationTravel`

Yang dulu dihapus adalah **model tersendiri** berisi nomor tiket, moda
transportasi, akomodasi, dan tanggal penerbangan — duplikat dari
`TravelArrangement`. Yang sekarang bukan model: ia **nilai baru pada
`RotationPeriod.segment_type`**.

Itu bukan soal penamaan. Karena tidak ada tabel travel, **tidak ada tempat
untuk menaruh data booking** — pencegahannya struktural, bukan disiplin. Kalau
suatu saat ada yang perlu menyimpan nomor tiket, ia harus menambah kolom ke
`RotationPeriod`, dan itu langkah yang kelihatan.

Ditambah satu pagar yang berbunyi sendiri: **guard test** yang menegaskan
field set `RotationPeriod` tidak pernah memuat kolom booking.

```python
FORBIDDEN = {
    "ticket_number", "transport_mode", "transport_detail",
    "accommodation_type", "accommodation_name",
    "accommodation_checkin", "accommodation_checkout",
    "accommodation_nights", "origin", "destination",
}
# gagal dengan pesan yang menyebut kenapa, plus rujukan ke keputusan ini
```

Aturannya satu kalimat: **segmen roster adalah pita kalender rencana; tanggal
penerbangan yang diajukan dan disetujui tetap milik `TravelArrangement` di
dalam Travel Request.**

#### 2b. Arah, dan kenapa out/in tidak boleh tertukar

| Segmen | Arah nyata | Menempel di ujung |
|---|---|---|
| `TRAVEL_OUT` | site → Point of Hire (pulang) | blok `WORK` |
| `TRAVEL_IN` | Point of Hire → site (berangkat) | blok `FIELD_BREAK` |

Sama dengan semantik `TravelDirection` yang sudah dipakai `TravelArrangement`
dan `RotationTravel` dulu. Dibalik, "hari perjalanan ke site dihitung hari
kerja" akan menempel ke perjalanan pulang.

#### 2c. Hari out/in jadi angka tersendiri

`default_travel_days` (total PP, ganjil condong ke sisi keluar) diganti
`default_travel_out_days` + `default_travel_in_days`; `RosterTravelDay` ikut.
Migrasi `out = ceil(total/2)`, `in = floor(total/2)` — identik dengan
`RotationPeriod.travel_days` hari ini, jadi **tidak ada jadwal existing yang
bergeser satu hari pun**.

Setelah ini pemecahan ganjil tidak lagi jadi rumus tersembunyi di generator; ia
jadi dua angka yang bisa dilihat dan diubah di layar.

#### 2d. `counts_as_roster_day` — dua flag, bukan satu

| Flag policy | Bawaan | Seed klien tambang |
|---|---|---|
| `travel_out_counts_as_roster_day` | `False` | `False` — aturan #1: site → POH bukan On Site |
| `travel_in_counts_as_roster_day` | `False` | `True` — aturan #4: Sorong/Ternate → site sudah dihitung On Site |

Bawaan keduanya `False` supaya rilis fitur ini **tidak mengubah jadwal yang
sedang berjalan**; nilai klien diisi lewat seed, bukan lewat bawaan kode.

Artinya harus dikunci sekarang supaya tidak salah dipakai nanti:

> `counts_as_roster_day` menentukan apakah hari itu **dihitung sebagai hari
> on-site di rekap**. Ia **tidak** memotong panjang blok `WORK`.

Pegawai 45/14 yang dua hari di kapal tetap menjalani 45 hari di site. Memotong
travel dari Work Days membuat angka di kontrak tidak cocok dengan angka mana
pun di sistem — dan itu keputusan lama yang tetap berlaku. `cycle_length` tetap
`work + off + travel_out + travel_in`.

#### 2e. Pegawai lokal (test case L)

`travel_out_days = travel_in_days = 0` atau `travel_creates_segment=False` →
segmennya tidak dibuat, siklusnya jadi `WORK → FIELD_BREAK → WORK`. Tanpa
cabang khusus di generator: nol hari menghasilkan nol baris, sama seperti
generator sekarang yang tidak menyisakan celah kalender saat `travel_days=0`.

#### 2f. Dampak yang harus disadari: perhitungan hari cuti pegawai site berubah

Ini konsekuensi paling tidak kelihatan dari keputusan ini, dan saya lebih baik
menuliskannya di depan.

`LeaveDayCalculator.resolve_rotation_work_days()` mengembalikan `None` kalau
baris `RotationPeriod` **tidak menutupi seluruh rentang cuti**. Hari travel
hari ini adalah **celah kalender tanpa baris**, jadi setiap cuti yang
menyeberangi jendela travel jatuh ke cabang rumus modulo
(`resolve_roster()`).

Begitu segmen travel dimaterialisasi, rentangnya tertutup penuh dan cabang
baris-nyata yang dipakai. **Angka hari cuti untuk kasus itu akan berubah.**

Dan perubahannya kemungkinan besar ke arah yang benar: `resolve_roster()`
menghitung siklus sebagai `work + off` **tanpa travel**, sementara jadwal
sebenarnya maju `work + off + travel` setiap putaran — jadi rumus modulonya
hanyut sebanyak hari travel per siklus. Untuk crew `CREW-6W` (42/14/2) itu 2
hari per putaran, menumpuk sepanjang tahun.

Saya belum menjalankannya, jadi ini **temuan dari membaca kode, belum
terverifikasi**. Fase 0 mengunci perilaku sekarang dengan test regresi lebih
dulu, baru fase 2 mengubahnya — sehingga selisihnya terlihat sebagai test yang
sengaja diperbarui, bukan sebagai angka yang diam-diam berbeda.

---

### Keputusan 3 — Approval bulk: satu dokumen untuk seluruh batch

**Disetujui: satu `RosterSetupRequest` = satu `WorkflowInstance` = satu item di
kotak masuk.** Tiga puluh pegawai tidak boleh jadi tiga puluh tombol Approve
yang isinya sama.

#### 3a. Kendala engine yang menentukan bentuknya

`WorkflowService.submit()` menerima `scope`, tapi `scope` **hanya** mengatur
pencocokan `WorkflowDefinition` dan mengisi kolom company/branch/location pada
instance. Penyusunan approver (`_build_approvals`) tetap berangkat dari
`employee` — `manager`, `department_head`, dan `position` semuanya membaca
`OrganizationAssignment` milik pegawai itu.

Dokumen batch tidak punya satu pegawai subjek. Konsekuensinya dua aturan:

**(1) Satu batch = satu Site, dan opsional satu Section.** Blocking validation,
bukan saran. Batch bercampur site membuat cakupan approver tidak bisa
ditentukan — dan kebocorannya diam, persis kasus "pengajuan Gebe mendarat di
kotak masuk orang Halmahera" yang sudah pernah terjadi.

**(2) Alur batch hanya boleh memakai step bertipe `role` atau `user`.**

!!! warning "Sudah dicabut — 1 Sep 2026"
    Aturan ini **tidak lagi berlaku**. Ia memang pernah diterapkan persis
    seperti tertulis di bawah, dan ternyata terlalu keras: yang dibuangnya
    justru meja yang paling diminta pengguna, yaitu persetujuan **atasan
    langsung** pegawai yang dijadwalkan.

    Penggantinya: step per-pegawai boleh dipakai **kalau seluruh baris dokumen
    menghasilkan approver yang sama** — satu dokumen, satu atasan. Diperiksa
    `RosterSetupService.batch_approver_findings()` dan dilaporkan di preview
    sebagai `mixed_approver`. Uraian yang berlaku ada di
    [Roster Management (business flow)](../../09-business-flows/Roster-Management.md)
    dan `docs/claude/hr/roster.md`.

`RosterSetupService.assert_batch_definition_supported()` dulu memeriksanya saat
submit dan menolak dengan pesan yang menyebut step mana yang bermasalah:

> Step #2 "Atasan Langsung" bertipe Manager. Dokumen setup roster memuat banyak
> pegawai, jadi tidak ada satu atasan langsung yang bisa ditunjuk. Pakai step
> bertipe Role Holder dengan Approver Scope Location/Section.

Alasannya waktu itu: meja yang masuk akal untuk setup roster dianggap memang
Admin HR Site, HR Manager Site, dan KTT — semuanya role, semuanya sudah ada di
alur `HR-TR-SITE`.

**(3) Organisasi sampel untuk cakupan role** diambil dari baris dengan
`employee_number` terkecil, dan itu **sah karena aturan (1)**: seluruh baris ada
di site yang sama, jadi sampel mana pun memberi location/section yang sama.
Dipilih deterministik supaya dua submit yang sama menghasilkan approver yang
sama. Alasannya ditulis di kode, karena "kenapa pakai pegawai pertama" adalah
pertanyaan yang pasti muncul saat orang membacanya.

`subject_employee` pada instance dibiarkan **kosong**. Dokumen setup adalah
dokumen perencanaan HR, bukan dokumen milik pegawai; masing-masing pegawai
melihat rencananya sendiri lewat layar Roster Plan yang sudah disaring
`RoleDataPermission`.

`document_label` diisi supaya kotak masuk terbaca tanpa membuka dokumennya:
`"Roster Setup — Gebe / OPS_SITE — 30 pegawai — mulai 2026-09-01"`.

#### 3b. Kalau approver cuma keberatan pada 3 dari 30 baris

Tidak perlu approval per baris. Engine sudah punya jawabannya:
**`RETURNED`** — dikembalikan ke pengaju untuk diperbaiki tanpa ditolak. Pengaju
membetulkan tiga baris itu (atau membuangnya), lalu mengajukan ulang; pengajuan
lama ditutup `CANCELLED` dan yang baru berdiri sendiri, sehingga jejak siapa
yang mengembalikan dan alasannya tetap terbaca.

Approve/Reject per baris sengaja **tidak** dibuat. Itu berarti satu dokumen
punya banyak keputusan parsial, dan "dokumen ini disetujui" tidak lagi punya
arti tunggal — persis masalah yang membuat approval per-pegawai ditolak sejak
awal.

#### 3c. Commit: per baris, dan kegagalannya tidak membatalkan persetujuan

Mengikuti pola `EmployeeActionService` yang sudah terbukti: alur yang sudah
selesai dan keputusan approver yang sah tidak boleh dibatalkan gara-gara satu
baris gagal ditulis.

```
approve → on_workflow_done
            untuk tiap RosterSetupLine (savepoint per baris):
                commit plan + v1 + baseline + opening credit
                line.status = COMMITTED
            baris yang gagal → line.status = FAILED, line.commit_error diisi
          dokumen → COMMITTED, atau PARTIALLY_COMMITTED kalau ada yang gagal
POST .../commit/  → mengulang HANYA baris FAILED
```

Validasi yang sungguhan dijalankan saat **Submit** (`assert_submittable`),
bukan saat commit — supaya kegagalan muncul di layar orang yang bisa
memperbaikinya. Pola yang sama dengan
`TravelRequestService.assert_no_leave_conflict`.

`RosterSetupLine`: `status` (PENDING/COMMITTED/FAILED/SKIPPED),
`commit_error`, `plan` FK (diisi setelah commit).

#### 3d. Pemeriksaan overlap dijalankan dua kali

Sekali saat preview, sekali lagi saat commit. Di antara keduanya bisa ada
dokumen lain yang disetujui duluan, dan `RosterSetupService.assert_no_active_plan()`
menolak dengan pesan yang **menyebut nomor dokumen** yang menabraknya — bukan
"pegawai ini sudah punya roster aktif", yang tidak bisa ditindaklanjuti.
Baris yang tertabrak jadi `FAILED`; dua puluh sembilan sisanya tetap terbit.

#### 3e. Pagar

`MAX_SETUP_LINES = 200` per dokumen. Tiga puluh baris × ~26 segmen setahun ≈
780 baris dalam satu transaksi — aman; dua ratus baris ≈ 5.200 dan itu batas
yang masih wajar untuk satu commit. Di atas itu, batch dipecah per Section, dan
itu memang pembagian kerja yang benar.

---

## 1. Existing model yang direuse

**Dipakai apa adanya, tidak disentuh:**

- `Employee`, `OrganizationAssignment`, seluruh master organisasi
- `RotationPurpose` (`deducts_leave`) — pembeda Field Break vs cuti
- `EmployeeLeave` / `LeaveBalance` / `EmployeeLeaveService` / `LeaveDayCalculator`
  — roster **membaca**, tidak menulis logika cuti
- `TravelRequest` / `TravelRequestPurpose` / `TravelArrangement`
- Engine workflow + registry + `WorkflowApprovalViewSet` (inbox)
- `NumberingSequence` / `DocumentSeries` / `DocumentNumberService`
- `AuditTrail`
- `BaseMasterService` / `BaseMasterViewSet` / `ServiceWriteMixin` /
  builders schema / lookup registry / `DataScopeService`
- Framework import generik (`@register_importer`) — dipakai untuk migrasi
  data go-live

**Assignment yang dipakai: `EmploymentAssignment`.** Tidak ada assignment baru.
Yang ditambahkan cuma referensi:

| Field baru di `EmploymentAssignment` | Tipe | Alasan |
|---|---|---|
| `roster_policy` | FK `RosterPolicy`, null | Referensi yang diminta. Kosong = pegawai HO, **tidak diproses generator sama sekali** |
| `roster_cycle_start` | Date, null | **Current Cycle Start per pegawai.** Wajib begitu `roster_policy` terisi |
| `roster_start_basis` | Char, null | Override basis milik policy, untuk kasus per orang. Kosong = ikut policy |
| `back_to_back_partner` | FK `Employee`, null, `SET_NULL` | Referensi opsional, **tidak pernah memblokir** |

`roster_start_override` yang lama tetap ada sebagai kolom deprecated dan
dipetakan ke `roster_cycle_start` saat migrasi (lihat §15). `roster_crew`
**tetap ada** — `LeaveDayCalculator.resolve_roster()` masih membacanya, dan
mencabutnya berarti menyentuh perhitungan hari cuti yang sudah jalan.

**Direuse dengan penambahan kolom (bukan model baru):**

- `RosterPolicy` — jadi pembawa pola + aturan travel + aturan credit (§3)
- `RosterTravelDay` — pecah `travel_days` jadi out/in
- `SiteRotation` — jadi header **Roster Plan** (nama tabel/model tetap, label
  UI diganti; rename model akan menyeret FK `TravelRequest.rotation_period`,
  `LeaveDayCalculator`, schema, dan modul FE tanpa manfaat setara)
- `RotationPeriod` — jadi **Roster Segment**

---

## 2. Model baru + field baru

### 2.1 Model baru (5)

| Model | Tabel | Isi ringkas |
|---|---|---|
| `RosterPlanVersion` | `hr_roster_plan_version` | Satu baris per versi rencana. `plan`, `version_no`, `status`, `source` (INITIAL/ADJUSTMENT/POLICY_CHANGE/HORIZON_EXTENSION), `effective_from`, `reason`, `reference_type/reference_id`, `approved_at/by`, `committed_at` |
| `RosterSetupRequest` + `RosterSetupLine` | `hr_roster_setup_request`, `hr_roster_setup_line` | Dokumen **bulk setup**. Header: site/section, as-of date, status, dokumen number. Line: employee, roster_policy, current_cycle_start, opening_rotation_credit, note, hasil validasi |
| `RosterAdjustment` | `hr_roster_adjustment` | Dokumen perubahan operasional: plan, kind, effective_date, days, reason, credit_impact, status, workflow |
| `RotationCreditTransaction` | `hr_rotation_credit_transaction` | **Ledger**, append-only |
| `RotationCreditBalance` | `hr_rotation_credit_balance` | Cache saldo per pegawai, dihitung ulang dari ledger (pola `LeaveBalance.used`) |

`RosterSetupLine` dan `RosterAdjustment` dipisah karena approvernya berbeda dan
siklus hidupnya berbeda: setup terjadi sekali per era, adjustment berkali-kali.

### 2.2 Kolom baru pada model existing

**`SiteRotation` (Roster Plan header):**

| Kolom | Alasan |
|---|---|
| `roster_policy` FK | Policy yang membentuk rencana ini, disalin saat commit |
| `cycle_start` Date | Current Cycle Start yang **dibekukan** ke dokumen |
| `roster_start_basis` Char | Dibekukan dari policy |
| `travel_out_days`, `travel_in_days` | Dibekukan. Menggantikan `cycle_travel_days` (total PP) |
| `travel_day_mode` | FIXED / ACTUAL_ITINERARY, dibekukan |
| `travel_out_counts_as_roster_day`, `travel_in_counts_as_roster_day` Bool | Dibekukan |
| `effective_from`, `effective_to` Date | Era rencana. `effective_to` null = era berjalan |
| `horizon_end` Date | Sampai kapan segmen sudah digenerate |
| `current_version` FK `RosterPlanVersion` | Versi yang berlaku |
| `baseline_version` FK `RosterPlanVersion` | Versi pertama yang disetujui — **tidak pernah berubah** |
| `submitted_at/by`, `approved_at/by`, `locked_at` | Jejak approval |
| `setup_line` FK, null | Asal-usul dari dokumen bulk setup |

`cycle_work_days`/`cycle_off_days` **tetap** (dibekukan dari policy, bukan lagi
dari crew). `cycle_travel_days` dipertahankan sebagai kolom hasil turunan
(`out + in`) supaya `cycle_length` dan report existing tidak pecah, lalu
dideprecate di fase berikutnya.

**`RotationPeriod` (Roster Segment):**

| Kolom | Alasan |
|---|---|
| `version_from` FK, `version_to` FK null | **Interval versi.** Segmen tidak pernah disunting; ia ditutup dan diganti |
| `segment_type` | Menggantikan `period_type`, nilai: `WORK`, `FIELD_BREAK`, `TRAVEL_OUT`, `TRAVEL_IN` |
| `counts_as_roster_day` Bool | Apakah hari ini mengisi kuota on-site |
| `is_locked` Bool | Segmen di masa lalu / sudah dibaseline |
| `planned_start/end` Date | Nilai baseline, untuk membandingkan dengan aktual |
| `source_adjustment` FK null | Adjustment yang melahirkan segmen ini |

`period_type` dipertahankan sebagai kolom lama yang diisi dari `segment_type`
(WORK → `work`, sisanya → `off`) sampai `LeaveDayCalculator` dan report ikut
diubah. Ini yang membuat perubahan bisa dirilis tanpa mematikan perhitungan
cuti (lihat §17).

---

## 3. Roster Policy schema

Satu master, tiga kelompok. Semua angka konfigurabel — **tidak ada satu pun
formula yang membaca nama atau kode policy**.

### 3.1 Identitas & cakupan (sudah ada)

`company` (null = semua), `location` (null = semua site di company), `code`,
`name`, `description`, `is_active`, plus **`is_default`** (baru).

Sesuai keputusan 1: `uniq_active_rosterpolicy_target (company, location)`
dicabut, diganti constraint yang sama tapi dikondisikan `is_default=True`.
`code` tetap unik per company. Pola **selalu** dari
`EmploymentAssignment.roster_policy` yang eksplisit; resolver by-specificity
turun peran jadi penyaji default di form dan sumber travel-day untuk pegawai
yang belum punya policy.

### 3.2 Pola siklus (baru)

| Field | Tipe | Catatan |
|---|---|---|
| `cycle_work_days` | int, **nullable** | 42 untuk 6:2. Kosong = policy ini cuma aturan site, tidak bisa ditugaskan ke pegawai (§0b.1c) |
| `cycle_off_days` | int, **nullable** | 14 |
| `roster_start_basis` | choice | `WORK_START_DATE` \| `SITE_ARRIVAL_DATE` \| `TRAVEL_DEPARTURE_DATE` |
| `rolling_horizon_months` | int, default 12 | Sejauh apa segmen digenerate ke depan |
| `min_segment_days` | int, default 1 | Pagar kewarasan |

**Arti `roster_start_basis`** — inilah yang dinormalisasi generator jadi satu
angka internal `work_block_start`:

| Basis | Normalisasi | Kapan dipakai |
|---|---|---|
| `WORK_START_DATE` | `work_start = cycle_start` | Yang diketik HR adalah hari pertama masuk kerja |
| `SITE_ARRIVAL_DATE` | `work_start = cycle_start` **dan** `TRAVEL_IN` diletakkan **sebelum** tanggal itu | Sesuai aturan #4 dokumen klien: perjalanan Sorong/Ternate → site sudah dihitung On Site |
| `TRAVEL_DEPARTURE_DATE` | `work_start = cycle_start + travel_in_days` | Yang diketik adalah tanggal berangkat dari POH |

Ketiganya menghasilkan tanggal blok kerja yang berbeda dari input yang sama —
itu sebabnya tidak boleh diasumsikan.

### 3.3 Travel Day (baru + migrasi dari kolom lama)

| Field | Tipe | Catatan |
|---|---|---|
| `travel_day_mode` | choice | `FIXED` \| `ACTUAL_ITINERARY` |
| `default_travel_out_days` | int | Menggantikan separuh `default_travel_days` |
| `default_travel_in_days` | int | idem |
| `travel_out_counts_as_roster_day` | bool, default False | Hari travel dihitung on-site **di rekap**; tidak memotong panjang blok WORK (§0b.2d) |
| `travel_in_counts_as_roster_day` | bool, default False | Seed klien tambang mengisinya `True` — aturan #4 |
| `travel_creates_segment` | bool, default True | False = travel jadi celah kalender saja (perilaku lama) |
| `count_transit_overnight` | bool, default True | Menginap di kota transit dihitung hari travel |
| `travel_variance_credit_eligible` | bool, default **False** | **Delay TIDAK otomatis jadi credit** |
| `travel_variance_credit_max_days` | int, default 0 | Pagar kalau eligible dinyalakan |

`RosterTravelDay` (per Point of Hire) ikut dipecah: `travel_out_days`,
`travel_in_days`, `notes`.

Migrasi dari kolom lama (`default_travel_days` = total PP, ganjil condong ke
sisi keluar): `out = ceil(total/2)`, `in = floor(total/2)`. Hasilnya identik
dengan `RotationPeriod.travel_days` hari ini, jadi jadwal existing tidak
bergeser satu hari pun.

### 3.4 Rotation Credit (baru)

| Field | Tipe | Catatan |
|---|---|---|
| `credit_enabled` | bool, default False | Site yang tidak memakai credit tidak perlu tahu fiturnya ada |
| `credit_conversion_ratio` | Decimal, null | Kosong = dihitung dari `work:off` policy sendiri (56:14 = 4). Perilaku `RosterPolicyResolver.ratio_for` sekarang, dipertahankan |
| `credit_rounding` | choice | `FLOOR` \| `ROUND_HALF_UP` \| `CEIL` \| `EXACT` |
| `credit_carry_remainder` | bool, default True | Sisa yang belum jadi satu hari penuh disimpan, bukan hangus |
| `credit_max_balance_days` | Decimal, null | Kosong = tanpa plafon |
| `credit_expiry_months` | int, null | Kosong = tidak kedaluwarsa. Eksekusi EXPIRED baru di fase berikut |

### 3.5 Aturan pengajuan (sudah ada, dipertahankan)

`request_lead_days`, `notify_lead_days`, `urgent_purposes` (M2M
`RotationPurpose`), `conversion_ratio` (dipetakan ke
`credit_conversion_ratio`).

---

## 4. Current Cycle Start — tempat penyimpanan

Tiga lapis, dan urutannya menentukan:

1. **`EmploymentAssignment.roster_cycle_start`** — sumber kebenaran keadaan
   sekarang, satu nilai per pegawai. Inilah yang diminta: dua orang satu policy
   `GBE-6-2` boleh punya jangkar berbeda.
2. **`SiteRotation.cycle_start`** — salinan beku ke dokumen rencana saat commit.
   Alasannya sama dengan `cycle_work_days` yang sudah disalin hari ini: rencana
   yang sudah disetujui dan sudah dibelikan tiket tidak boleh bergeser karena
   ada yang mengoreksi master minggu depan.
3. **`RosterCrew.cycle_start_date`** — tetap ada untuk kompatibilitas
   `LeaveDayCalculator`, turun jadi **saran** saat mengisi form
   (`autofill`), bukan sumber.

**Riwayat perubahannya** — lihat §7.4. Ringkasnya: `EmploymentAssignment`
adalah satu baris keadaan-sekarang dan tidak bisa effective-dated, jadi
riwayatnya ditumpangkan ke mekanisme yang sudah ada (`EmployeeAction` +
`RosterPlanVersion`), bukan ke tabel history baru.

**Yang tidak berubah:** pegawai tanpa `roster_policy` **tidak punya**
`roster_cycle_start`, tidak masuk generator, tidak muncul di layar roster.
Pegawai HO tidak tersentuh sama sekali.

---

## 5. Roster Plan / Cycle generation (rolling horizon)

### 5.1 Bentuk satu siklus

```
[ WORK n hari ][ TRAVEL_OUT ][ FIELD_BREAK m hari ][ TRAVEL_IN ][ WORK ...
```

- `TRAVEL_OUT` / `TRAVEL_IN` **tidak dibuat** kalau
  `travel_creates_segment=False` atau hari travelnya 0 (pegawai lokal, test
  case L) — siklusnya jadi `WORK → FIELD_BREAK → WORK` tanpa cabang khusus di
  generator.
- `counts_as_roster_day` diisi per arah dari policy
  (`travel_out_counts_as_roster_day` / `travel_in_counts_as_roster_day`). Ia
  **tidak pernah memendekkan blok `WORK`** — lihat §0b.2d. Panjang siklus tetap
  `work + off + travel_out + travel_in`, persis perilaku generator sekarang,
  jadi jadwal existing tidak bergeser.

### 5.2 Fungsi murni, tanpa DB

`RosterCalculationService` menggantikan/membungkus `RotationPeriodGenerator`,
tetap tanpa satu pun query:

```python
RosterCalculationService.build_segments(
    cycle_start: date,
    basis: str,
    work_days: int,
    off_days: int,
    travel_out_days: int,
    travel_in_days: int,
    travel_counts_as_roster_day: bool,
    travel_creates_segment: bool,
    horizon_end: date,          # bukan cycle_count
    start_sequence: int = 1,
) -> list[SegmentRow]
```

Perbedaan penting dari sekarang: **batasnya tanggal, bukan jumlah siklus.**
`cycle_count` masih disimpan di header sebagai angka turunan untuk kolom
tabel, tapi generator berhenti di `horizon_end`. Ini yang membuat rolling
horizon jadi satu parameter, bukan hitungan manual.

Pagar: `MAX_HORIZON_MONTHS = 24`, `MAX_SEGMENTS_PER_PLAN = 400`, dan
`horizon_end` dipotong ke `min(diminta, today + MAX)` — generator tidak boleh
bisa diminta membuat roster tak hingga.

### 5.3 Rolling horizon

- `horizon_end = today + policy.rolling_horizon_months`, dihitung saat commit
  dan setiap kali extend.
- Perpanjangan lewat `tenant_command extend_roster_horizon [--schema=] [--dry-run]`,
  idempoten: untuk tiap plan ACTIVE yang `horizon_end < target`, generate
  **hanya dari `horizon_end + 1`** dan simpan sebagai versi
  `HORIZON_EXTENSION`. Segmen lama tidak disentuh sama sekali, jadi ini bukan
  regenerasi dan tidak butuh approval.
- Perintah, bukan Celery Beat — `django_celery_beat` masih dikomentari di
  `SHARED_APPS`. Begitu beat dinyalakan, task-nya tinggal membungkus command
  yang sama dengan `schema_context()`.

---

## 6. Preview

Preview **tidak menulis apa pun**, dan itu gampang karena kalkulatornya sudah
fungsi murni.

`POST /api/hr/roster-plans/preview/`

```jsonc
// request
{
  "employee": 154,
  "roster_policy": 3,
  "cycle_start": "2026-08-01",
  "roster_start_basis": null,        // null = ikut policy
  "horizon_months": 12,
  "opening_rotation_credit": 0
}
// response
{
  "segments": [ { "sequence": 1, "segment_type": "work", "start_date": "...",
                  "end_date": "...", "total_days": 42,
                  "counts_as_roster_day": true }, ... ],
  "summary": { "cycles": 6, "work_days": 252, "field_break_days": 84,
               "travel_days": 12, "start_date": "...", "end_date": "..." },
  "travel_days_reason": "GBE-6-2: Makassar → 1 out / 1 in.",
  "validations": [
    { "level": "blocking", "code": "no_policy",  "message": "..." },
    { "level": "warning",  "code": "no_partner", "message": "..." }
  ]
}
```

Preview yang sama dipakai tiga tempat: layar setup satuan, layar bulk (per
baris), dan layar review sebelum submit approval. Satu implementasi, karena
begitu ada dua, salah satunya akan menampilkan angka yang berbeda dari yang
akhirnya tersimpan.

**Warning vs blocking** (diminta eksplisit):

| Level | Contoh |
|---|---|
| **Blocking** — tidak bisa commit/submit | policy kosong; cycle start kosong; `work_days`/`off_days` ≤ 0; overlap dengan plan aktif lain milik pegawai yang sama; cycle start setelah `termination_date`; pegawai tidak punya company |
| **Warning** — boleh lanjut | back-to-back partner kosong; Point of Hire kosong (travel jatuh ke default site); cycle start > 1 siklus di masa lalu; travel days 0 padahal site punya aturan travel; policy berbeda dari `roster_crew.work_schedule`; ada cuti APPROVED yang jatuh di blok WORK |

---

## 7. Approval → Baseline

### 7.1 Status dokumen

`SiteRotationStatus` sudah memuat nilainya. Yang dipakai:
`DRAFT → SUBMITTED → APPROVED → ACTIVE`, plus `REJECTED`, `CANCELLED`,
`COMPLETED` (era yang sudah ditutup).

### 7.2 Alur

```
Preview (tanpa DB)
   └─ Commit      → SiteRotation DRAFT + RosterPlanVersion v1 (status DRAFT)
                    + segmen v1
   └─ Submit      → WorkflowService.submit(module="hr",
                       document_type="roster_plan" | "roster_setup")
   └─ Approve     → registry.register_completion → RosterPlanService.on_workflow_done
                    → status ACTIVE, baseline_version = v1,
                      segmen v1 di-lock, locked_at diisi
   └─ Reject      → status REJECTED, segmen v1 dibuang (soft delete)
```

Dua `document_type` baru: `roster_setup` (dokumen bulk, §12) dan
`roster_adjustment` (§8). Plan satuan diajukan lewat `roster_setup` berisi satu
baris — satu jenis dokumen approval, bukan dua yang harus dijaga tetap sama.

Kebutuhan seed yang menyertainya: `NumberingSequence` `hr/roster_setup` (prefix
`RSU`) dan `hr/roster_adjustment` (prefix `RAJ`); `WorkflowDefinition`
`HR-ROSTER-SETUP` dan `HR-ROSTER-ADJUSTMENT`; `register_route` ke halaman FE;
item menu di `seed_menus`.

### 7.3 Baseline — segmen tidak pernah disunting

Aturan keras: **`RotationPeriod` tidak pernah di-`UPDATE` untuk mengubah
tanggal.** Yang ada cuma tutup-dan-ganti.

- Tiap segmen membawa `version_from` dan `version_to` (null = masih berlaku).
- Baseline v1 = segmen yang `version_from <= 1` dan (`version_to` null atau
  `>= 1`).
- Rencana berjalan = segmen yang `version_to` null.
- Adjustment membuat v2: segmen masa depan yang terkena ditutup
  (`version_to = 1`), segmen pengganti dimasukkan dengan `version_from = 2`.
  Segmen masa lalu **tidak disalin** — mereka tetap satu baris yang dimiliki
  semua versi.

Konsekuensi yang menguntungkan: `TravelRequest.rotation_period` yang menunjuk
blok off masa lalu **tetap valid** setelah adjustment, karena barisnya tidak
diganti. Yang bisa yatim cuma TR yang menunjuk blok masa depan yang digeser —
itu justru kasus yang memang harus diberi peringatan (§13 langkah 9).

Alternatif yang **tidak** saya rekomendasikan: menyimpan baseline sebagai
snapshot JSON di header. Lebih sedikit tabel, tapi "blok apa yang dibaselinekan
untuk Agustus" tidak bisa dijawab dengan query — dan itu pertanyaan pelaporan
yang pasti datang.

### 7.4 Perubahan policy permanen (test case J)

Beda kasus, beda jalur. **Jangan dicampur:**

| Kasus | Jalur | Dampak ke jadwal |
|---|---|---|
| Kapal delay, blok diperpanjang | `RosterAdjustment` | Versi baru pada plan yang sama; era tidak berubah |
| Pegawai pindah 8:2 → 6:2 permanen | Perubahan `EmploymentAssignment.roster_policy` **effective-dated** | Plan lama ditutup (`effective_to = effective_date - 1`, status COMPLETED), plan baru dibuat sebagai era berikutnya dengan v1-nya sendiri |

Effective-dating-nya lewat `EmployeeAction` — mekanisme yang sudah ada, sudah
punya approval, `values_before`/`values_after`, dan riwayat di tab History
pegawai. Tambahan yang dibutuhkan: satu nilai baru
`EmployeeActionType.ROSTER_CHANGE` dan kolom `proposed_roster_policy` /
`proposed_roster_cycle_start` / `current_*` pasangannya, plus cabang di
`EmployeeActionService.apply()`.

Alternatifnya tabel `RosterAssignmentHistory` sendiri — saya tidak
merekomendasikan: dua tempat riwayat kepegawaian untuk satu pegawai, dan tab
History yang sudah jalan tidak akan memuatnya.

---

## 8. Adjustment

### 8.1 Schema `RosterAdjustment`

| Kolom | Catatan |
|---|---|
| `document_number` | Deret `hr/roster_adjustment` |
| `plan` FK | Rencana yang disesuaikan |
| `employee` FK | Denormalisasi, untuk filter & data scope |
| `company`/`branch`/`location` | Denormalisasi, pola yang sama dengan `SiteRotation` |
| `adjustment_kind` | lihat tabel di bawah |
| `effective_date` | Titik mulai recalculation. Segmen sebelum tanggal ini tidak disentuh |
| `segment` FK, null | Segmen yang jadi sasaran; kosong = ditentukan service dari `effective_date` |
| `days` | Jumlah hari (selalu positif; arahnya dari `adjustment_kind`) |
| `new_cycle_start` Date, null | Untuk kasus jangkar digeser, bukan blok diperpanjang |
| `credit_impact` | `NONE` \| `EARN` \| `USE`, diusulkan service dari policy, boleh ditimpa approver |
| `credit_days` | Decimal, hasil konversi. Read-only, dihitung `RotationCreditService` |
| `reason` | **Wajib.** Tanpa alasan, dokumen ini tidak menjelaskan apa pun |
| `reference` | Nomor TR / nomor tiket / nomor memo |
| `status` | DRAFT/SUBMITTED/APPROVED/REJECTED/CANCELLED |
| `applied_at`, `apply_error` | Idempotensi + kegagalan penerapan (pola `EmployeeAction`) |
| `resulting_version` FK | Versi yang dilahirkannya |

### 8.2 Jenis adjustment

Empat yang sudah ada di `SiteRotationService.ADJUSTMENT_KINDS` dipertahankan
persis semantiknya, ditambah tiga:

| Kind | Dampak jadwal | Dampak credit |
|---|---|---|
| `work_extension` | Blok WORK diperpanjang `days`, sisanya bergeser | `EARN` (hari ÷ rasio), kalau `credit_enabled` |
| `early_return` | Blok WORK dipendekkan | `USE` atau tidak, tergantung penyebab |
| `deferred_leave` | Blok OFF bertambah `days ÷ rasio` | `NONE` (sudah diberikan sebagai hari off) |
| `late_return` | Blok WORK bertambah `days × rasio` | `NONE` |
| `loyalty` | **Tidak mengubah jadwal** | `NONE` |
| `no_impact` | **Tidak mengubah jadwal** (pesawat cancel, aturan #17) | `NONE`, kecuali policy menyalakan `travel_variance_credit_eligible` |
| `schedule_shift` | Seluruh sisa jadwal digeser `days` | `NONE` |
| `credit_use` | Field break dimajukan sebanyak saldo yang dipakai | `USE` |

`loyalty` dan `no_impact` **tetap mengembalikan penjelasan tertulis** meski
tidak mengubah apa pun — itu perilaku yang sudah ada dan alasannya masih benar:
"kenapa jadwal saya tidak berubah" harus punya jawaban.

**Delay travel tidak otomatis jadi credit.** `no_impact` bawaannya `NONE`.
Yang mengubahnya cuma `travel_variance_credit_eligible=True` pada policy, dan
itu dipagari `travel_variance_credit_max_days`.

---

## 9. Rotation Credit Ledger

### 9.1 `RotationCreditTransaction` (append-only)

| Kolom | Catatan |
|---|---|
| `employee` FK | |
| `entry_type` | `OPENING_BALANCE`, `EARNED`, `USED`, `ADJUSTMENT_PLUS`, `ADJUSTMENT_MINUS`, `EXPIRED`, `REVERSAL` |
| `days` | Decimal(6,2). **Selalu positif**; arahnya dari `entry_type` |
| `transaction_date` | Kapan dicatat |
| `effective_date` | Kapan berlakunya (bisa mundur untuk opening balance) |
| `source_module`, `source_type`, `source_id` | Referensi ke asal — `hr`/`roster_adjustment`/`42`. String, tanpa `GenericForeignKey`, pola yang sama dengan `WorkflowInstance` |
| `plan` FK null, `segment` FK null | Tautan langsung kalau ada |
| `remainder_days` | Sisa excess yang **belum** dikonversi, dibawa ke transaksi berikutnya |
| `reason` | Wajib untuk `ADJUSTMENT_*`, `EXPIRED`, `REVERSAL` |
| `reverses` FK self, null | Diisi hanya oleh `REVERSAL` |
| `created_by`, `created_at` | Dari `BaseModel` |

Aturan yang ditegakkan service, bukan cuma konvensi:

- **Tidak ada update, tidak ada delete.** `RotationCreditService.update()` dan
  `soft_delete()` melempar. Koreksi = `ADJUSTMENT_PLUS`/`ADJUSTMENT_MINUS`;
  pembatalan transaksi = `REVERSAL` yang menunjuk barisnya.
- Satu `REVERSAL` per transaksi (constraint unik pada `reverses` untuk baris
  aktif) — membalik dua kali berarti saldonya salah dan tidak ada yang tahu.
- `REVERSAL` hanya boleh menunjuk transaksi yang belum pernah dibalik dan
  bukan `REVERSAL` itu sendiri.

### 9.2 Saldo

`RotationCreditBalance` per (employee): `earned`, `used`, `adjustment`,
`expired`, `carried_excess_days`, `balance`. **Dihitung ulang dari ledger**
setiap kali ada transaksi — bukan ditambah/dikurangi inkremental. Alasannya
sama dengan `LeaveBalance.used`: penjumlahan ulang tidak bisa hanyut, dan
saldonya perlu bisa disortir di tabel.

Disimpan **terpisah total dari `LeaveBalance`**. Rotation credit bukan cuti,
tidak punya `leave_type`, tidak punya tahun, dan tidak boleh ikut terhitung di
kartu cuti.

### 9.3 Konversi excess → credit (test case G)

Rasio dari `policy.credit_conversion_ratio`, atau dihitung dari pola sendiri
(`work/off`) — persis `RosterPolicyResolver.ratio_for()` yang sudah ada.

Yang dibawa sebagai sisa adalah **hari excess yang belum terkonversi**, bukan
pecahan credit. Ini pilihan sadar: pecahan 0,33 hari kredit tidak bisa
dijelaskan ke pegawai, sedangkan "1 hari lembur site kamu belum genap jadi
kredit" bisa.

```
excess 7 hari, ratio 3, FLOOR + carry
  7 + carried(0) = 7
  earned      = 7 // 3 = 2 hari
  remainder   = 7 % 3 = 1 hari  → carried_excess_days = 1

berikutnya excess 5 hari
  5 + carried(1) = 6
  earned      = 2 hari
  remainder   = 0
```

`ROUND_HALF_UP`/`CEIL`/`EXACT` memakai `Decimal` dengan 2 desimal dan tidak
menyimpan remainder. `EXACT` menyimpan 2,33 apa adanya — disediakan untuk
tenant yang memang menghitung begitu, bukan sebagai bawaan.

### 9.4 Memakai credit

`credit_use` pada `RosterAdjustment`: field break dimajukan / diperpanjang
sebanyak `days`, ledger mencatat `USED`, dan **Roster Policy tidak disentuh
sama sekali** — itu memang yang diminta. Saldo boleh sampai nol; menembus nol
diblokir kecuali policy mengizinkan (`credit_allow_negative`, default False).

---

## 10. Opening balance & migrasi go-live

Prinsipnya: **rekam keadaan sekarang, jangan karang masa lalu.**

Satu baris `RosterSetupLine` per pegawai memuat persis yang diminta:
`employee`, `roster_policy`, `current_cycle_start`, `opening_rotation_credit`,
`as_of_date`, `note`.

- `current_cycle_start` boleh (dan biasanya) **tanggal lampau** — hari pertama
  blok yang sedang dijalani orangnya sekarang. Generator berangkat dari sana,
  jadi segmen pertama yang dihasilkan adalah blok berjalan dengan sisa hari
  yang benar (test case D).
- Segmen yang seluruhnya jatuh sebelum `as_of_date` **tidak dibuat**. Roster
  ini tidak berpura-pura tahu apa yang terjadi tahun lalu.
- `opening_rotation_credit` → satu transaksi `OPENING_BALANCE` dengan
  `effective_date = as_of_date`, `reason` berisi keterangan dari `note`, dan
  `source_type = "roster_setup"` yang menunjuk barisnya (test case E).
- Segmen yang mulai sebelum `as_of_date` tapi berakhir sesudahnya dibuat utuh
  dan langsung `is_locked=True` — orangnya memang sudah di site sejak tanggal
  itu.

**Jalur input massal:** importer `hr.roster_setup` di atas framework import
generik yang sudah ada (`@register_importer`, preview → confirm → job).
Kolomnya: `employee_number`, `roster_policy_code`, `current_cycle_start`,
`opening_rotation_credit`, `as_of_date`, `note`. Otomatis dapat
`/api/imports/hr.roster_setup/{preview,template,confirm}/` tanpa view baru —
dan `date_fields` **wajib** diisi, kalau tidak `01/08/2026` bisa terbaca
sebagai Januari.

Wajib diingat: setelah importer ditambahkan, **restart worker Celery**.

---

## 11. Travel Day: FIXED vs ACTUAL_ITINERARY

| | `FIXED` | `ACTUAL_ITINERARY` |
|---|---|---|
| Sumber angka | `RosterTravelDay` (site, POH) → `default_travel_*` policy | `TravelArrangement` pada TR yang sudah APPROVED |
| Kapan dipakai | Selalu saat generate rencana | Saat **rekonsiliasi**, setelah TR disetujui |
| Yang tersimpan di segmen | Pita kalender rencana | Pita kalender yang disesuaikan ke etape nyata |

Keduanya bukan pilihan yang saling meniadakan pada satu momen: rencana
**selalu** FIXED (belum ada tiket saat jadwal setahun disusun). `ACTUAL_ITINERARY`
menyalakan langkah kedua — begitu TR disetujui, `RosterRecalculationService`
membandingkan pita rencana dengan etape nyata (test case H:
Jakarta→Sorong→menginap→Gebe = 2 hari, `count_transit_overnight` menentukan
apakah malam transitnya ikut dihitung) dan, kalau berbeda, **mengusulkan**
`RosterAdjustment` bertipe `no_impact` — usulan, bukan mutasi otomatis.

Test case I (rencana 2 hari, aktual 3): variance tercatat sebagai warning +
usulan adjustment; **tidak ada transaksi credit** kecuali
`travel_variance_credit_eligible=True`. Ini yang diminta eksplisit dan akan
saya buatkan test-nya.

`travel_counts_as_roster_day` menentukan apakah pita travel mengisi kuota
on-site. Bawaannya **False** supaya jadwal yang sudah berjalan tidak bergeser
saat fitur ini dirilis.

---

## 12. Bulk roster workflow (Site → Section → Employees)

```
1. Pilih Site (Location)                 → wajib
2. Pilih Section / Department             → opsional, penyaring
3. Sistem menampilkan pegawai kandidat    → yang punya organisasi di site itu,
                                            belum punya plan aktif,
                                            belum di-terminate
4. Pilih Roster Policy default            → berlaku untuk seluruh baris,
                                            per baris boleh berbeda
5. Isi Current Cycle Start per baris      → boleh beda-beda (test case B & C).
                                            Ada tombol "isi semua dengan
                                            tanggal ini" sebagai pintasan,
                                            bukan sebagai aturan
6. Preview                                → per baris: segmen + summary +
                                            validations
7. Review                                 → warning vs blocking dipisah;
                                            baris blocking tidak bisa ikut
8. Submit                                 → SATU WorkflowInstance untuk
                                            seluruh dokumen
9. Approve                                → commit N plan sekaligus, tiap plan
                                            dapat v1 + baseline
```

Satu dokumen, satu approval — bukan 30 item di kotak masuk approver. Plan
satuan tetap lewat dokumen yang sama dengan satu baris.

Kandidat disaring `DataScopeService` seperti layar lain, jadi admin site tidak
melihat pegawai site lain.

Aturan yang mengikat, seluruhnya dari §0b keputusan 3:

- **Satu batch = satu Site**, opsional satu Section — blocking validation.
  Tanpa itu cakupan approver tidak bisa ditentukan dan dokumennya mendarat di
  meja yang salah tanpa suara.
- **Alur batch hanya boleh memakai step `role`/`user`.** Step `manager` /
  `department_head` / `position` ditolak saat submit dengan pesan yang menyebut
  step-nya.
- **Organisasi sampel** untuk cakupan role diambil dari baris ber-`employee_number`
  terkecil; sah karena aturan pertama, deterministik supaya approver-nya tidak
  berubah antar submit.
- `subject_employee` instance dibiarkan kosong — ini dokumen perencanaan HR,
  bukan dokumen milik satu pegawai.
- Keberatan sebagian → **`RETURNED`**, bukan approve per baris.
- Commit per baris dengan savepoint; baris gagal jadi `FAILED` + `commit_error`
  dan diulang lewat `POST .../commit/`. Kegagalan commit **tidak** membatalkan
  persetujuan.
- `MAX_SETUP_LINES = 200`.

Pencegahan overlap: `RosterSetupService.assert_no_active_plan()` menolak baris
yang pegawainya sudah punya plan `effective_to IS NULL`, dengan pesan yang
menyebut **nomor dokumen** yang menabraknya (pola
`EmployeeLeaveService.assert_no_overlap`). Diperiksa dua kali — saat preview
dan saat commit — karena di antara keduanya bisa ada dokumen lain yang
disetujui duluan. Baris yang tertabrak jadi `FAILED`; sisanya tetap terbit.

---

## 13. Recalculation algorithm

`RosterRecalculationService.recalculate(plan, effective_date, source, reason, user)`

```
 1. select_for_update pada plan. Baca ulang dari DB — memeriksa instance yang
    sudah di tangan membuat dua permintaan bersamaan sama-sama lolos.
 2. Tolak kalau effective_date < plan.effective_from,
    atau effective_date <= tanggal segmen terakhir yang is_locked.
 3. Buat RosterPlanVersion v(n+1): source, effective_from, reason,
    reference_type/reference_id, created_by.
 4. Tentukan titik potong:
      - segmen yang end_date < effective_date        → tidak disentuh
      - segmen yang start_date >= effective_date     → ditutup (version_to = n)
      - segmen yang memuat effective_date            → DIPECAH:
            bagian [start .. effective_date-1] tetap, end_date-nya disalin ke
            baris baru milik v(n+1) yang menutup di situ;
            sisanya ditutup.
 5. Tentukan jangkar baru:
      - adjustment.new_cycle_start kalau diisi
      - kalau tidak: hari setelah segmen terakhir yang bertahan,
        ditambah dampak adjustment (perpanjangan / pemendekan / geseran)
 6. Generate maju dari jangkar itu sampai horizon_end memakai
    RosterCalculationService (fungsi murni, tidak menyentuh DB).
 7. Insert segmen baru dengan version_from = n+1, sequence melanjutkan
    nomor terakhir yang terpakai.
 8. Sinkronkan header: end_date, horizon_end, cycle_count, current_version.
 9. Perbaiki tautan yang jadi yatim:
      TravelRequest yang rotation_period-nya ditutup → dipetakan ulang ke
      segmen baru yang tanggalnya bertumpuk; kalau tidak ada, di-null-kan dan
      dicatat sebagai warning pada dokumen. TIDAK menghapus TR apa pun.
10. Transaksi credit (kalau ada) dicatat RotationCreditService — sekali,
    dipagari applied_at pada dokumen adjustment.
11. AuditTrail: action=UPDATE, module="hr/roster", object_id=plan.pk,
    before = ringkasan versi n, after = ringkasan versi n+1,
    plus reason & reference.
```

Sifat yang harus dipenuhi dan akan ditest:

- **Idempoten**: memanggil ulang dengan `effective_date` yang sama pada
  dokumen adjustment yang sudah `applied_at` tidak menghasilkan versi baru.
- **Masa lalu tidak berubah**: tidak ada satu pun `UPDATE` pada segmen yang
  `end_date < effective_date`.
- **Baseline utuh**: query segmen `version_from <= baseline <= version_to`
  memberi hasil yang sama sebelum dan sesudah adjustment.

---

## 14. Back-to-Back partner

- Satu kolom: `EmploymentAssignment.back_to_back_partner` (FK `Employee`,
  null, `SET_NULL`).
- **Referensi, bukan validasi.** Pegawai tanpa pasangan valid sepenuhnya (test
  case K).
- Preview memberi **warning** `no_b2b_partner` kalau site-nya lazim
  berpasangan; warning tidak pernah memblokir submit maupun approve.
- **Tidak ada auto-sync** jadwal partner di fase ini. Yang ada cuma tampilan
  pembanding di layar detail (jadwal saya vs jadwal partner) supaya tumpang
  tindih terlihat mata, dan warning `b2b_overlap` kalau blok WORK keduanya
  bertumpuk.
- Tidak simetris otomatis. Kalau A menunjuk B tapi B tidak menunjuk A, itu
  warning, bukan koreksi diam-diam.

---

## 15. Migrasi DB, perubahan API/service, perubahan UI

### 15.1 Migrasi (urut, semuanya reversible kecuali yang ditandai)

| # | App | Isi | Risiko |
|---|---|---|---|
| 1 | administration | Tambah kolom pola + travel + credit + `is_default` ke `RosterPolicy`; pecah `RosterTravelDay.travel_days` → out/in | Data migration: `out = ceil(t/2)`, `in = floor(t/2)`; `is_default=True` untuk seluruh baris existing |
| 2 | administration | **Cabut** `uniq_active_rosterpolicy_target`, pasang `uniq_active_rosterpolicy_default` | Aman: constraint lama menjamin cuma ada satu baris per site, jadi tidak ada ambiguitas yang lahir saat upgrade |
| 3 | hr | `EmploymentAssignment`: `roster_policy`, `roster_cycle_start`, `roster_start_basis`, `back_to_back_partner` | Data migration **hanya** mengisi `roster_cycle_start = roster_start_override or roster_crew.cycle_start_date`. Pemetaan `roster_policy` lewat `tenant_command migrate_roster_assignments` (§0b.1e) — tidak menebak |
| 4 | hr | Model baru `RotationCreditTransaction`, `RotationCreditBalance` | — |
| 5 | hr | Model baru `RosterPlanVersion`; kolom baru `SiteRotation`; `version_from/to` + `segment_type` + flag pada `RotationPeriod` | Data migration: seluruh plan existing dapat v1 sintetis, seluruh segmen `version_from = v1`, `segment_type` diisi dari `period_type` |
| 6 | hr | Model baru `RosterSetupRequest`/`Line`, `RosterAdjustment` | — |
| 7 | hr | `EmployeeActionType.ROSTER_CHANGE` + kolom `proposed_roster_*` | Kalau usul §7.4 disetujui |

Semua unique constraint baru **wajib** dikondisikan `Q(is_deleted=False)`,
sesuai konvensi repo.

### 15.2 Service baru (semua di `apps/hr/api/roster/`)

| Service | Tanggung jawab | Menyentuh DB? |
|---|---|---|
| `RosterCalculationService` | Pola → deret segmen; normalisasi `roster_start_basis`; hitung `cycle_length`, `cycles_until` | **Tidak** |
| `RosterGenerationService` | Preview, commit v1, extend horizon | Ya |
| `RosterAdjustmentService` | Dokumen adjustment: validasi, submit, apply | Ya |
| `RosterRecalculationService` | Algoritma §13 | Ya |
| `RotationCreditService` | Ledger + saldo + konversi + reversal | Ya |
| `RosterSetupService` | Bulk setup, kandidat, validasi massal | Ya |
| `RosterPolicyResolver` | **Diperluas**, bukan diganti: `policy_for(employee)` baca assignment dulu | Ya (ringan) |

Aturan yang diminta dan sudah jadi konvensi repo: seluruh formula ada di
`RosterCalculationService` yang tanpa DB, jadi bisa ditest tanpa tenant. Tidak
ada logika di serializer, view, maupun frontend.

### 15.3 Endpoint

```
# Plan
GET/POST/PATCH  /api/hr/roster-plans/
POST            /api/hr/roster-plans/preview/           # tanpa menulis
POST            /api/hr/roster-plans/<id>/extend-horizon/
GET             /api/hr/roster-plans/<id>/segments/?version=<n>
GET             /api/hr/roster-plans/<id>/baseline-diff/
GET             /api/hr/roster-plans/<id>/versions/
GET             /api/hr/roster-plans/calendar/?location=&start=&end=

# Setup (bulk)
GET/POST/PATCH  /api/hr/roster-setups/
GET             /api/hr/roster-setups/candidates/?location=&section=
POST            /api/hr/roster-setups/<id>/preview/
POST            /api/hr/roster-setups/<id>/submit/
POST            /api/hr/roster-setups/<id>/withdraw/

# Adjustment
GET/POST/PATCH  /api/hr/roster-adjustments/
POST            /api/hr/roster-adjustments/<id>/preview-impact/
POST            /api/hr/roster-adjustments/<id>/submit/
POST            /api/hr/roster-adjustments/<id>/apply/       # ulang kalau gagal

# Rotation credit
GET             /api/hr/rotation-credits/                    # ledger
GET             /api/hr/rotation-credits/balance/?employee=
POST            /api/hr/rotation-credits/adjust/             # ADJUSTMENT_±
POST            /api/hr/rotation-credits/<id>/reverse/

# Lookup
GET             /api/administration/references/hr/lookup/roster-policies/
```

Approve/Reject **tidak** punya endpoint sendiri — lewat kotak masuk workflow
yang sudah ada (`/api/workflow/approvals/<id>/{approve,reject,return}/`).

`data_scope` untuk semua viewset baru mengikuti `SiteRotationViewSet` yang
sudah ada, supaya angka roster cocok dengan tabel Employee.

### 15.4 UI (repo Nuxt)

| Layar | Cara dibuat | `framework_module` |
|---|---|---|
| Roster Policy | regenerate | `hr/roster-policies` (sudah ada, tambah tab) |
| Roster Plan (list + detail workspace) | generate | `hr/roster-plans` |
| Roster Setup (bulk) | **tulis tangan** — wizard 4 langkah, bukan CRUD | `hr/roster-setups` |
| Roster Adjustment | generate + dialog | `hr/roster-adjustments` |
| Rotation Credit (ledger + saldo) | generate (read-only) | `hr/rotation-credits` |
| Roster Calendar (gantt per site) | **tulis tangan** | — |

Ingat dua jebakan yang sudah tercatat: `framework_module` menentukan rute
halaman Nuxt (halamannya wajib di `app/pages/<module>/`), dan setelah schema BE
diubah **wajib** `pnpm meinova generate <module>`.

---

## 16. Test

Ini akan jadi **test pertama di repo** (`tests.py` kosong semua). Struktur:
`apps/hr/tests/roster/`.

### 16.1 Unit — tanpa DB, `SimpleTestCase`

`RosterCalculationService`: bentuk siklus, tiga `roster_start_basis`, travel 0
/ ganjil / genap, `travel_counts_as_roster_day` on/off, batas horizon,
`start_sequence`, jangkar di masa lalu, tahun kabisat.

`RotationCreditService.convert()`: keempat mode rounding, carry remainder,
ratio dari policy vs dihitung, ratio 0 / negatif.

**Guard test** (§0b.2a): `RotationPeriod` tidak boleh punya kolom booking —
`ticket_number`, `transport_*`, `accommodation_*`, `origin`, `destination`.
Gagal dengan pesan yang merujuk keputusan 2, supaya yang menambahkannya tahu
kenapa ditolak, bukan cuma bahwa ditolak.

**Test regresi `LeaveDayCalculator`** (§0b.2f): mengunci angka hari cuti
pegawai roster **sebelum** segmen travel dimaterialisasi, termasuk cuti yang
menyeberangi jendela travel. Fase 0 menuliskannya, fase 2 memperbaruinya —
sehingga selisihnya muncul sebagai test yang sengaja diubah, bukan sebagai
angka yang diam-diam berbeda.

### 16.2 Integration — `TenantTestCase`

Service + workflow + ledger + audit.

### 16.3 Pemetaan test case yang diminta

| | Kasus | Test |
|---|---|---|
| A | 6:2, cycle start 1 Aug | `test_generate_normal_cycle` — segmen, tanggal, summary |
| B | Policy sama, cycle start beda | `test_same_policy_different_anchor` — dua pegawai, tidak ada tanggal yang sama |
| C | Bulk 30 pegawai satu section | `test_bulk_setup_preserves_per_employee_anchor` + assert jumlah query (anti N+1) |
| D | Migrasi pegawai mid-cycle | `test_setup_with_past_cycle_start_starts_at_current_block` |
| E | Opening credit +10 | `test_opening_balance_creates_ledger_row` — `entry_type=OPENING_BALANCE`, saldo 10 |
| F | Work extension 6→7 minggu | `test_extension_keeps_baseline` — baseline v1 identik, v2 berbeda, segmen masa lalu tidak ter-`UPDATE` |
| G | Excess 7, ratio 3:1 | `test_credit_conversion_floor_with_carry` — earned 2, remainder 1; lalu excess 5 → earned 2 |
| H | Multi-etape Jakarta→Sorong→Gebe | `test_actual_itinerary_multi_leg` — `count_transit_overnight` on/off |
| I | Delay 2→3 hari | `test_travel_variance_no_auto_credit` — **0 transaksi credit**; lalu dengan flag menyala → 1 transaksi |
| J | 8:2 → 6:2 permanen | `test_policy_change_closes_era` — plan lama COMPLETED, plan baru v1, segmen lama utuh |
| K | Tanpa partner B2B | `test_no_partner_is_valid` — warning ada, approve lolos |
| L | Pegawai lokal | `test_local_employee_without_travel_segments` |
| M | Pegawai HO | `test_ho_employee_not_touched` — 0 plan, 0 query ke generator, `LeaveDayCalculator` tidak berubah |

### 16.4 Edge case tambahan

Cycle start = hari ini; cycle start jauh di masa depan; `work_days=0`;
`off_days=0`; horizon 0 bulan; adjustment `effective_date` di masa lalu
(ditolak); dua adjustment bersamaan (`select_for_update`); reversal ganda
(ditolak); credit menembus nol; pegawai di-terminate di tengah horizon;
overlap dua plan aktif; `RosterPolicy` dihapus saat masih dipakai (`PROTECT`);
DST/timezone — tidak relevan karena semuanya `DateField`, tapi
`timezone.localdate()` tetap dipakai konsisten.

---

## 17. Dampak ke modul lain

### 17.1 Yang PASTI tersentuh

**`LeaveDayCalculator` (`apps/hr/api/leave/calculator.py`)** — dua titik:

- `resolve_rotation_work_days()` menghitung hari kerja dari
  `RotationPeriod.period_type == WORK`. Begitu segmen travel dimaterialisasi
  dan versioning menyala, query ini **wajib** ditambah filter
  `version_to__isnull=True`, kalau tidak segmen versi lama ikut terhitung dan
  hari cuti seseorang jadi dobel. **Ini risiko diam terbesar dari seluruh
  proposal** dan akan saya buatkan test regresi lebih dulu, sebelum kolomnya
  ditambahkan.
- `resolve_roster()` membaca `roster_crew`. Ditambah pembacaan
  `roster_policy`/`roster_cycle_start` dengan crew sebagai fallback, sehingga
  pegawai yang belum dimigrasi tetap terhitung seperti sekarang.

**`TravelRequestService.build_from_period`** — jendela travel yang sekarang
dihitung dari `cycle_travel_days` beralih membaca segmen `TRAVEL_OUT`/`IN`
kalau ada. Perilaku lama tetap jadi fallback.

**`SiteRotationService`** — `generate_periods` / `extend_periods` /
`regenerate_from` / `shift_from` / `adjust_by_ratio` dipindah ke service baru
dan dibungkus versioning. Endpoint lamanya dipertahankan sebagai jalur transisi
(pola yang sama dengan URL import attendance lama).

**Seed & demo** — `seed_roster_policy` (tambah pola + travel out/in),
`seed_demo_workforce` (isi `roster_policy` + `roster_cycle_start` per pegawai
GBE), `reset_demo_data` (buang plan version, setup, adjustment, ledger),
`seed_administration --only=numbering`, `seed_workflows`, `seed_menus`.

**`report_rotation_cycles`** — ikut menyaring versi berjalan.

### 17.2 Yang TIDAK tersentuh (diverifikasi lewat grep)

- **Attendance** — tidak ada satu pun referensi ke `RotationPeriod`,
  `RosterCrew`, atau `cycle_work_days` di `apps/hr/models/attendance/`,
  `apps/hr/imports/`, maupun jalur sync agent. Roster **tidak** menentukan
  hari kerja absensi hari ini, dan proposal ini tidak mengubahnya.
- **Payroll** — tidak ada referensi. Belum ada model payroll run, jadi tidak
  ada tempat roster bisa bocor ke sana.
- **Leave / LeaveBalance / LeavePolicy** — roster **membaca** saja. Field
  break tidak memotong `LeaveBalance`; yang memotong tetap `EmployeeLeave`
  lewat `EmployeeLeaveService`. Satu sumber angka, tetap.
- Organisasi, Employee, Role/Permission, data scope, dashboard, workflow engine
  (cuma menambah `document_type`, tidak mengubah engine).

### 17.3 Arsitektur untuk Field Break (belum diimplementasikan penuh)

Yang disiapkan sekarang supaya integrasi berikutnya tidak perlu bongkar:

- Segmen `FIELD_BREAK` sudah punya jenisnya sendiri, terpisah dari OFF generik.
- `RotationPeriod.purpose` (`RotationPurpose.deducts_leave`) sudah ada dan
  tetap jadi pembeda "memotong saldo atau tidak".
- `RosterPlan` menyediakan **planned field break period** yang bisa dibaca
  Travel Request: `GET /api/hr/roster-plans/<id>/segments/?type=field_break&upcoming=1`.
- Rantai `Roster → Field Break → optional Travel → optional Rotation Credit →
  optional Annual Leave` semuanya sudah punya tautannya
  (`TravelRequest.rotation_period`, `TravelRequestPurpose.employee_leave`,
  `RotationCreditTransaction.segment`). Yang belum: otomatisasi penerbitannya.

---

## 18. Pertanyaan terbuka

Tiga yang paling menentukan sudah dijawab — lihat **§0b Keputusan terkunci**.
Keputusan 1 sekalian menutup pertanyaan soal `RosterCrew`: dipertahankan
sebagai pengelompokan gelombang, `cycle_start_date`-nya turun jadi saran.

Sisanya masih terbuka, tapi **tidak menghalangi fase 0–2** — semuanya baru
menggigit di fase 3 ke atas:

1. **Versioning segmen (tutup-dan-ganti) vs snapshot JSON baseline** —
   rekomendasi saya versioning (§7.3). Dibutuhkan sebelum fase 3.
2. **`RotationPeriodType.OFF` direname jadi `FIELD_BREAK`?** Rename nilai
   berarti data migration + regenerate schema FE. Alternatifnya `OFF`
   dipertahankan sebagai nilai tersimpan dan Field Break jadi label tampilan.
   Dibutuhkan sebelum fase 2.
3. **Riwayat perubahan roster policy lewat `EmployeeAction`
   (`ROSTER_CHANGE`)** — atau tabel history sendiri? (§7.4). Dibutuhkan
   sebelum fase 4.
4. **Rolling horizon default 12 bulan** dan perpanjangannya lewat
   `tenant_command` manual dulu (Celery Beat masih mati) — cukup? Dibutuhkan
   sebelum fase 7.

---

## 19. Urutan pengerjaan yang saya usulkan

| Fase | Isi | Bisa dirilis sendiri? |
|---|---|---|
| 0 | ✅ **SELESAI** — 44 test regresi di `apps/hr/tests/roster/`, plus perbaikan urutan migrasi. Lihat §19b | Ya — jaring pengaman sebelum apa pun disentuh |
| 1 | `RosterPolicy` diperluas + `RosterTravelDay` out/in + migrasi data + layar setting | Ya |
| 2 | `EmploymentAssignment.roster_policy`/`roster_cycle_start` + `RosterCalculationService` + endpoint **preview** | Ya — preview tidak menulis apa pun |
| 3 | Versioning segmen + commit v1 + `RosterSetupRequest` (bulk) + approval + baseline | Ya |
| 4 | `RosterAdjustment` + `RosterRecalculationService` | Ya |
| 5 | `RotationCreditTransaction` + ledger + konversi + saldo | Ya |
| 6 | `ACTUAL_ITINERARY` + rekonsiliasi travel + back-to-back reference | Ya |
| 7 | Rolling horizon command + importer go-live + demo data | Ya |

Tiap fase berdiri sendiri dan tidak meninggalkan setengah fitur di layar —
alasan yang sama dengan kenapa widget tanpa model tidak dibuat, bukan diisi
angka contoh.

---

## 19b. Fase 0 — hasil

`python manage.py test apps.hr.tests.roster --keepdb` → **44 test, semuanya
lolos**.

| Berkas | Jumlah | Jenis |
|---|---|---|
| `apps/hr/tests/roster/test_rotation_generator.py` | 20 | `SimpleTestCase`, tanpa database |
| `apps/hr/tests/roster/test_leave_day_calculator.py` | 24 | `TenantTestCase` |

Yang dikunci: bentuk deret ON/OFF, pemecahan travel ganjil, pagar
`cycle_count`, `cycles_until`/`summarize`/`next_cycle_start`, resolusi
kalender berlapis, hari libur per lokasi, fallback Senin–Jumat, cabang roster
(rumus modulo maupun baris nyata), dan pagar `calculate()`.

Tiga test bertanda **REGRESI ROSTER** merekam perilaku yang memang akan
berubah di fase 2 — itu tujuannya.

### Temuan 1 — migrasi tidak bisa di-replay dari nol (sudah diperbaiki)

Test DB gagal dibuat:
`ValueError: Related model 'administration.site' cannot be resolved`.

Empat migrasi menambah FK ke `administration.Site`, model yang dihapus
`administration/0011_rename_site_to_location`, tapi **tidak satu pun
menyatakan urutannya terhadap rename itu**. Rencana migrasi dari nol
menempatkan rename di posisi 54 dan `imports/0004` di posisi 114 — jadi
migrasi itu menambah FK ke model yang sudah tidak ada.

Ini **bukan cuma masalah test**: jalur kodenya sama persis dengan pembuatan
schema tenant baru, jadi **penyediaan tenant baru sedang rusak**. Database dev
dan tenant `demo` tidak terpengaruh karena keduanya dimigrasi bertahap saat
`Site` masih ada.

Perbaikannya `run_before` pada keempat migrasi — murni metadata urutan, tidak
mengubah satu pun operasi, dan tidak berpengaruh pada database yang sudah
termigrasi (Django hanya mencatat nama migrasi). Tiga di antaranya sebenarnya
*kebetulan* sudah terjadwal benar; ikut ditambal karena menambah migrasi baru
di fase 1 bisa mengubah urutannya kapan saja.

Setelah perbaikan: rename di 54, keempatnya di 33/45/46/53.

### Temuan 2 — travel dihitung dua kali saat menurunkan tanggal mulai

`test_cycle_advance_counts_travel_once` membuktikan satu putaran maju
`work + off + travel` (travel **sekali**), dan `SiteRotation.cycle_length`
sudah menghitungnya begitu.

Tapi `SiteRotationService.apply_cycle_pattern` memakai:

```python
cycle_length = work + off + travel * 2   # apps/hr/api/site_rotation/services.py
```

lalu mengoper angka itu ke `next_cycle_start()`. Akibatnya `start_date` yang
terisi otomatis untuk dokumen baru mendarat di tanggal yang **bukan** awal
siklus crew mana pun — meleset `travel` hari tiap putaran (2 hari untuk
`CREW-6W`).

Hanya kena dokumen baru yang `start_date`-nya dikosongkan supaya diturunkan
dari jangkar crew; tanggal yang diketik manual tidak lewat jalur ini.

**Sudah diperbaiki** (fase 4, bersamaan dengan pembangunan jalur baru):
`cycle_length` di `apply_cycle_pattern` kini `work + off + travel`. Jalur baru
lewat `RosterCalculationService` tidak pernah melewatinya, tapi dokumen yang
masih dibuat lewat layar Roster Schedule lama tetap memakainya — jadi
memperbaikinya bukan pekerjaan yang jatuh sendiri.

### Catatan menjalankan test

- **Pakai `--keepdb`.** Tiap `TenantTestCase` membuat schema tenant sendiri
  lewat `migrate_schemas`; sekali jalan penuh ~4 menit tanpa itu.
- `TenantTestCase` milik django-tenants **tidak memanggil
  `super().setUpClass()`**, jadi tidak ada rollback per-test dan
  `setUpTestData` tidak pernah jalan. Tiap test karena itu membuat pegawainya
  sendiri dan hanya memeriksa miliknya — hasilnya tidak bergantung pada
  bersih-tidaknya data test sebelumnya.

---

## 19c. Hasil implementasi (fase 1–5 dan 7)

Ditulis setelah kodenya jadi, jadi bagian ini **menang** atas rencana di
atas kalau keduanya berbeda. Yang berbeda dari rencana ditandai ⚠.

### Yang sudah berjalan

| Fase | Isi | Berkas utama |
|---|---|---|
| 1 | `RosterPolicy` pembawa pola siklus + travel out/in + rotation credit | `apps/administration/models/references/roster_policy.py`, migrasi `administration/0026` |
| 2 | `EmploymentAssignment.roster_policy` / `roster_cycle_start` / `back_to_back_partner`, kalkulator murni | `apps/hr/api/roster/calculation.py`, migrasi `hr/0033`–`0034` |
| 3 | Setup massal + preview + approval + baseline | `apps/hr/api/roster/{services,setup_service}.py`, `apps/hr/models/roster_setup.py` |
| 4 | Penyesuaian + perhitungan ulang berversi | `apps/hr/api/roster/{recalculation,adjustment_service}.py`, migrasi `hr/0036` |
| 5 | Ledger rotation credit + konversi + saldo | `apps/hr/api/roster/credit_service.py`, migrasi `hr/0035` |
| 7 | Rolling horizon + seed numbering/alur/menu | `apps/hr/management/commands/extend_roster_horizon.py` |

API: `apps/hr/api/roster/{serializers,views,urls,schema}` — empat resource
(`roster-setups`, `roster-setup-lines`, `roster-adjustments`,
`rotation-credits`). Sisi Nuxt sudah digenerate beserta rute halamannya.

### Keputusan yang bergeser dari rencana

⚠ **Nomor putaran naik saat blok kerja dibuka, bukan saat daftar blok
habis.** Rencana tidak menyebut ini, dan implementasi pertama memakai
"habisnya daftar" — yang benar untuk deret yang mulai dari blok kerja,
tapi salah begitu jadwal disambung dari tengah siklus: blok kerja pembuka
putaran kedua masih bernomor 1 dan travel sesudahnya yang bernomor 2.
Dikunci test `test_cycle_number_still_lands_on_work_when_joining_mid_cycle`.

⚠ **`summarize()` mengembalikan tanggal sebagai string ISO.** Rekapnya
dibekukan ke `RosterPlanVersion.summary` yang sebuah JSONField, dan `date`
tidak bisa diserialisasi ke sana. Kegagalannya baru muncul saat commit,
jauh dari layar preview yang memakai rekap yang sama.

⚠ **Rasio konversi kredit diambil dari pola yang dibekukan ke rencana,
bukan dari policy pegawai.** Rencana bisa dibuat sebelum policy-nya
menempel ke penempatan, dan rasio yang tidak ketemu menghasilkan nol
kredit tanpa satu pun pesan. `RosterAdjustmentService.ratio_for(plan=...)`.

⚠ **Kompensasi off tidak diberikan langsung ke jadwal.** Aturan #13
menyebut tambahan off = hari ÷ rasio; angka itu masuk ke ledger sebagai
kredit, lalu dipakai lewat dokumen `Use Rotation Credit`. Memberikannya
langsung berarti dua sumber angka untuk hak yang sama.

⚠ **`RosterGenerationService.commit` ikut menyinkronkan
`EmploymentAssignment`.** Rencana yang terbit tanpa menyentuh assignment
membuat form pegawai menampilkan keadaan yang berbeda dari jadwalnya, dan
resolver policy tidak menemukan rasionya.

### Jebakan teknis yang ditemukan saat mengerjakan

- **`select_for_update` + `select_related` pada FK nullable ditolak
  PostgreSQL** (`FOR UPDATE cannot be applied to the nullable side of an
  outer join`). `recalculate()` memakai `select_for_update(of=("self",))`.
- **`uniq_active_hr_rotation_period_sequence` berlaku lintas versi**, jadi
  baris pengganti wajib memakai nomor urut berikutnya, bukan nomor yang
  sama dengan yang digantikannya. Nomor urut berlubang di versi berjalan —
  dan itu benar, karena urutan tampilan ditentukan tanggal.
- **Kolom hasil introspeksi model muncul di tabel dengan key yang tidak
  dikirim serializer** (`company` → `company_name`). Tiap schema roster
  punya konstanta `HIDDEN_*_COLUMNS` yang mematikannya.
- **`@action` yang menempel ke method salah.** `SiteRotationViewSet`
  memasang dekorator `url_path="shift-periods"` di atas helper `_user`,
  jadi endpoint-nya memanggil helper itu dan `shift_periods` tidak pernah
  terdaftar. Sudah diperbaiki.

### Gap yang baru ketahuan saat dipakai

**Fitur bulk tidak punya tombol.** `POST .../add-employees/` jalan sejak
awal, tapi tidak pernah dideklarasikan di `schema.actions` — jadi
satu-satunya jalan menambah pegawai ke dokumen setup adalah mengetik
baris satu per satu di grid inline. Endpoint tanpa tombol tidak bisa
dibedakan dari fitur yang tidak ada.

Menutupnya butuh tipe field baru di framework Nuxt: **`multilookup`**
(`framework/components/forms/MMultiLookupField.vue`) — memilih banyak
baris dari sebuah endpoint, dengan pencarian, "Select all shown", dan
baris yang sudah dipakai ditandai lewat `disabled_key`.
`MMultiSelectField` yang sudah ada hanya menerima opsi statis dari
schema, dan daftar pegawai satu site tidak bisa ditulis di schema.
Dirender `MRecordActions.vue`; `endpoint` field-nya menerima `{id}`
seperti `action.endpoint`.

Dua jebakan yang ikut ketahuan di situ:

- **Nilai awal field action selalu `""`.** Untuk multilookup itu membuat
  `v-model` menimpa isian pertama dan `missingRequired` membacanya
  sebagai sudah terisi.
- **`refresh_from_db()` tidak membersihkan cache prefetch.** `line_count`
  dibaca dari `obj.lines.all()` yang di-prefetch sebelum aksinya jalan,
  jadi `add-employees` membalas "2 pegawai ditambahkan" bersama
  `line_count: 0` — dan yang dilihat pengguna cuma angka nol. Keempat
  action setup sekarang membaca ulang lewat `get_queryset().get(pk=...)`.

**Form setup tidak menyebut Company, dan Site-nya tidak bisa dibedakan.**
Tenant demo memuat 12 company dengan 11 baris lokasi bernama persis
"Default Location". Dropdown Site menampilkan tiga belas baris yang
sepuluh di antaranya identik, dan tidak ada satu pun keterangan yang
memberi tahu milik siapa. Sekarang Company ditanyakan lebih dulu
(`required`), Site membawa `lookup_params={"company_id": "$company"}` +
`depends_on="company"`, dan Section menyusul di bawahnya.
`RosterSetupRequest.clean()` menolak Site yang bukan milik company
terpilih — penyaringan form bisa dilewati pemanggil API langsung, dan
dokumen yang company-nya salah mengambil nomor dari deret perusahaan
yang salah.

Sekalian di layar yang sama: `line_count`/`committed_count` diberi
`modes=["edit"]` (dua penghitung yang di layar create muncul sebagai
kotak kosong berlabel "Employees" — di form yang justru punya tombol
Add Employees), dan `horizon_months` diberi `default=12` supaya kotaknya
tidak terbaca sebagai wajib diisi.

**"TR No." di daftar Roster Schedule.** Nama dari masa `SiteRotation`
masih merangkap Travel Request. Sekarang TR punya modelnya sendiri;
kolomnya jadi **Roster No.**, judul layarnya **Roster Schedule**, dan
ditambah kolom **Roster Policy** — rencana yang lahir dari dokumen Setup
tidak punya crew, jadi kolom Roster Crew yang "-" di semua baris
terbaca seperti data belum diisi, bukan seperti jalur yang memang
berbeda.

**Data uji site memegang role yang tidak dipakai alur mana pun.**
`seed_demo_workforce` memberi meja site kembaran `HR-ADMIN-SITE` /
`HR-MANAGER-SITE` demi cakupan data, sementara `HR-TR-SITE` step #4
mencari `HR-MANAGER` bercakupan location dan **tanpa fallback**.
Akibatnya `seed_site_travel_demo` gagal total: alur site tidak bisa
diajukan sama sekali. Meja site sekarang memegang role fungsional yang
sama dengan kantor pusat, dan yang memisahkannya `approver_scope` —
persis yang seharusnya dibuktikan skenario itu. Cakupan data untuk meja
site tetap diperagakan `seed_data_scopes` dengan role-nya sendiri.

**`reset_demo_data` tidak membuang dokumen setup, penyesuaian, dan
ledger kredit**, jadi tiap pembangunan ulang meninggalkan satu RSU tanpa
baris — terbaca persis seperti dokumen yang gagal disimpan. Id dokumen
setup dicatat **sebelum** barisnya dihapus: sesudah itu tidak ada lagi
yang menghubungkannya ke pegawai data uji.

### Yang belum dikerjakan

- **Fase 6**: `travel_day_mode = ACTUAL_ITINERARY` (kolomnya tersimpan,
  rekonsiliasi rencana↔realisasi belum ada) dan layar pembanding
  back-to-back.
- **Kedaluwarsa kredit** (`credit_expiry_months` tersimpan, belum dibaca).
- **Penjadwalan otomatis** `extend_roster_horizon` — butuh
  `django_celery_beat` yang masih dikomentari di `SHARED_APPS`.
- **Importer go-live** untuk `hr.roster_setup`.
