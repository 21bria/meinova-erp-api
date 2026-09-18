# Reports — lapisan laporan global

`apps/reports` adalah **satu-satunya** rumah laporan lintas modul, dan
seluruhnya **read-only**.

## Arah ketergantungan

```
reports → hr
reports → payroll
reports → scm
reports → finance
```

Tidak pernah sebaliknya. Reports boleh memanggil service/query/model
CURRENT dari modul sumber; modul sumber **tidak boleh** mengimpor apa pun
dari `apps.reports`.

Alasannya bukan kerapian. Satu laporan manajemen membaca Attendance,
Leave, Overtime, Roster, dan Employee sekaligus — menaruhnya di salah
satu modul membuat empat modul lain jadi ketergantungan yang tidak
terlihat dari struktur berkasnya, dan laporan Payroll/SCM/Finance
berikutnya tidak punya tempat yang setara.

## Aturan

- **Tidak ada endpoint tulis di seluruh cabang `apps/reports`.** Tidak
  ada `POST`/`PUT`/`PATCH`/`DELETE`, dan servicenya tidak punya jalan
  menulis ke transaksi sumber.
- **Tidak ada model baru untuk menyimpan hasil ringkasan.**
  `apps/reports/models.py` sengaja kosong. Laporan yang di-persist adalah
  angka kedua yang bisa menyimpang dari sumbernya tanpa berbunyi; tambah
  model hanya kalau ada kebutuhan persisted report yang nyata.
- **Jangan membangun ulang engine.** Hari terjadwal, kalender/libur,
  aturan cuti, klasifikasi lembur, dan roster tetap dibaca dari modul
  sumbernya. Tiap kali muncul godaan menulis "kalau tanggalnya Sabtu
  maka…", jawabannya sudah ada di modul sumber — lihat docstring
  `apps/reports/api/hr/period_summary/services.py` yang menyebut satu per
  satu dari mana tiap aturan datang.
- **Cakupan data wajib dipanggil sendiri.** Laporan adalah `APIView`,
  bukan `BaseMasterViewSet`, jadi `filter_queryset()` tidak pernah
  dilewati. Tiap queryset harus lewat `DataScopeService.filter(...)`.

## Struktur

```
apps/reports/
├── api/
│   ├── urls.py                    # /api/reports/
│   └── hr/
│       ├── urls.py                # /api/reports/hr/
│       ├── period_summary/
│       │   ├── urls.py
│       │   ├── views.py           # BaseDashboardAPIView + drill-down
│       │   ├── schema.py          # susunan layar (widget + filter)
│       │   ├── services.py        # agregasi + presenter
│       │   ├── metrics.py         # nama metrik & pengelompokan
│       │   └── drilldown.py       # rincian per angka
│       ├── employee_reporting_audit/
│       │   ├── urls.py
│       │   ├── views.py           # laporan + lookup Reporting Status
│       │   ├── schema.py          # susunan layar (satu tabel, tanpa periode)
│       │   ├── services.py        # perakit baris + presenter
│       │   └── statuses.py        # semantik Account/Reporting Status
│       ├── manpower_summary/
│       │   ├── urls.py
│       │   ├── views.py           # KPI + breakdown + tabel agregat
│       │   ├── schema.py          # susunan layar (tanpa periode)
│       │   └── services.py        # populasi, agregasi, presenter
│       └── contract_expiry/
│           ├── urls.py
│           ├── views.py           # KPI + 2 chart + tabel + 2 lookup status
│           ├── schema.py          # susunan layar (tanpa periode/tanggal)
│           ├── services.py        # populasi, agregasi, presenter
│           └── statuses.py        # ambang bucket + semantik Renewal Status
└── tests/hr/
```

Ini **pola CURRENT**, sama dengan `apps/administration/api/calendar/`
(service duduk di dalam `api/<modul>/<resource>/`), bukan struktur
`services/` + `queries/` terpisah di akar app. Laporan berikutnya
mengikuti bentuk yang sama: satu direktori per laporan di bawah
`api/<domain>/`.

## HR Period Summary

Menumpang runtime dashboard (`schema_type="dashboard"`) dengan sengaja:
pemilih periode, filter lookup berjenjang, dan pembagian hasil per
`widget.key` sudah diselesaikan di `apps/framework/views/dashboard.py`.
Yang ditambahkan cuma satu tipe widget (`table`), bukan runtime kedua.

- `GET /api/reports/hr/period-summary/` — seluruh widget sekaligus
- `GET /api/reports/hr/period-summary/?widget=employee_period_summary&page=2&page_size=50&search=...`
  — satu widget saja; ini yang dipakai tabel saat berpindah halaman
- `GET /api/reports/hr/period-summary/ui-schema/` — schema untuk generator FE
- `GET /api/reports/hr/period-summary/drilldown/?metric=&employee_id=`
  — baris sumber yang **menyusun** angkanya, memakai filter yang sama

### Populasi laporan: organisasi dulu, applicability sesudahnya

Dua populasi yang berbeda, dan **urutannya bagian dari kontrak**:

1. **Populasi organisasi** — filter dropdown lalu `DataScopeService`.
   Menjawab "baris siapa yang boleh dilihat pengguna ini".
2. **Populasi proses** — dari situ,
   `exclude_none_applicable(qs, REPORT_FEATURES)`. Menjawab "dari yang
   boleh dilihat, siapa yang diproses laporan ini".

Applicability karena itu hanya bisa **mempersempit**. Ditaruh lebih
dulu, ia akan terbaca seperti bisa memunculkan pegawai di luar cakupan —
dan kekeliruan seperti itu tidak berbunyi sampai ada yang membuka
laporan orang lain.

`REPORT_FEATURES` = `attendance`, `leave`, `overtime`, `field_break` —
persis proses yang **diwakili kolom** laporan ini. Roster dan Shift
sengaja tidak ikut: laporan ini tidak punya satu pun metrik yang
melaporkannya, jadi memasukkannya membuat pegawai yang cuma punya Roster
tetap terbit sebagai baris nol.

Pegawai yang keempatnya dimatikan tidak menghasilkan baris dan tidak
masuk Headcount laporan. Yang setidaknya satu prosesnya masih berlaku
tetap masuk (semantik **ANY**), dengan metrik yang tidak berlaku
bernilai nol.

### Metric → proses (`METRIC_FEATURES`)

Tiap metrik membaca penandanya sendiri. **Satu flag untuk seluruh
laporan adalah jawaban yang salah**: pegawai yang tidak diabsen tapi
tetap punya cuti harus hilang dari kolom kehadiran dan tetap ada di
kolom cuti.

| Metrik | Proses |
| --- | --- |
| `scheduled`, `present`, `absent`, `late`, `early`, `off_worked`, `holiday_worked` | `attendance` |
| `annual`, `sick`, `other_leave`, `unpaid` | `leave` |
| `field_break` | `field_break` |
| `ot_regular`, `ot_off`, `ot_holiday`, `ot_total` | `overtime` |

Field Break **tidak** menumpang `leave`: `RotationPurpose` memisahkan
keduanya justru karena field break tidak memotong saldo apa pun.

Angka untuk proses yang tidak berlaku **tidak pernah lahir**, bukan lahir
lalu dibuang — `_subject()` menyaring pegawainya sebelum sumbernya
ditarik. Akibatnya `days_by_metric` ikut kosong, jadi drill-down tidak
menawarkan rincian untuk angka yang tidak dihitung.

`PeriodSummary.total()` dan `HRPeriodSummaryDrilldown.resolve()`
menyaring dengan aturan yang **sama** (`row.counts(metric)`) — pembilang
dan rinciannya tidak boleh berasal dari populasi yang berbeda.

### Drill-down: kontrak audit (17 Sep 2026)

`drilldown.py` membangun rincian dari `PeriodSummary` yang sama dengan
tabel. Kontraknya **aditif**: kunci lama (`label`, `unit` hours/days,
`source`, `link`, `count`, `total`, `items[].value/detail/reference`)
tetap terkirim. Yang baru semuanya kode stabil; frontend yang
menerjemahkannya.

| Kunci | Isi |
| --- | --- |
| `source_code` | `attendance` / `leave` / `overtime` / `roster` |
| `detail_kind` | `late` / `early` / `attendance_day` / `leave` / `overtime` / `roster` — menentukan kolom dialog |
| `aggregate` | `{value, unit}`; `unit` = `occurrence` / `day` / `hour` (`METRIC_UNITS`) |
| `occurrences` | jumlah baris rincian |
| `duration_minutes` | total menit, **hanya** untuk Late/Early/OT; `null` untuk metrik hari |
| `duration_complete` | `false` kalau ada kejadian tanpa menit tercatat (mis. status LATE hasil import) |
| `employee` | `{id, name, number}` bila `employee_id` disebut |
| `items[]` | + `employee_id`, `source_code`, `quantity`, `row_unit`, `detail_code`, `scheduled_time`, `actual_time`, `start_time`, `end_time`, `duration_minutes`, `excused_minutes`, `reason`, `range_start`, `range_end`, `record_id` |

Aturan yang tidak boleh dilanggar:

* **Late/Early tetap kejadian.** "4x" di tabel tidak diganti durasi;
  menitnya fakta kedua di `duration_minutes`.
* **Durasi Late/Early = `late_minutes`/`early_leave_minutes`** milik
  `AttendancePolicyResolver`, yang sudah dipotong toleransi. 08:00 →
  08:27 boleh tercatat 12 menit. Selisih jam jadwal dan jam tap
  **tidak pernah** dipakai sebagai durasi, di backend maupun
  frontend. Menit 0 pada baris yang tetap terhitung (status LATE)
  dikirim `null`, bukan ditebak.
* **`total` = `aggregate.value` = accessor tabel** —
  `PeriodSummary(rows=<baris yang sama>).total(metric)`. Sebelumnya
  jam OT dijumlahkan dari `round(menit/60, 2)` per dokumen, jadi tiga
  lembur 20 menit terbaca 0,99 di rincian dan 1,0 di tabel.
* Jam (`HH:MM`) memakai `WALL_CLOCK_TZ`, sama dengan `/me/attendance`.
* Off Worked / Holiday Worked adalah **hari**, bukan jam; barisnya
  membawa jam masuk/pulang dan `worked_minutes` sebagai bukti, tapi
  kepala dialog tidak menjumlahkannya.
* Lembur belum punya nomor dokumen maupun approval (status RECORDED
  saja) — `reference` tetap berisi alasan seperti sebelumnya.

**Cakupan data.** `employee_id` yang tidak ada di populasi laporan
pemanggil (di luar cakupan, di luar filter, atau tidak ada) → **404**
yang sama untuk ketiganya. `employee_id` yang bukan angka → **400**
(dulu diam-diam dibaca "seluruh pegawai"). Tanpa `employee_id`,
rinciannya tetap hanya populasi yang lolos `DataScopeService`.

Test: `apps.reports.tests.hr.test_period_summary_drilldown`.

### Penyebut: `headcount` vs `feature_headcount`

* `headcount` — berapa pegawai di laporan ini.
* `feature_headcount(feature)` — berapa yang **diproses** fitur itu.

Keduanya sama selama seluruh group applicable, dan mulai berbeda begitu
ada yang dimatikan. Rasio yang dibagi jumlah orang harus memakai yang
kedua; memakai yang pertama mengencerkan angkanya dengan orang yang
memang tidak pernah diabsen.

Attendance Rate sendiri = Present ÷ (Present + Absent), dan keduanya
sudah hanya menjumlahkan baris yang Attendance-nya berlaku — pegawai
yang tidak diabsen tidak menyumbang nol ke penyebutnya.

### Hari terjadwal ikut Feature Applicability

"Hari terjadwal" laporan ini datang dari
`apps.hr.api.attendance.schedule.scheduled_work_days_bulk()`, dan sejak
23 Ags 2026 fungsi itu mengembalikan **himpunan kosong** untuk pegawai
yang `EmployeeGroup.attendance_applicable`-nya dimatikan. Jadi direksi
yang memang tidak diabsen keluar dari partisi Scheduled = Present +
Absent + Leave, bukan tampil sebagai mangkir sepanjang bulan.

Penjagaannya sengaja ditaruh di `schedule.py`, bukan di
`AttendanceClosingService`: penutup hari, seed presensi, dan laporan ini
sama-sama lewat sana. Kalau dipasang di penutup hari saja, layar
Attendance bersih tapi laporan tetap menghitung direksi sebagai mangkir
— persis selisih diam yang sudah dihindari dokumen ini di tempat lain.

**Headcount tidak berubah.** Applicability memutuskan siapa yang jadi
subjek sebuah proses, bukan siapa yang terhitung sebagai pegawai. Filter
Employee Group pada laporan ini juga tidak berubah artinya.

Kuncinya tetap terbit di hasil `_bulk` dengan himpunan kosong, jadi
pemanggil yang membaca `result[employee.id]` tidak perlu tahu apa pun
soal applicability.

### Kolom identitas tabel

`Employee ID | Employee Name | Location | Scheduled | …`

Employee ID memakai `employee_number` — kolom yang sudah ada di
`Employee` dan sudah dikirim `table_row()` sejak awal. Yang dulu kurang
cuma kolomnya di schema: data yang terkirim tanpa kolom adalah cara
paling sunyi sebuah field terlihat "tidak ada", dan yang membuka layar
akan mencarinya di backend.

Tiga hal yang **tidak** berubah karenanya, dan ketiganya sengaja:

* **Drill-down tetap memakai `employee_id` internal.** Nomor pegawai
  boleh diketik ulang HR dan boleh kosong, jadi ia bukan kunci.
* **Baris Total melewatinya.** `TOTAL_METRICS` hanya memuat kolom
  angka — menjumlahkan nomor pegawai menghasilkan angka yang tidak
  salah hitung, cuma tidak berarti apa pun.
* **Kotak cari sudah mencocokkan nomor sejak awal** (`search_text` =
  nama + nomor), jadi tidak ada yang perlu ditambahkan di sana.

Export nanti tinggal membacanya dari baris yang sama.

**Lebar dan kolom terkunci.** Kolom terkunci (`sticky_columns`) tidak
bisa menanyakan lebarnya ke browser saat render pertama, jadi framework
memakukannya — bawaannya 224px, ukuran yang pas untuk kolom nama. Kolom
pendek karena itu **wajib** menyebut `width` sendiri; "HO001" di kotak
selebar 224px meninggalkan jarak kosong sampai kolom nama dan terbaca
seperti kolomnya salah pasang. Employee ID memakai `width=104`.

`sticky_columns=2` — nomor **dan** nama ikut terkunci. Satu kolom
terkunci berarti yang tinggal saat tabel digeser mendatar cuma nomor,
dan sembilan belas kolom angka di sebelahnya jadi tidak bisa dibaca
milik siapa.

Sisi framework: `MDashboardTable` menjumlahkan `left` kolom terkunci
dari lebar kolom **sebelumnya**, bukan `index * STICKY_WIDTH`. Perkalian
itu benar hanya selama seluruh kolom terkunci sama lebar; begitu yang
pertama dipersempit, kolom kedua mendarat di tengah kolom pertama dan
menutupinya. Kolom yang tidak menyebut `width` tetap memakai lebar
bawaan, jadi tabel dashboard lain tidak berubah.

### Paginasi

`apps/framework/tables.py` (`TablePage`) — bukan di `apps/reports`, karena
pertanyaannya sama untuk tiap laporan berikutnya.

- Bawaan 25 baris; ukuran dibatasi ke `page_size_options` di schema
  (25/50/100). Angka di luar daftar **jatuh ke bawaan**, bukan dilayani —
  satu tenant tiga ribu pegawai plus `?page_size=99999` berarti seluruh
  agregasi dirakit jadi satu respons
- **`total` dan `totals` selalu dari seluruh dataset yang lolos filter**,
  bukan dari halaman yang sedang terbuka. Ini yang membuat baris Total
  cocok dengan kartu KPI di atasnya; kalau ikut diiris, kartu yang
  menghitung 500 orang berdiri di atas Total yang menjumlahkan 25
- `matched` = yang lolos kotak cari, dasar penghitungan jumlah halaman
- Kotak cari menyaring **tabelnya saja** (nama + nomor pegawai) dan tidak
  menyentuh KPI/chart. Filter laporan punya tempatnya sendiri di
  `filters` dan memang mengubah KPI

Konsekuensi yang belum ditutup: tiap perpindahan halaman merakit ulang
agregasi seluruh pegawai, karena `PeriodSummary` dihitung sekali **per
request** dan halaman diiris dari hasilnya. Cache lintas-request belum
ada.

## Employee Reporting Audit

Laporan **master organisasi**, bukan laporan periode. Yang dijawabnya
satu pertanyaan: *"struktur pegawai, garis pelaporan, dan akun
login-nya sudah lengkap belum?"* — dalam satu tabel yang bisa dibaca
HR dan manajemen tanpa membuka layar Employee satu per satu.

Versi command-line-nya sudah lama ada
(`apps/hr/management/commands/audit_employee_reporting.py`) dan **tetap
ada**; konsep kolom serta querynya yang dipakai ulang di sini. Yang
tidak dipakai ulang adalah kodenya: laporan membaca model lewat service
sendiri di `apps/reports`, karena command itu tidak lewat autentikasi
maupun `DataScopeService` sama sekali. Menjadikannya sumber runtime
berarti satu laporan di layar yang tidak punya cakupan data.

- `GET /api/reports/hr/employee-reporting-audit/` — tabelnya
- `GET /api/reports/hr/employee-reporting-audit/?widget=employee_reporting_audit&page=2&page_size=50&search=...`
  — satu widget saja; ini yang dipakai tabel saat berpindah halaman
- `GET /api/reports/hr/employee-reporting-audit/ui-schema/` — schema
  untuk generator FE
- `GET /api/reports/hr/employee-reporting-audit/reporting-status/`
  (+ `<id>/`) — isi dropdown Reporting Status

Tidak ada drill-down, tidak ada KPI, tidak ada chart, dan **tidak ada
endpoint tulis**. Garis pelaporan diperbaiki di layar Employee; laporan
yang bisa menyunting apa yang dilaporkannya menghapus jejak siapa yang
mengubah apa.

### Tidak ada periode, dan itu bagian dari kontrak

Tidak satu pun kolomnya berubah karena bulan yang dipilih. Pemilih
periode yang tetap dipasang "supaya seragam dengan laporan lain"
mengajari pembacanya bahwa hasilnya bergantung pada bulan, lalu membuat
mereka menyimpulkan salah justru saat datanya tidak berubah.

Dua sisi yang menegakkannya:

* schema tidak mendeklarasikan filter bertipe `period`, dan
  `MDashboard.vue` menyembunyikan pemilihnya sendiri kalau tidak ada;
* `get_period()` di-override mengembalikan `{}` — bawaannya merakit
  rentang bulan berjalan dan mengirimkannya di respons, dan rentang
  yang ikut terkirim untuk laporan yang tidak memakainya adalah
  konfigurasi mati yang terbaca seperti konfigurasi hidup.

### Populasi: cakupan organisasi + filter, titik

```
Population = Authorized Organization Scope ∩ filter yang dipilih
```

`DataScopeService.filter(qs, EMPLOYEE_SCOPE, user)` dipanggil **paling
akhir** dan tidak bisa dilewati; petanya sama persis dengan
`EMPLOYEE_SCOPE` HR Period Summary dan `EmployeeViewSet.data_scope`.
Filter dropdown hanya mempersempit — menyebut id company atau location
di luar cakupan lewat query string tidak membuka satu baris pun.

Yang ikut menyaring di luar itu cuma dua kolom master: `is_deleted=False`
(soft delete) dan `is_active=True`. Yang kedua mengikuti konsep command
lamanya — garis pelaporan orang yang sudah keluar bukan lagi temuan yang
perlu ditindaklanjuti.

### Feature Applicability **tidak** menyaring laporan ini

Sengaja, dan ini keputusan yang paling mudah dibalik oleh orang
berikutnya yang melihat `exclude_none_applicable` dipakai di laporan
sebelah.

HR Period Summary adalah laporan **proses**: kolomnya Attendance,
Leave, Overtime, Field Break, jadi pegawai yang keempatnya dimatikan
tidak punya satu angka pun untuk disumbangkan. Laporan ini melaporkan
**struktur**, dan struktur tidak punya penanda applicability.

Kalau applicability ikut menyaring, direksi hilang dari laporan yang
tugasnya mengaudit garis pelaporan — dan lubang di garis pelaporan
paling mungkin justru ada di puncak struktur, tempat yang tidak punya
atasan untuk mengoreksinya. Di tenant peragaan bedanya terlihat
langsung: Period Summary menghitung **28** pegawai (BOARD seluruh flag
OFF), Employee Reporting Audit menerbitkan **30**.

### Sumber tiap kolom

Tidak satu pun ditebak, dan itu yang membedakan laporan ini dari
"organization chart" yang menyusun atasan dari nama jabatan.

| Kolom | Sumber |
| --- | --- |
| Employee ID / Employee Name | `Employee.employee_number`, `Employee.full_name` |
| Company … Section, Position | `OrganizationAssignment` (`name` masternya) |
| Employee Group / Employment Type / Join Date | `EmploymentAssignment` |
| Masa Kerja | dihitung dari `join_date` saat respons dirakit |
| Report To ID / Name | `OrganizationAssignment.reports_to` |
| Account / Account Email | `Employee.user` → `User.username`, `User.email` |
| Report To Account / Email | `reports_to.user` → `User.username`, `User.email` |
| Account Status | `User.is_active` (+ ada-tidaknya `User`) |
| Reporting Status | ada-tidaknya `reports_to` |

**Report To hanya dari `OrganizationAssignment.reports_to`.** Bukan dari
Employee Group, nama jabatan, role, atau "manager department-nya siapa"
— empat tebakan yang semuanya menghasilkan atasan yang terlihat masuk
akal dan tidak pernah dipilih siapa pun. Akun atasan pun harus milik
orang yang menjadi `reports_to`, bukan akun lain yang kebetulan
sejabatan.

Kolom organisasi yang belum diisi berbunyi **"Belum Ditentukan"**, sama
dengan HR Period Summary. Kolom akun/atasan yang memang kosong dikirim
sebagai string kosong dan dirender "—" oleh `formatDashboardValue` —
satu lambang kosong untuk seluruh tabel dashboard, bukan dua.

**Masa Kerja dihitung, tidak disimpan.** Angka yang disimpan mulai salah
pada hari pertama setelah ditulis, tanpa satu pun proses yang berbunyi.
Bentuknya `"7 th 7 bl"`; tanggal masuk yang belum tiba mengembalikan
kosong, bukan `"0 th 0 bl"` — nol bulan kerja untuk orang yang belum
masuk adalah jawaban yang salah, bukan jawaban yang kecil.

### Semantik status

**Account Status** dibacakan dari `User`, tidak disimpulkan:

| Nilai | Artinya |
| --- | --- |
| `Connected` | `Employee.user` terisi dan `is_active=True` |
| `Inactive` | akunnya ada, `is_active=False` |
| `No Account` | `Employee.user` kosong |

Dua yang terakhir wajib dibedakan: **belum pernah dibuatkan** berbeda
dari **pernah ada lalu dicabut**. Yang pertama tugas HR yang belum
selesai, yang kedua justru sudah selesai ditangani — menggabungkannya
jadi satu "tidak aktif" menghapus persis perbedaan yang dicari
pengaudit.

**Reporting Status faktual, bukan penilaian:**

| Nilai | Artinya |
| --- | --- |
| `Has Report To` | `reports_to` terisi |
| `No Report To` | `reports_to` kosong |

Bukan `OK` / `ERROR`. Direksi dan sebagian pimpinan puncak memang sah
berdiri tanpa Report To, dan master organisasi hari ini **tidak punya
penanda top-level** yang bisa membedakan mereka dari garis pelaporan
yang benar-benar putus. Laporan yang menandai keduanya sebagai galat
melatih pembacanya mengabaikan kolom itu — lalu yang benar-benar putus
lewat bersama sisanya.

Kalau suatu hari master punya penanda root yang authoritative, di
situlah nilai ketiga boleh lahir. **Bukan** dari Employee Group, nama
jabatan, atau job level: itu tebakan yang persis dihindari kolom Report
To sendiri.

### Filter dan kotak cari

Sembilan filter, kunci dan endpoint lookup-nya **sama persis** dengan HR
Period Summary (minus periodenya) — bukan demi keseragaman tampilan,
melainkan supaya `expand_filter_values` dan `DataScopeService`
menegakkan artinya di satu tempat untuk kedua layar:

Company (multi) · Branch · Location (multi, + tombol "Lokasi Saya") ·
Department (multi) · Section (multi) · Employee Group (multi) ·
Employment Type (multi) · Employee · Reporting Status

Seluruh isinya sudah tersaring cakupan di sisi lookup masing-masing.

**Reporting Status tidak lewat `LookupRegistry`** karena tidak punya
model — ia lahir dari ada-tidaknya `reports_to`. Dilayani laporan ini
sendiri sebagai dua pilihan tetap dengan bentuk respons
`{count, next, previous, results}` yang sama dengan `BaseLookupView`,
jadi `MLookupSelect` memakannya tanpa perlu tahu bedanya. Id-nya angka
(`1` = Has Report To, `2` = No Report To) karena `toNumber()` di
`MDashboardFilters.vue` meng-`Number()` nilai filter satu-pilihan; id
berupa teks mendarat sebagai `null` dan dropdown-nya terlihat kosong
padahal isinya terkirim. Nilai yang tidak dikenal = **tanpa
penyaringan**, aturan yang sama dengan filter dashboard lain.

Kotak cari mencocokkan **delapan identitas**, bukan seluruh baris:
nomor & nama pegawai, akun & emailnya, lalu nomor, nama, akun, dan email
atasannya. Konsekuensi yang disengaja: mengetik nomor seorang manajer
menghasilkan barisnya **dan** seluruh bawahannya — persis yang dicari
pengaudit, satu perintah untuk satu cabang.

Paginasi memakai `apps/framework/tables.py` (`TablePage`) yang sama
dengan laporan lain: bawaan 25, ukuran dibatasi ke `page_size_options`,
`total` = seluruh baris yang lolos filter, `matched` = yang lolos kotak
cari. **Tidak ada baris Total** — seluruh kolomnya identitas, dan
menjumlahkan nomor pegawai menghasilkan angka yang tidak salah hitung,
cuma tidak berarti apa pun.

### Invariant yang dijaga test

`apps/reports/tests/hr/test_employee_reporting_audit.py` — 39 test.
Yang paling penting bukan angkanya melainkan **kelengkapannya**:
laporan audit yang diam-diam menghilangkan barisnya sendiri lebih buruk
daripada laporan yang gagal, karena yang membacanya menyimpulkan
strukturnya sudah rapi.

- pegawai **tanpa akun** tetap terbit, dengan sel akun kosong dan
  status `No Account` — justru temuan yang dicari
- pegawai **tanpa Report To** tetap terbit, status `No Report To`
- **BOD tetap terbit** walau seluruh flag applicability group-nya OFF
- akun yang dimatikan **dibedakan** dari tidak punya akun
- akun atasan datang dari `reports_to`, dan atasan tanpa akun
  menyisakan kolomnya kosong (bukan kolom orang lain)
- filter Company multi-select, Location, Department/Section, Employee,
  dan Reporting Status hanya mempersempit
- **cakupan tidak bisa dilewati lewat query param** — id company atau
  location di luar cakupan mengembalikan nol baris, disebut sendiri
  maupun disebut bersama id yang memang dicakup
- pengguna bercakupan satu lokasi hanya melihat lokasinya
- **satu query untuk seluruh baris** (`assertNumQueries`-style):
  akun, atasan, dan email atasan lewat `select_related`, dan hasilnya
  dihitung sekali per request

```bash
python manage.py test apps.reports.tests.hr.test_employee_reporting_audit --keepdb
python manage.py test apps.reports.tests.hr.test_manpower_summary --keepdb
python manage.py test apps.reports.tests.hr.test_contract_expiry --keepdb
```

## Manpower Summary

Laporan **manajemen** atas jumlah dan komposisi tenaga kerja. Yang
dijawabnya satu pertanyaan: *"berapa orang, tersebar di mana, dan
komposisinya apa"* — per company, location, department, Employee Group,
dan jenis kepegawaian.

Tiga laporan yang sering tertukar dengannya, dan bedanya bukan
tampilannya:

| | Isi | Satu baris = | Berubah per bulan? |
| --- | --- | --- | --- |
| **Employee Master** (`apps/hr/api/employee`) | input & perawatan data pegawai — **punya tulis** | satu pegawai | — |
| **Employee Reporting Audit** | kelengkapan struktur, garis pelaporan, akun | satu pegawai | tidak |
| **Manpower Summary** | jumlah & komposisi workforce | satu **kelompok** organisasi | tidak |
| **HR Period Summary** | hasil operasional (hadir, cuti, lembur) | satu pegawai | ya |

Yang membuat laporan ini bukan salinan ketiganya adalah barisnya:
**agregat**, bukan daftar pegawai. Daftar pegawai satu per satu sudah
punya dua tempatnya sendiri; menyalinnya ke sini berarti tiga layar
yang harus dijaga tetap sama tanpa ada yang meminta layar ketiga.

- `GET /api/reports/hr/manpower-summary/` — seluruh widget sekaligus
- `GET /api/reports/hr/manpower-summary/?widget=manpower_table&page=2&search=...`
  — satu widget saja; ini yang dipakai tabel saat berpindah halaman,
  supaya empat KPI dan lima chart tidak dihitung ulang untuk jawaban
  yang sama persis
- `GET /api/reports/hr/manpower-summary/ui-schema/` — schema untuk
  generator FE

Tidak ada drill-down dan **tidak ada endpoint tulis**. Komposisi
manpower diperbaiki di layar Employee.

### Snapshot, bukan periode

Laporan ini **potret hari ini**: yang dihitung adalah pegawai yang
berstatus aktif saat request dilayani. Tidak satu pun angkanya berubah
karena bulan yang dipilih, jadi pemilih periodenya tidak ada — sisi
yang menegakkannya sama persis dengan Employee Reporting Audit (schema
tidak mendeklarasikan filter bertipe `period`; `get_period()`
di-override mengembalikan `{}`).

**Headcount as-of tanggal tertentu adalah laporan yang berbeda** dan
butuh riwayat penempatan (`EmployeeAction`/`EmployeeHistory`), bukan
master hari ini. Dicatat sebagai NEXT di bawah — bukan ditebak diam-diam
dari data yang ada.

### Populasi

```
Population = Authorized Organization Scope ∩ filter yang dipilih
```

`DataScopeService.filter(qs, EMPLOYEE_SCOPE, user)` dipanggil **paling
akhir** dan tidak bisa dilewati; petanya sama persis dengan HR Period
Summary, Employee Reporting Audit, dan `EmployeeViewSet.data_scope`.
Filter dropdown hanya mempersempit — menyebut id company atau location
di luar cakupan lewat query string tidak menambah satu orang pun ke
headcount.

Yang ikut menyaring di luar filter cuma dua kolom master:
`is_deleted=False` (soft delete) dan `is_active=True`. Yang kedua yang
menjadikannya *headcount* dan bukan *jumlah baris pegawai yang pernah
ada* — orang yang sudah keluar bukan lagi manpower, dan menghitungnya
membuat angka laporan naik terus selamanya.

### Feature Applicability **tidak** menyaring manpower

Aturan yang sama dengan Employee Reporting Audit — lihat bagian
"Feature Applicability **tidak** menyaring laporan ini" di atas untuk
kontrasnya dengan HR Period Summary — tapi alasannya di sini satu
tingkat lebih keras: **manpower adalah angka organisasi, bukan angka
proses.** Direksi yang seluruh proses HR-nya dimatikan tetap orang yang
digaji dan tetap menempati kursi di struktur.

Kalau applicability ikut menyaring, "Total Headcount" di laporan
manpower menjadi lebih kecil daripada jumlah orang yang benar-benar
bekerja, dan tidak ada satu pun di layar yang memberi tahu selisihnya.
Di tenant peragaan bedanya terlihat langsung: HR Period Summary
menghitung **28** pegawai (BOARD seluruh flag OFF), Manpower Summary
dan Employee Reporting Audit sama-sama **30**.

Tidak satu pun kode Employee Group dibaca di modul ini (`BOARD`, `BOD`,
`MANAGEMENT`, …); ada test yang memindai sumbernya untuk memastikannya.

### Permanent vs Contract: `requires_contract`, bukan nama

Yang membelah komposisi adalah **`EmploymentType.requires_contract`**,
penanda master yang sama dengan yang dipakai form Employee untuk
menyalakan kolom Contract Type/Start/End. Bukan nama dan bukan kode
jenisnya:

- `requires_contract=False` → **Permanent**
- `requires_contract=True` → **Contract** (jadi "Daily Worker",
  "Intern", "Outsourcing", dan "Consultant" ikut ke sini — semuanya
  memang berbasis kontrak)
- tidak punya `EmploymentAssignment`/jenis kepegawaian sama sekali →
  **Belum Ditentukan**

Karena itu invariant yang benar adalah:

```
Permanent + Contract + Belum Ditentukan = Headcount
```

dan **bukan** `Permanent + Contract = Headcount`. Master hidup
(`apps/administration/seeds/reference/hr.py`) berisi enam jenis
kepegawaian, dan pegawai yang jenisnya belum diisi tidak masuk keduanya.
Kartu KPI keempat ("Tanpa Employment Type") ada justru supaya selisihnya
tidak pernah harus dicari sendiri oleh yang membacanya; di tenant yang
masternya rapi angkanya nol, dan itu jawaban yang berguna.

### KPI, breakdown, dan tabel

Empat kartu KPI, semuanya `trend=False` — tidak ada periode berarti
tidak ada periode pembanding, dan "naik 0% dari bulan lalu" di bawah
angka yang tidak pernah dibandingkan cuma derau yang terbaca sebagai
fakta.

| Widget | Tipe | Isi |
| --- | --- | --- |
| `headcount` | stat | Total Headcount |
| `permanent` | stat | `requires_contract=False` |
| `contract` | stat | `requires_contract=True` |
| `unspecified_employment_type` | stat | tanpa jenis kepegawaian |
| `company_breakdown` | bar (stacked) | headcount per company |
| `location_breakdown` | bar (stacked) | headcount per location |
| `department_breakdown` | bar (stacked) | headcount per department |
| `employee_group_breakdown` | donut | proporsi per Employee Group |
| `employment_type_breakdown` | donut | proporsi per jenis kepegawaian |
| `manpower_table` | table | agregat company → location → department |

Batangnya bertumpuk Permanent/Contract supaya satu chart menjawab
sebaran sekaligus komposisinya; tinggi tiap batang tetap sama dengan
headcount kelompok itu. Tumpukan ketiga ("Belum Ditentukan") hanya ikut
kalau memang ada isinya — legenda dengan satu entri yang selalu nol cuma
derau. Ekor di luar delapan kelompok terbesar dijumlahkan ke satu batang
"Lainnya", jadi total chart tetap sama dengan Total Headcount.

Kolom tabelnya: Company, Location, Department, Headcount, Permanent,
Contract, Belum Ditentukan. Widget-nya membawa `total_label="Kelompok"`
— penghitung baris di kanan atas kartu tabel, yang bawaan frontend-nya
"Pegawai": benar untuk dua laporan HR lain yang satu barisnya satu
orang, menyesatkan di sini karena angkanya (11 kelompok) berdiri tepat
di sebelah kartu KPI yang berbunyi 30. Diurutkan menurut **kode** master (bukan
jumlah): tabel ini dibaca sebagai daftar organisasi, dan urutan yang
berpindah tiap kali ada satu orang pindah department membuat pembacanya
kehilangan barisnya sendiri. Kelompok yang salah satu tingkatnya belum
diisi tetap terbit sebagai "Belum Ditentukan" dan berdiri di ujung —
orangnya tetap dihitung.

`totals` (baris Total) dan `total` (jumlah baris) dihitung dari
**seluruh** populasi yang lolos filter, jadi tidak ikut berubah saat
halaman digeser maupun saat ada yang diketik di kotak cari. Paginasi dan
kotak carinya `apps/framework/tables.TablePage`, sama dengan dua laporan
lain.

### Filter

Delapan, kuncinya sama persis dengan laporan HR lain (`company`,
`branch`, `location`, `department`, `section`, `employee_group`,
`employment_type`, `employment_status`) supaya `expand_filter_values`
dan `DataScopeService` menegakkan artinya di satu tempat untuk ketiga
layar. Quick: Company, Location, Department. Sisanya di panel Advanced
Filter. "Lokasi Saya" (`self_filter`) tersedia di Location, sama dengan
laporan lain.

**Tidak ada filter Employee** — laporan agregat yang disaring ke satu
orang cuma menghasilkan satu baris berisi angka 1, dan pertanyaannya
sudah dijawab Employee Master.

Satu filter mempersempit **seluruh** laporan sekaligus: KPI, kelima
chart, dan tabelnya berangkat dari satu `ManpowerSummary` yang dirakit
sekali per request dan disimpan di context. Itu bukan sekadar
penghematan query — tiga penghitung yang membangun querysetnya
masing-masing adalah cara paling pasti membuat KPI dan tabel di satu
layar menyebut angka yang berbeda setelah salah satu filternya diubah
dan yang lain lupa diikutkan.

### Sumber data

Satu query untuk seluruh populasi, lewat `values_list` — bukan instance
model. Kolom yang dibaca:

| Kolom laporan | Sumber |
| --- | --- |
| company / location / department | `OrganizationAssignment` |
| Employee Group | `EmploymentAssignment.employee_group` |
| Employment Type + Permanent/Contract | `EmploymentAssignment.employment_type` (+ `requires_contract`) |
| headcount | `Employee` (`is_active=True`, `is_deleted=False`) |

Section, Branch, dan Employment Status ikut sebagai **filter** saja —
ketiganya menyaring populasi tapi tidak menjadi kolom maupun sumbu
chart.

### Invariant yang dijaga test

`apps/reports/tests/hr/test_manpower_summary.py` — 53 test.

- Total Headcount = jumlah pegawai populasi; pegawai nonaktif dan
  ter-soft-delete tidak dihitung
- kelima breakdown (company, location, department, Employee Group,
  Employment Type) benar angkanya, dan **totalnya sama dengan KPI**
- grouping tabel benar (company → location → department), urutannya
  menurut kode, dan `Headcount = Permanent + Contract + Belum
  Ditentukan` per baris maupun di baris Total
- tabelnya **bukan daftar pegawai**: sepuluh pegawai → lima baris, dan
  tidak satu pun kolom identitas pegawai ikut
- `id` baris dirakit dari **kode** organisasinya, jadi dua department
  bernama sama di company berbeda tetap dua baris ber-`id` berbeda
- filter Company, Location, Department, Section, Employee Group,
  Employment Type, dan Employment Status mempersempit **seluruh**
  laporan secara konsisten (satu helper memeriksa KPI + 5 chart + tabel
  sekaligus)
- **cakupan tidak bisa diperluas lewat query param** — id di luar
  cakupan mengembalikan nol, disebut sendiri maupun bersama id yang
  memang dicakup
- **group ber-applicability OFF tetap dihitung**, dan mengubah flag
  applicability tidak menggeser headcount satu pun
- **tidak ada kode Employee Group yang di-hardcode** — test memindai
  sumber modulnya
- jenis kepegawaian berkontrak yang **namanya bukan "Contract"** tetap
  masuk kolom Contract
- satu query untuk seluruh populasi, dan dihitung sekali per request
- schema tidak punya filter periode, `get_period()` mengembalikan `{}`,
  seluruh widget punya resolver, dan tidak ada method tulis

```bash
python manage.py test apps.reports.tests.hr.test_manpower_summary --keepdb
python manage.py test apps.reports.tests.hr.test_manpower_movement --keepdb
python manage.py test apps.hr.tests.movement --keepdb   # penjagaan penempatan
```

### Known limitation / NEXT

- **Headcount as-of tanggal tertentu** belum ada. Laporan ini snapshot
  hari ini; historical/as-of butuh riwayat penempatan, bukan master hari
  ini. Task terpisah.
- **Tidak ada tren headcount** (grafik per bulan) — konsekuensi
  langsung dari poin di atas.
- **Employee Movement dan Turnover** adalah laporan tersendiri, bukan
  tambahan di sini. **Contract Expiry sudah selesai** — lihat bagiannya
  sendiri di bawah; pertanyaannya memang berbeda ("siapa yang habis
  kontraknya", bukan "berapa orang yang berkontrak").
- Breakdown per **Section**, **Position**, **Job Level**, dan
  **gender/usia** belum ada; ketiganya tersedia di master kalau nanti
  diminta.

## Contract Expiry

Laporan **manajemen** atas masa kontrak. Yang dijawabnya satu
pertanyaan: *"kontrak siapa yang akan atau sudah habis, dan mana yang
harus segera ditindaklanjuti"*.

Bedanya dengan tiga tempat lain yang menyentuh tanggal kontrak, dan
bedanya bukan tampilannya:

| | Isi | Satu baris = | Punya tulis? |
| --- | --- | --- | --- |
| **Employee Master** (`apps/hr/api/employee`) | input & perawatan masa kontrak | satu pegawai | ya |
| **Employee Action** (`apps/hr/api/employee_action`) | dokumen yang **mengubah** kontrak (extension/change) | satu dokumen | ya |
| **Reminder dashboard HR** (`apps/hr/api/dashboard/reminders.py`) | tanggal yang **sudah dekat**, ambangnya `EmployeeReminderPolicy.contract_lead_days` | satu tanggal | tidak |
| **Contract Expiry** | seluruh kontrak berjalan, dipecah per bucket | satu **kontrak berjalan** | tidak |

Reminder dan laporan ini memang membaca kolom yang sama dan memakai
rumus sisa hari yang sama, dan itu bukan duplikasi yang perlu
disatukan: reminder adalah **tagihan harian** yang ambangnya diatur per
tenant dan hanya memperlihatkan yang sudah dekat, laporan ini adalah
**potret utuh** yang memperlihatkan juga yang masih jauh — termasuk
kontrak yang tidak akan pernah muncul di reminder karena masih setahun
lagi, dan itu justru yang dipakai merencanakan anggaran.

- `GET /api/reports/hr/contract-expiry/` — seluruh widget sekaligus
- `GET /api/reports/hr/contract-expiry/?widget=contract_table&page=2&search=...`
  — satu widget saja; ini yang dipakai tabel saat berpindah halaman,
  supaya lima KPI dan dua chart tidak dihitung ulang untuk jawaban yang
  sama persis
- `GET /api/reports/hr/contract-expiry/ui-schema/` — schema untuk
  generator FE
- `GET /api/reports/hr/contract-expiry/expiry-status/` dan
  `.../renewal-status/` — isi dua dropdown yang **tidak punya tabel
  master**; bentuk responsnya `{count, next, previous, results}` sama
  dengan `BaseLookupView`

Tidak ada drill-down dan **tidak ada endpoint tulis**. Kontrak
diperpanjang lewat dokumen Employee Action, bukan dari laporan yang
melaporkannya.

### Sumber kebenaran: tidak ada model baru

Tidak satu pun model kontrak atau workflow renewal dibuat untuk laporan
ini. Semua dibaca dari yang sudah ada:

| Yang dibaca | Dari mana | Kenapa itu yang benar |
| --- | --- | --- |
| kontrak yang **berlaku** | `EmploymentAssignment.contract_type / contract_start / contract_end` | baris **keadaan sekarang**, satu per pegawai |
| siapa yang **berkontrak** | `EmploymentType.requires_contract` | penanda master yang sama yang dipakai `EmploymentAssignment.clean()` |
| **riwayat** kontrak | `EmployeeAction` yang `APPLIED` | dibaca layar Employment History — **tidak** dibaca laporan ini |
| **perpanjangan berjalan** | `EmployeeAction` bertipe `CONTRACT_EXTENSION`/`CONTRACT_CHANGE` berstatus `ACTION_OPEN_STATUSES` | satu-satunya sumber kolom Renewal Status |
| organisasi & atasan | `OrganizationAssignment` (`reports_to` apa adanya) | hubungan yang benar-benar tersimpan, bukan diturunkan dari jabatan |

**Tidak ada "memilih record kontrak yang authoritative" di laporan
ini**, dan itu konsekuensi desain yang sudah ditetapkan, bukan
penyederhanaan: kontrak berjalan seorang pegawai hanya ada **satu**,
letaknya di `EmploymentAssignment`, dan `clean()`-nya sudah menegakkan
artinya — jenis kepegawaian yang tidak berkontrak **tidak boleh**
membawa masa kontrak sama sekali. Kontrak lama pindah ke riwayat
Employee Action saat dokumen perubahannya diterapkan (lihat migration
`hr/0031_backfill_legacy_contract_history`), bukan menumpuk sebagai
beberapa baris kontrak yang harus dipilih salah satunya.

### Populasi

```
Population = Authorized Organization Scope
           ∩ EmploymentType.requires_contract = True
           ∩ punya catatan kontrak (contract_start atau contract_end terisi)
           ∩ filter yang dipilih
```

`DataScopeService.filter(qs, EMPLOYEE_SCOPE, user)` dipanggil **paling
akhir** dan tidak bisa dilewati; petanya sama persis dengan HR Period
Summary, Employee Reporting Audit, Manpower Summary, dan
`EmployeeViewSet.data_scope`. Filter dropdown hanya mempersempit —
menyebut id company atau location di luar cakupan lewat query string
tidak menambah satu baris pun.

Keputusan populasi yang **eksplisit**, masing-masing dikunci test:

| Keadaan | Diperlakukan | Kenapa |
| --- | --- | --- |
| jenis kepegawaian berkontrak, kontrak terisi | **masuk** | inti laporan |
| jenis kepegawaian **tidak** berkontrak | tidak masuk | tidak punya masa kontrak; `clean()` melarangnya membawa tanggal |
| berkontrak menurut jenisnya, tapi kolom kontraknya **kosong sama sekali** | tidak masuk | kelengkapan master, bukan masa kontrak yang akan habis — NEXT |
| kontrak **tanpa Contract End** | **masuk**, status `Tanpa Tanggal Akhir` | `clean()` melarangnya, tapi seed/importer massal menulis lewat `save()`; menyembunyikannya berarti satu-satunya layar yang bisa menemukannya justru yang menutupinya |
| `is_active=False` (resign/terminate) | tidak masuk | kontrak orang yang sudah keluar bukan pekerjaan yang tertunda; aturan yang sama dengan Manpower Summary dan Employee Reporting Audit |
| `is_deleted=True` | tidak masuk | soft delete |

Nama dan kode jenis kepegawaian **tidak pernah dibaca**. Ada test yang
memindai sumber modul untuk memastikan tidak ada `"PKWT"`, `"CONT"`,
`"PERM"`, `"Permanent"`, dan seterusnya — tenant yang menamai jenisnya
sendiri ("Kontrak Proyek", "Harian Lepas") tetap masuk laporan.

### Feature Applicability **tidak** menyaring

Contract Expiry adalah laporan **kepegawaian**, bukan laporan proses
Attendance/Leave/Roster. Aturan yang sama dengan Manpower Summary dan
Employee Reporting Audit, dan alasannya di sini paling langsung:
direksi yang seluruh proses HR-nya dimatikan tetap orang yang
kontraknya bisa habis — dan kontrak itu justru yang paling mahal kalau
terlewat.

Tidak ada Feature Applicability yang secara domain memengaruhi masa
kontrak; enam flag pada `EmployeeGroup` semuanya proses harian
(attendance, roster, shift, field break, leave, overtime). Karena itu
resolver applicability **tidak dipanggil sama sekali** di modul ini, dan
ada test yang memindai sumbernya untuk memastikannya.

### As Of: hari ini, tanpa pemilih

Tanggal acuannya `timezone.localdate()` saat request dilayani. Tidak ada
pemilih periode dan **tidak ada pemilih tanggal**.

Bukan karena As Of Date yang bisa dipilih tidak berguna, melainkan
karena runtime dashboard hari ini hanya melayani dua bentuk filter:
pemilih periode dan dropdown lookup (`MDashboardFilters.vue` di repo
Nuxt). Pemilih tanggal berarti runtime frontend baru; memakai pemilih
periode **bulan** untuk laporan yang butuh satu tanggal berarti kotak
yang terbaca seperti konfigurasi hidup padahal tidak menggeser satu
angka pun. Ditegakkan sama seperti dua laporan snapshot lainnya: schema
tidak mendeklarasikan filter bertipe `period`, dan `get_period()`
di-override mengembalikan `{}`.

`ContractExpiryService.as_of(context)` menghormati `context["as_of"]`
kalau isinya objek `date` — seam untuk test dan pemanggil internal.
Itu **bukan** jalan masuk dari query string: `BaseDashboardAPIView.
get_context()` hanya menyalin kunci yang dideklarasikan sebagai filter
di schema, dan `as_of` sengaja tidak ada di sana. Ada test yang mengirim
`?as_of=2020-01-01` dan memastikan laporannya tidak bergeser.

### Days Remaining dan bucket

```
days_remaining = contract_end - as_of
```

Rumus yang sama persis dengan reminder dashboard HR
(`apps/hr/api/dashboard/reminders.py`), jadi kedua layar tidak bisa
berbeda pendapat soal "tinggal berapa hari".

| Days Remaining | Kode | Label UI |
| --- | --- | --- |
| < 0 | `expired` | Expired |
| 0 – 30 | `expiring_30` | ≤ 30 Hari |
| 31 – 60 | `expiring_60` | 31–60 Hari |
| 61 – 90 | `expiring_90` | 61–90 Hari |
| > 90 | `future` | > 90 Hari |
| tidak ada Contract End | `no_end_date` | Tanpa Tanggal Akhir |

Batasnya **inklusif di atas**: 30 masih `≤ 30 Hari`, 31 sudah `31–60`.
`0` berarti kontrak habis **hari ini** — dan itu sengaja dibedakan dari
`None`, yang berarti tanggal akhirnya tidak ada sama sekali. Ambangnya
ditulis **sekali** di `statuses.py` dan dipakai KPI, dua chart, tabel,
maupun filter; boundary 30/31, 60/61, dan 90/91 dikunci test, termasuk
lewat pemeriksaan langsung ke fungsinya.

**Status derived tidak disimpan ke database.** Ia berubah sendiri tiap
hari, dan angka yang disimpan mulai salah pada hari pertama sesudah
ditulis tanpa satu pun proses yang berbunyi — masalah yang sama dengan
masa kerja di Employee Reporting Audit, diselesaikan dengan cara yang
sama.

### Renewal Status

Dibacakan dari dokumen `EmployeeAction` yang **masih berjalan**, bukan
disimpulkan dari tanggal:

| Status dokumen | Renewal Status |
| --- | --- |
| `DRAFT` | Draft |
| `SUBMITTED` | Pending Approval |
| `APPROVED` | Approved |
| `APPLIED`, `REJECTED`, `CANCELLED` | No Renewal Record |
| tidak ada dokumen kontrak sama sekali | No Renewal Record |

Jenis yang dibaca: `CONTRACT_EXTENSION` dan `CONTRACT_CHANGE`. Kalau
seorang pegawai punya lebih dari satu dokumen terbuka (kedua jenis itu
boleh berdiri bersamaan), yang ditampilkan yang **tanggal berlakunya
paling akhir**.

**Tidak ada nilai "Renewed"**, dan itu keputusan, bukan kekurangan.
Dokumen yang sudah `APPLIED` berarti kolom kontrak pegawainya sudah
ikut berpindah — barisnya sendiri sudah berada di bucket yang lebih
jauh. Menyebutnya "sudah diperpanjang" di baris yang justru masih
mendesak adalah memberi tahu HR bahwa pekerjaan yang belum selesai
sudah selesai.

Kolom `Renewal Doc` membawa nomor dokumennya supaya yang membacanya
bisa langsung mencarinya di layar Employee Actions.

### KPI, chart, dan tabel

**Lima kartu KPI**, `trend=False` semuanya (tidak ada periode
pembanding): `Expired`, `≤ 30 Hari`, `31–60 Hari`, `61–90 Hari`, dan
`Total Kontrak Aktif`.

Invariant yang dijaga test:

```
Expired + ≤30 + 31–60 + 61–90 + >90 + Tanpa Tanggal Akhir
    = Total Kontrak Aktif
    = jumlah baris tabel (sebelum paginasi)
    = jumlah seluruh batang Contract Expiry Timeline
```

Kartu kelima ada karena empat angka pertama berdiri tanpa penyebut
kalau ia tidak ada: "Expired 2" berarti sangat berbeda di tenant
berkontrak 5 orang dan di tenant berkontrak 500.

**Dua chart, dan sengaja cuma dua.** Company, Location, dan Employment
Type sudah berdiri sebagai filter dan sebagai kolom tabel; menambahkan
chart untuk masing-masingnya menghasilkan layar yang harus digulir
sebelum sampai ke tabel yang justru berisi daftar orang yang harus
dihubungi.

1. **Contract Expiry Timeline** (bar **tegak**, `horizontal=False`,
   span 8) — jumlah kontrak yang berakhir per bulan, dua belas bulan ke
   depan dari bulan tanggal acuan. Sumbu X bulan, sumbu Y jumlah
   kontrak. Dua belas bulan **selalu** terkirim, termasuk bulan yang
   berisi nol: batang yang hilang dan bulan yang memang kosong terbaca
   sama, dan yang pertama membuat jaraknya salah baca.

   Tegak, bukan mendatar, dan itu satu-satunya bar chart di sini yang
   memang begitu: kategorinya **waktu**, dan waktu yang berjalan ke
   kanan dibaca lebih cepat daripada yang berjalan ke bawah. Preseden
   yang sama di HR Period Summary (`attendance_trend`,
   `overtime_trend`).

   Tiga ember tambahan yang **hanya muncul kalau ada isinya**:
   `Sudah Lewat` (berakhir sebelum bulan berjalan), `> 12 Bulan`, dan
   `Tanpa Tanggal Akhir`. Ada supaya seluruh batang tetap menjumlah ke
   Total Kontrak Aktif — chart yang memotong ekornya diam-diam terbaca
   sebagai chart yang lengkap. Alasan itu **tidak** lagi tercetak di
   keterangan chart (bunyinya sekarang satu kalimat, "Kontrak yang
   berakhir dalam 12 bulan ke depan."): penjelasan rekonsiliasi adalah
   yang dicari saat mengaudit angkanya, bukan saat membacanya sekilas,
   dan tempatnya di dokumen ini.
2. **Expiring by Department** (**donut**, span 4) — kontrak yang
   **perlu ditindaklanjuti** (Expired sampai 90 hari) per Department,
   terbanyak dulu, delapan teratas + `Lainnya`.

   Donut karena yang dibawanya **komposisi**: berapa bagian dari beban
   tindak lanjut yang dipegang tiap department. Angka di tengahnya
   total yang perlu ditindaklanjuti — bukan Total Kontrak Aktif, dan
   memang **harus** berbeda. Perlu diketahui saat membacanya: donut
   memang lebih lemah daripada batang untuk membandingkan dua nilai
   yang berdekatan; kalau suatu saat yang dicari "siapa yang paling
   banyak", batang mendatar lebih tepat, dan itu satu baris di
   `schema.py`.

   Populasinya **bagian** dari populasi laporan, bukan populasi lain:
   filter dan cakupan yang sama sudah menyaringnya, yang berbeda cuma
   potongan bucket-nya — dan itu ditulis di keterangan chart supaya
   tidak ada yang menyangka chart dan KPI berangkat dari tempat
   berbeda.

   **Payload-nya tidak ikut berubah saat bentuknya berganti.** Resolver
   ini tetap mengirim `categories` + `datasets` (satu deret berwarna
   `warning`) seperti waktu ia masih batang — yang menyesuaikan
   frontend, yang memang tahu dua bentuk data. Ekor di luar delapan
   besar tetap dilipat ke `Lainnya` di sini, dan sekarang ada
   test-nya: sembilan potongan adalah batas atas, dan itu yang
   menentukan panjang palet kategori di frontend.

**Tabel: daftar orang, bukan agregat.** Bedanya dengan tabel Manpower
Summary bukan selera — yang dicari pembaca laporan ini adalah nama yang
harus dihubungi minggu ini, dan agregat per department justru
menghapusnya. Agregatnya sudah ada, dua chart di atasnya.

Kolomnya: Employee ID, Employee Name, Company, Location, Department,
Section, Position, Employee Group, Employment Type, Employment Status,
Contract Type, Contract Start, Contract End, Days Remaining, Expiry
Status, Renewal Status, Renewal Doc, Report To. `sticky_columns=2`, jadi
nomor dan nama pegawai ikut terkunci saat tabel digeser ke kanan.

Urutan bawaan **yang paling mendesak lebih dulu** — Expired → yang
terdekat → yang masih jauh, dan kontrak tanpa tanggal akhir paling
akhir. Ditegakkan service, bukan frontend: tabel yang harus diurutkan
sendiri oleh pembacanya sebelum berguna adalah tabel yang sebagian
pembacanya tidak pernah urutkan.

`Days Remaining` untuk kontrak tanpa tanggal akhir dikirim sebagai
**string kosong, bukan 0**: nol berarti habis hari ini, dan kolom angka
yang menuliskan nol untuk "tidak diketahui" mengarang jawaban paling
mendesak dari data yang tidak ada.

### Filter dan kotak cari

| Filter | Placement | Sumber |
| --- | --- | --- |
| Company (multi) | quick | organization lookup |
| Location (multi, + "Lokasi Saya") | quick | organization lookup |
| Department (multi) | quick | organization lookup |
| Branch | advanced | organization lookup |
| Section (multi) | advanced | organization lookup |
| Employee Group (multi) | advanced | HR reference lookup |
| Employment Type (multi) | advanced | HR reference lookup |
| Employment Status (multi) | advanced | HR reference lookup |
| Expiry Status | advanced | endpoint laporan ini |
| Renewal Status | advanced | endpoint laporan ini |

Kunci dan endpoint organisasinya sama persis dengan tiga laporan HR
lainnya, jadi `expand_filter_values` (BOD Location) dan
`DataScopeService` berlaku otomatis dan satu tombol Location tidak
berperilaku berbeda di empat layar.

Dua filter terakhir menunjuk endpoint milik laporan ini sendiri karena
keduanya **tidak punya tabel master**: Expiry Status dihitung dari
tanggal, Renewal Status dibacakan dari status dokumen. Membuatkan tabel
referensi untuk nilai yang ditentukan kode berarti master yang bisa
disunting sampai tidak lagi cocok dengan yang dibaca laporannya. Id-nya
**angka** — `MLookupSelect` meng-`Number()` nilai filter satu-pilihan,
jadi id berupa teks mendarat sebagai `null` dan dropdown-nya terlihat
kosong padahal isinya terkirim (pola yang sama dengan `reporting_status`
di Employee Reporting Audit).

Keduanya **derived**, jadi disaring di Python sesudah barisnya jadi dan
**sebelum** hasil laporan dibentuk — dengan begitu KPI, chart, dan tabel
tetap berangkat dari daftar yang sama persis. Menyaringnya di tabel saja
menghasilkan layar yang kartunya menyebut 12 dan tabelnya berisi 3,
tanpa satu pun keterangan bahwa keduanya menghitung hal yang berbeda.

Kotak cari mencocokkan **nomor dan nama pegawai**, dan cuma itu. Ia
tidak menggeser KPI maupun chart — aturan `TablePage` yang berlaku untuk
seluruh laporan.

### Invariant yang dijaga test

`apps/reports/tests/hr/test_contract_expiry.py`:

- populasi ditentukan `requires_contract`, bukan nama/kode jenis
  kepegawaian (panggung memakai "Kontrak Proyek" dan "Harian Lepas"),
  plus pemindaian sumber modul terhadap literal `"PKWT"`, `"CONT"`,
  `"PERM"`, `"Permanent"`, `"BOARD"`, …
- pegawai tetap, pegawai nonaktif, pegawai terhapus, dan jenis
  berkontrak **tanpa catatan kontrak** tidak masuk
- kontrak tanpa Contract End masuk, dengan `days_remaining=None` dan
  status `Tanpa Tanggal Akhir`
- boundary −1/0/30/31/60/61/90/91 dan `None`, lewat panggung **dan**
  lewat fungsi ambangnya langsung
- as-of = hari ini; `?as_of=` tidak pernah masuk context; `get_period()`
  mengembalikan `{}`; tidak ada filter `period` di schema
- Renewal Status: draft / submitted / approved terbaca; `APPLIED` dan
  `REJECTED` **bukan** renewal berjalan; `CONTRACT_CHANGE` ikut dibaca
- Organization Scope diterapkan, dan query param (company/location di
  luar cakupan) tidak bisa memperluasnya
- filter company/location/department/section/employee group/employment
  type/employment status/expiry status/renewal status
- kotak cari nomor & nama; kotak cari tidak menggeser total maupun
  `totals`
- KPI = chart = tabel: seluruh bucket menjumlah ke Total Kontrak Aktif,
  jumlah batang timeline = Total, chart department = jumlah bucket yang
  perlu ditindaklanjuti
- Feature Applicability tidak menyaring; mengubah flag group tidak
  menggeser satu baris pun; resolver applicability tidak dipanggil
- read-only: tidak ada `post`/`put`/`patch`/`delete` di view, tidak ada
  `ServiceWriteMixin`, dan tidak ada satu pun `.save(`/`.create(`/
  `.update(`/`.delete(` di service
- populasi dirakit **sekali per request** (dua query: pegawai + dokumen
  renewal)

### Demo / UAT

Cast peragaan (`apps/hr/seeds/demo_employees.py`) punya lima pegawai
berkontrak yang sengaja menempati **lima bucket berbeda**: Expired
(−6 hari), ≤30 (+9), 31–60 (+40), 61–90 (+75), dan >90 (+300).

Tapi `demo_employees.TODAY` **dipatok** (`date(2026, 8, 9)`) — sengaja,
karena masa kerja menentukan jatah cuti dan data uji yang jawabannya
berubah tiap hari tidak bisa dipakai membandingkan apa pun. Laporan ini
menghitung dari **hari ini**, jadi keduanya menjauh satu hari tiap hari:
sebulan sesudah seed dijalankan, kontrak yang mestinya memperagakan
"≤ 30 Hari" sudah pindah ke "Expired" dan dua kartu KPI berdiri kosong
di layar yang justru sedang diuji.

Karena itu ada satu perintah idempotent yang menjangkarkan ulang:

```bash
tenant_command seed_contract_expiry_demo --schema=demo
```

Yang dikerjakannya (`apps/hr/seeds/demo_contract_expiry.py`):

1. menyetel `contract_end` kelima pegawai itu ke `hari ini + offset`,
   dengan offset dibaca dari `demo_employees.PEOPLE` — satu sumber,
   bukan daftar nomor pegawai kedua yang harus dijaga tetap sama;
2. menerbitkan **satu** dokumen Contract Extension yang masih berjalan
   untuk kontrak terdekat, lewat `EmployeeActionService` (jalur yang
   sama dengan pengguna), supaya kolom Renewal Status punya nilai selain
   "No Renewal Record".

Yang **tidak** disentuhnya: join date, jatah cuti, presensi, roster, dan
pegawai yang kontraknya sudah pernah diubah dokumen Employee Action yang
`APPLIED` — menimpa tanggal hasil dokumen yang sudah diterapkan membuat
riwayat pegawainya berbohong tentang keadaannya sendiri.

Berkas ini **tidak mengimpor apa pun dari `apps.reports`** (arah
ketergantungan `reports → hr`, tidak pernah sebaliknya), jadi ia tidak
menyebut satu pun nama bucket — yang memutuskan bucket adalah
laporannya.

### Known limitation / NEXT

- **As Of Date yang bisa dipilih** belum ada; laporan ini selalu potret
  hari ini. Butuh tipe filter tanggal baru di runtime dashboard
  frontend, bukan sekadar parameter backend.
- **Contract completeness** — pegawai yang jenis kepegawaiannya menuntut
  kontrak tapi kolom kontraknya kosong sama sekali **tidak** muncul di
  laporan ini. Itu temuan kelengkapan master dan tempatnya bersama
  Employee Reporting Audit, bukan di laporan masa kontrak.
- **Renewal Status hanya melihat dokumen yang masih berjalan.** Riwayat
  "sudah berapa kali diperpanjang" ada di `EmployeeAction` yang `APPLIED`
  dan belum ditampilkan; kalau nanti diminta, sumbernya sudah ada.
- **Probation Expiry** adalah laporan tetangga yang belum ada. Kolomnya
  (`probation_start`/`probation_end`) sudah tersimpan dan reminder-nya
  sudah jalan; laporannya belum.
- Tidak ada notifikasi/eskalasi dari laporan ini — itu tugas
  `send_employee_reminders` + `EmployeeReminderPolicy`, dan sengaja
  tidak diduplikasi.

## Manpower Movement

`apps/reports/api/hr/manpower_movement/` —
`GET /api/reports/hr/manpower-movement/` (+ `ui-schema/`), read-only.

Laporan **manajemen** atas perubahan tenaga kerja dalam satu periode.
Bentuknya bukan daftar dan bukan potret, melainkan satu persamaan yang
harus tertutup:

```
Opening Headcount + Join + Transfer In − Transfer Out − Exit
    = Closing Headcount
```

Bedanya dengan **Manpower Summary** bukan tampilannya: Summary adalah
potret **hari ini** dan memakai `is_active`; laporan ini adalah
**selisih antara dua tanggal** dan sama sekali tidak membaca
`is_active`. Orang yang keluar bulan lalu tetap harus terhitung di
Opening bulan lalu — kalau tidak, Opening berubah surut tiap ada yang
resign, dan laporan Januari yang dibuka bulan Juni menunjukkan angka
berbeda dari yang dicetak bulan Februari.

### Audit sumber kebenaran — apa yang ada dan apa yang tidak

Laporan ini didahului audit, dan hasilnya yang menentukan bentuknya.
Empat temuan, dan semuanya masih berlaku:

1. **Tidak ada riwayat penempatan organisasi sama sekali.**
   `OrganizationAssignment` menyimpan keadaan sekarang, satu baris per
   pegawai. Tidak ada tabel yang menyimpan "dulu di mana".
2. **`EmployeeMovement` di `apps/hr/models/employee_history.py` adalah
   kode mati, dan bentuknya menyesatkan.** Ia punya persis kolom yang
   laporan ini butuhkan (`movement_type`, `from_company`/`to_company`,
   `effective_date`) tapi modulnya **tidak pernah diimpor**
   `models/__init__.py`, tidak punya migrasi, dan tabelnya tidak ada.
   Jangan dijadikan titik mulai; ia terbaca seperti solusi yang sudah
   jadi.
3. **Join dan Exit memang bisa direkonstruksi**, dan cuma dari tanggal:
   `EmploymentAssignment.join_date` dan `termination_date`.
4. **Transfer dulu tidak meninggalkan jejak apa pun.**
   `OrganizationService` tidak punya padanan `PROTECTED_FIELDS` milik
   `EmploymentService`, jadi satu PATCH ke form Employee memindahkan
   orang antarperusahaan tanpa dokumen, tanpa persetujuan, dan tanpa
   audit trail — `EmployeeService` bukan turunan `BaseService`, jadi
   `_audit()` tidak pernah menulis untuk jalur itu. **Sudah ditutup**;
   lihat bagian berikutnya.

### Penjagaan penempatan (`OrganizationService.PROTECTED_FIELDS`)

Sembilan kolom penempatan tidak bisa lagi diubah langsung dari form
Employee begitu pegawainya ada: `company`, `branch`, `location`,
`division`, `department`, `section`, `position`, `job_level`,
`job_grade`. Jalurnya `EmployeeAction`, dan pesan penolakannya menyebut
**jenis action mana** yang menerbitkannya.

Pola dan alasannya sama persis dengan `EmploymentService.PROTECTED_FIELDS`
di sebelahnya, termasuk cara memeriksanya: **dibandingkan**, bukan
dilihat kunci mana yang dikirim. Form mengirim seluruh isi tab apa
adanya, jadi menolak setiap kiriman yang memuat kuncinya akan membuat
menyimpan Organization Notes pun ditolak dengan alasan mutasi.

Saat **create** kolom-kolom itu bebas diisi — penempatan awal, belum ada
sejarah yang bisa hilang. `via_action=True` melewati penjagaannya.

Yang sengaja **tidak** dikunci, dan alasannya:

| Kolom | Kenapa tidak dikunci |
| --- | --- |
| `reports_to` | Garis pelaporan adalah koreksi data, bukan mutasi. Employee Reporting Audit ada justru untuk memunculkan yang kosong supaya HR membetulkannya, dan satu atasan yang resign berarti seluruh bawahannya harus dialihkan |
| `cost_center` | Dimensi biaya, bukan penempatan orang. Tidak ada satu pun suku Manpower Movement yang membacanya |
| `organization_effective_date`, `organization_notes` | Keterangan atas penempatan, bukan penempatannya |

**Dua jalur masih bisa menembusnya, dan keduanya disengaja:**

- `EmployeeActionService._apply_organization()` menulis
  `OrganizationAssignment` **langsung**, bukan lewat service — ia butuh
  semantik "kolom yang tidak diusulkan jangan ikut dikosongkan". Itu
  jalur yang sudah membekukan `values_before` dan sudah lewat
  persetujuan.
- **Employee importer** (`apps/hr/imports/employee/writer.py`) juga
  menulis langsung. Memblokirnya akan mematahkan impor ulang, jadi
  dibiarkan — konsekuensinya mutasi yang masuk lewat impor tidak
  terbit sebagai Transfer In/Out. Tercatat sebagai NEXT.

### Konsekuensi yang harus dibaca sebagai bagian kontrak

**Transfer In/Out hanya terisi untuk periode sesudah penjagaan itu
berlaku.** Periode sebelumnya menampilkan 0, dan itu bukan "tidak ada
mutasi" melainkan "tidak ada yang mencatatnya". Laporan ini **tidak
menebak** mutasi lama dari master hari ini: angka yang direkonstruksi
dari master terbaca persis seperti angka yang benar, dan selisihnya
baru ketahuan bertahun-tahun kemudian.

### Definisi headcount — detik, bukan hari

`headcount_at(D)` mencacah pada **detik awal** tanggal `D`:

```
join_date < D          # tegas, bukan <=
termination_date >= D  # atau kosong
```

- **Opening** dibaca pada `start`
- **Closing** dibaca pada `end + 1 hari`

Kenapa tegas: orang yang bergabung tepat di hari pertama periode belum
ada saat periodenya dibuka — ia masuk lewat suku Join. Dengan `<=` ia
terhitung di Opening **dan** di Join, dan Closing meleset satu untuk
tiap orang yang bergabung di tanggal 1. Simetrisnya di ujung lain:
orang yang hari terakhir bekerjanya jatuh di akhir periode terhitung
Exit dan **tidak** ikut Closing.

`is_active` **tidak dibaca sama sekali**, dan itu menutup satu
kebocoran yang masih terbuka: `Employee.is_active` masih bisa dimatikan
langsung dari form tanpa mengisi `termination_date`. Kalau headcount
membacanya, orang itu hilang dari Closing tanpa pernah terbit sebagai
Exit — dan identitasnya pecah tanpa sebab yang terlihat di layar.

### Pemutaran mundur penempatan

Headcount lampau **tidak** boleh dinilai dari penempatan hari ini.
Kalau dinilai begitu, orang yang pindah keluar lokasi di tengah periode
hilang dari Opening lokasinya sendiri sementara Transfer Out tetap
mengurangi satu — identitasnya meleset persis sebanyak mutasi yang
terjadi.

`_rewind()` karena itu mengambil dokumen mutasi **paling awal sesudah**
tanggal yang dihitung; sisi lamanya **adalah** penempatan orang itu
saat itu. Yang tidak punya dokumen sesudahnya dinilai dari penempatan
sekarang.

Terbukti di tenant peragaan: Opening Sagea Mine Agustus 2026 = 19,
**termasuk** LOK006 yang hari ini sudah berada di Jakarta Head Office.

### Transfer In / Out / Internal Move

Sebuah dokumen jadi Transfer In kalau ujung barunya di dalam populasi
yang dilaporkan sementara ujung lamanya di luar, dan Transfer Out untuk
kebalikannya. Yang **kedua ujungnya di dalam** adalah Internal Move —
tetap terbit sebagai baris tabel, tapi tandanya **0**: mutasi yang
tidak melewati batas tidak mengubah jumlah kepala. Yang kedua ujungnya
di luar tidak terbit sama sekali.

Ditentukan dari batas yang dilewati, **bukan dari `action_type`**: yang
membedakan Transfer dari Promotion adalah alasan dan meja yang
menyetujuinya, bukan kolom yang ditulis — `EmployeeAction` sendiri
memakai satu handler untuk keempat jenis organisasi. Promosi yang
memindahkan orang ke perusahaan lain **adalah** Transfer Out bagi
perusahaan yang ditinggalkan.

Sumbernya `EmployeeAction` dengan `status=APPLIED` (bukan `APPROVED` —
dokumen yang alurnya selesai tapi penerapannya gagal belum mengubah
data pegawainya) dan `effective_date` di dalam periode (bukan
`applied_at` — mutasi yang disetujui 20 Agustus untuk berlaku 1
September adalah pergerakan bulan September).

**Dinilai pada batas company/branch/location saja.** Cuma tiga dimensi
itu yang dokumennya simpan sebagai id di **kedua** ujungnya
(`company_id` didenormalisasi saat dokumen dibuat, `proposed_company_id`
diisi usulannya). Department dan section hanya ada di sisi usulan; sisi
lamanya cuma ada sebagai **nama** di `values_before`, dan mencocokkan
riwayat lewat nama adalah cara laporan mulai berbohong begitu ada
master yang diganti nama.

### `variance` — selisih yang selalu diterbitkan

`variance = closing − expected_closing`, ikut di `totals` tabel. Nol
untuk seluruh keadaan yang dijaga test. Diterbitkan dan bukan
di-`assert`: laporan yang melempar 500 saat datanya ganjil tidak
menolong siapa pun, sedangkan angka yang diam-diam dibulatkan agar
cocok justru berbahaya.

### Tidak ada filter Movement Type, dan itu keputusan

Contract Expiry punya filter Expiry Status karena di sana seluruh KPI
lahir dari baris yang sama. Di sini tidak: Opening dan Closing dihitung
dari **tanggal**, bukan dari baris pergerakan. Filter yang menyisakan
Exit saja akan mengubah lima kartu dan membiarkan dua lainnya, dan
layarnya berhenti menjadi persamaan. Yang butuh melihat satu jenis
sudah terlayani kolom Movement di tabel + kotak cari.

### KPI, chart, dan tabel

Delapan kartu dalam dua baris. **Baris pertama adalah identitasnya,
dibaca kiri ke kanan**: Opening → Join → Transfer In → Transfer Out →
Exit → Closing, `span=2` masing-masing. Urutan itu juga urutan batang
chart jembatan; kartu yang disusun ulang menurut selera membuat
pembacanya kehilangan persamaannya.

Baris kedua: **Net Change** (`span=6`) dan **Tanpa Tanggal Bergabung**
(`span=6`). Yang kedua bukan KPI manajemen melainkan penjaga
rekonsiliasi — pegawai tanpa `join_date` tidak bisa ditempatkan di
periode mana pun jadi dikeluarkan, dan pengeluaran yang tidak terlihat
adalah cara paling mudah membuat dua layar berbeda angka tanpa ada yang
bisa menjelaskan sebabnya.

`trend=False` di semuanya: laporan ini **sudah** perbandingan antara
awal dan akhir periode; menempelkan "naik 12% dari bulan lalu" di bawah
angka yang artinya sendiri sudah selisih menghasilkan dua perbandingan
bertumpuk.

Dua chart:

- **Headcount Bridge** — bar **tegak** (`horizontal=False`, `span=7`),
  kategorinya persamaan yang dibaca kiri ke kanan. Transfer Out dan
  Exit digambar **negatif** supaya aritmetikanya terlihat; enam batang
  yang semuanya positif memaksa pembacanya mengingat mana yang
  dikurangkan. Aturan tegak-vs-mendatar sama dengan Contract Expiry
  Timeline: tegak untuk kategori yang punya urutan alami
- **Exit by Reason** — donut (`span=5`), delapan teratas + `Lainnya`.
  Angka tengahnya sama dengan KPI Exit, dan memang harus sama

Tabel: **satu baris per peristiwa, bukan per pegawai**, kronologis.
Orang yang bergabung lalu pindah dalam periode yang sama muncul dua
kali — itu memang yang harus terlihat, dan menggabungkannya per orang
justru menghapus salah satunya. Kronologis dan bukan terbaru-dulu:
tabel ini buku besar yang menjelaskan bagaimana Opening berubah jadi
Closing, dan buku besar yang dibaca mundur tidak menjelaskan apa-apa.

### Master yang ikut diperbaiki: `TerminationReason`

Ditemukan saat menyiapkan peragaan, dan **bukan cuma masalah
peragaan**: `TerminationReason` tidak pernah ikut di-seed di tenant mana
pun, sementara `EmploymentAssignment.clean()` mewajibkannya begitu
`termination_date` diisi dan `ACTION_FIELD_RULES` mewajibkannya untuk
dokumen Termination. Akibatnya **tidak ada tenant yang bisa mencatat
satu pun kepergian** — dokumennya lolos seluruh alur persetujuan lalu
gagal di detik penerapannya, berhenti di status `approved` dengan
`apply_error` terisi.

Sepuluh baris ditambahkan ke `apps/administration/seeds/reference/hr.py`
bersama `ContractType`/`ProbationType`: `RESIGN`, `CONTRACT_END`,
`RETIRE`, `MUTUAL`, `PERFORMANCE`, `MISCONDUCT`, `REDUNDANCY`,
`HEALTH`, `DECEASED`, `OTHER`.

### Invariant yang dijaga test

`apps/reports/tests/hr/test_manpower_movement.py`:

- `Opening + Join + In − Out − Exit = Closing` — tanpa filter, per
  lokasi, untuk akun bercakupan, dan pada periode tanpa pergerakan
- `variance == 0` di seluruh keadaan itu, dan kuncinya ada di `totals`
- Batas: bergabung di hari pertama **tidak** ikut Opening; bergabung di
  hari terakhir **ikut** Closing; hari terakhir bekerja di akhir periode
  **tidak** ikut Closing; masuk+keluar di periode yang sama = dua baris
  bertanda berlawanan
- Yang keluar tetap terhitung di Opening periodenya sendiri
- `is_active` tidak dibaca; tanpa `join_date` dikeluarkan **dan**
  dihitung; Feature Applicability tidak menyaring
- Cakupan tidak bisa dilebarkan lewat query param
- Mutasi: internal vs in vs out dari batas populasi; hanya `APPLIED`;
  `effective_date` bukan tanggal lain; jenis non-organisasi bukan
  mutasi; `ORGANIZATION_ACTION_TYPES` dikunci terhadap model
- Setiap jenis pergerakan punya label **dan** tanda — jenis tanpa tanda
  diam-diam dianggap 0
- Kunci payload tabel dibandingkan dengan kunci kolom schema — persis
  bug `ShiftCalendarDaySerializer` yang lolos seluruh test service
- Setiap widget schema punya `resolve_<key>()`; tidak ada method tulis

`apps/hr/tests/movement/test_placement_guard.py` menjaga penjagaan
penempatannya: perpindahan ditolak, penempatan tidak berubah saat
ditolak, pesan menyebut jenis action yang benar, yang bukan
perpindahan tetap boleh disimpan, penempatan awal bebas, dan
`via_action` melewatinya.

### Demo / UAT

```bash
python manage.py tenant_command seed_administration --only=hr-reference --schema=demo
python manage.py tenant_command seed_manpower_movement_demo --schema=demo
```

Idempoten. Menerbitkan empat peristiwa **lewat `EmployeeActionService`**
— jalur yang sama dengan pengguna, bukan baris yang disuntikkan
langsung — berlaku di **bulan berjalan**:

| Pegawai | Peristiwa | Berlaku |
| --- | --- | --- |
| LOK006 | Mutasi Sagea Mine → Jakarta Head Office | tgl 5 |
| HO007 | Mengundurkan diri | tgl 10 |
| HO008 | Mutasi Jakarta Head Office → Sagea Mine | tgl 15 |
| LOK005 | Kontrak berakhir, tidak diperpanjang | tgl 20 |

Angka Agustus 2026, akun `admin` (cakupan penuh):

```
30 + 0 + 0 − 0 − 2 = 28     internal_move 2, variance 0
```

Filter Location = Sagea Mine:

```
19 + 0 + 1 − 1 − 1 = 18     variance 0
```

Filter Location = Jakarta Head Office (MMR):

```
9 + 0 + 1 − 1 − 1 = 8       variance 0
```

Akun bercakupan sungguhan `demo.gmsite` (satu lokasi), tanpa filter
apa pun — cakupannya sendiri yang jadi batasnya:

```
Agustus 2026   19 + 0 + 1 − 1 − 1 = 18     variance 0
Tahun 2026     17 + 2 + 1 − 1 − 1 = 18     variance 0
```

Baris kedua itu yang memperagakan **kelima suku terisi sekaligus**;
untuk `admin` tahun 2026 angkanya `27 + 3 + 0 − 0 − 2 = 28`.

Dua mutasi yang sama terbaca **Internal Move** bagi admin dan
**Transfer In/Out** bagi pembaca yang cuma memegang satu lokasi. Itu
bukan ketidakkonsistenan — itu definisinya.

**Yang ikut berubah di tenant peragaan, dan memang tidak bisa tidak:**
dua pegawai jadi tidak aktif, jadi **Manpower Summary turun 30 → 28**,
dan penempatan LOK006/HO008 berpindah. Peragaan pergerakan yang tidak
menggerakkan apa pun tidak memperagakan apa pun.

**`join_date` sengaja tidak disentuh** — ia menentukan jatah cuti
seluruh data uji. Akibatnya kartu Join bernilai 0 pada tampilan bulan
berjalan; ganti periodenya ke **Year** dan ketiga join 2026 muncul
bersama kepergian dan mutasinya, identitas tetap tertutup.

### Known limitation / NEXT

- **Filter Department/Section/Employee Group/Employment Type/Status
  mempersempit Opening/Closing/Join/Exit tapi tidak ikut menentukan
  sebuah mutasi masuk atau keluar** — dokumennya tidak menyimpan sisi
  lama dimensi-dimensi itu sebagai id. Mutasi yang cuma memindahkan
  department karena itu terbaca Internal Move di semua tampilan
- **Penempatan baris Join dan Exit dibaca dari keadaan sekarang.**
  Kolom Company/Location/Department pada baris itu adalah penempatan
  **hari ini**, bukan saat peristiwanya. Untuk baris Transfer dua
  ujungnya justru diketahui — dokumennya menyimpan keduanya
- **`Employee.is_active` masih bisa dimatikan dari form tanpa
  `termination_date`.** Laporan ini kebal karena tidak membacanya, tapi
  Manpower Summary **membacanya**, jadi kedua layar bisa berbeda tanpa
  ada yang menjelaskan. Menguncinya adalah keputusan tersendiri:
  `is_active` adalah toggle `placement="quick"` di form Employee
- **Employee importer menembus penjagaan penempatan** (menulis
  `OrganizationAssignment` langsung), jadi mutasi lewat impor tidak
  terbit sebagai Transfer In/Out
- **Transfer In/Out kosong untuk periode sebelum penjagaan berlaku**,
  dan itu permanen — riwayatnya memang tidak pernah dicatat
- **Manpower Trend** (headcount antarbulan / as-of) belum dikerjakan.
  Sesudah laporan ini, riwayatnya **cukup untuk Join/Exit** tapi
  **belum cukup untuk komposisi organisasi lampau** kecuali untuk
  periode yang mutasinya sudah berdokumen
- Belum ada frontend; UAT browser belum dilakukan


## Menu, hub, dan beranda

- Katalog aplikasi beranda: `apps/administration/api/dashboard/catalog.py`
  (`reports`, status `ACTIVE`)
- Menu sidebar: `apps/accounts/seeds/menus.py`, modul `reports` —
  cerminan `moduleMenus.reports` di `app/constants/menus.ts` repo Nuxt.
  **Menambah item di sana berarti menambahnya di sini juga**, kalau tidak
  item itu tidak akan pernah bisa dibatasi per role
- Hub `/reports` di frontend: `app/registry/section-hub/reports.ts`

Isi grup `reports-hr` hari ini — **tiga tempat yang harus sama**
(seed menu di sini, `moduleMenus.reports` di Nuxt, kartu hub):

| Laporan | Rute |
| --- | --- |
| HR Period Summary | `/reports/hr/period-summary` |
| Employee Reporting Audit | `/reports/hr/employee-reporting-audit` |
| Manpower Summary | `/reports/hr/manpower-summary` |
| Contract Expiry | `/reports/hr/contract-expiry` |
| Manpower Movement | `/reports/hr/manpower-movement` |

Modul yang **baru ditambahkan** ke `APP_CATALOG` tetap sampai ke pengguna
lama: `FavoriteAppService.get_favorites` menyusulkan entri katalog yang
belum punya baris `FavoriteApp` sama sekali. Tanpa itu modul baru hanya
terlihat oleh akun yang belum pernah menekan Save di Customize — dan
`seed_dashboard` menekan Save untuk semua orang sekaligus.

## Test

```bash
python manage.py test apps.reports --keepdb
python manage.py test apps.framework --keepdb   # TablePage, tanpa database

# satu laporan saja
python manage.py test apps.reports.tests.hr.test_period_summary --keepdb
python manage.py test apps.reports.tests.hr.test_employee_reporting_audit --keepdb
python manage.py test apps.reports.tests.hr.test_manpower_summary --keepdb
python manage.py test apps.reports.tests.hr.test_manpower_movement --keepdb
python manage.py test apps.hr.tests.movement --keepdb   # penjagaan penempatan
```
