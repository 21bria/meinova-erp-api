# HR Management — Technical Reference

Lapisan teknis untuk developer dan auditor. Halaman bisnis di bagian ini sengaja tidak memuat nama berkas, nama model, atau nomor baris; semuanya dikumpulkan di sini.

---

## Model yang berwenang

| Konsep bisnis | Model | Tabel |
|---|---|---|
| Company / Branch / Work Location | `Company`, `Branch`, `Location` | `master_company`, `master_branch`, `master_location` |
| Division / Department / Section | `Division`, `Department`, `Section` | `master_division`, `master_department`, `master_section` |
| Position / Cost Center | `Position`, `CostCenter` | `master_position`, `master_cost_center` |
| Employee | `Employee` | `hr_employee` |
| Employment | `EmploymentAssignment` (1:1) | `hr_employee_employment` |
| Organization Assignment | `OrganizationAssignment` (1:1) | `hr_employee_organization` |
| Payroll Assignment | `PayrollAssignment` (1:N, effective-dated) | `hr_employee_payroll_assignment` |
| Work Calendar / Holiday | `WorkCalendar`, `Holiday`, `HolidayCompany` | `master_work_calendar`, `master_holiday` |
| Shift / Work Schedule | `Shift`, `ShiftGroup`, `WorkSchedule`, `WorkScheduleDay` | `master_shift`, `master_work_schedule` |
| Shift assignment | `EmployeeShiftAssignment` (layer × kind) | `hr_employee_shift_assignment` |
| Roster Policy | `RosterPolicy`, `RosterTravelDay`, `RosterShiftRotation` | `master_roster_policy` |
| Roster Setup | `RosterSetupRequest`, `RosterSetupLine` | `hr_roster_setup_request`, `hr_roster_setup_line` |
| Rencana & versi | `SiteRotation`, `RosterPlanVersion` | `hr_site_rotation`, `hr_roster_plan_version` |
| Segmen | `RotationPeriod` | `hr_rotation_period` |
| Penyesuaian | `RosterAdjustment` | `hr_roster_adjustment` |
| Kredit rotasi | `RotationCreditTransaction`, `RotationCreditBalance` | `hr_rotation_credit_*` |
| Attendance Policy | `AttendancePolicy` | `administration_attendancepolicy` |
| Jenis & kebijakan cuti | `LeaveType`, `LeavePolicy` | `master_leave_type`, `master_leave_policy` |
| Dokumen cuti | `EmployeeLeave` | `hr_employee_leave` |
| Kartu cuti | `LeaveBalance` | `hr_leave_balance` |
| Izin kehadiran | `AttendancePermission` | `hr_attendance_permission` |
| Perlakuan payroll atas izin | `PayrollPermissionRule` | `payroll_permission_rule` |
| Perlakuan payroll atas cuti | `PayrollLeaveRule` | `payroll_leave_rule` |
| Catatan lembur | `EmployeeOvertime` | `hr_employee_overtime` |
| Kelompok & tingkat lembur | `OvertimeGroup`, `OvertimeGroupTier` | `payroll_overtime_group*` |
| Feature applicability | `EmployeeGroup` + `HRFeature` | `master_employee_group` |
| Bukti tap mentah | `AttendanceLog` | `hr_attendance_log` |
| Presensi harian | `EmployeeAttendance` | `hr_employee_attendance` |
| Mesin & pemetaan nomor | `AttendanceDevice`, `AttendanceDeviceEmployee` | `hr_attendance_device*` |
| Profil import | `ImportProfile` (`module="hr/attendance"`) | `imports_importprofile` |

---

## Titik tunggal resolusi jadwal

Seluruh modul membaca jadwal lewat `apps/hr/api/attendance/schedule.py`. Tidak ada penghitung kedua.

| Fungsi | Menjawab |
|---|---|
| `is_roster(employee)` | pegawai roster atau kalender — menerima `roster_crew` **atau** `roster_policy` |
| `employment_bounds(employee)` | pagar join date / termination date |
| `planned_work_days()` / `scheduled_work_days()` | himpunan tanggal kerja |
| `resolve_shift()` | override → baseline → shift tetap → `WorkScheduleDay`; `kind=REST` menjawab `None` dan berhenti |
| `scheduled_window()` / `shift_span()` | jendela terjadwal, termasuk lintas tengah malam |
| `holidays_bulk()` | hari libur per pegawai |

`ShiftCalendarService` adalah **penyaji**, bukan penghitung kedua: seluruh jawabannya berasal dari fungsi di atas.

---

## Resolusi policy

Pola `specificity` dipakai `AttendancePolicy`, `LeavePolicy`, `RosterPolicy`, `EmployeeActionPolicy`, dan `WorkflowDefinition`.

```python
# AttendancePolicy.specificity
(4 if company_id else 0) + (2 if location_id else 0) + (1 if employee_group_id else 0)
```

Tidak ada tingkat pegawai. Company mengalahkan Location.

---

## Jalur tulis presensi

Empat jalur, dan tiap baris membawa asal-usulnya sendiri.

| Jalur | Service | `source` | `external_id` | `AttendanceLog` |
|---|---|---|---|---|
| Unggah file mesin | `ImportPipelineService.execute(module="hr/attendance")` → `AttendanceImporter.write()` → `AttendanceImportWriter.upsert()` | `import` | `DEV-ATT-…` pada data peragaan | **ya**, satu baris per tap |
| Rekap deterministik peragaan | `EmployeeAttendanceService.create()` | `device` | `SEED-ATT-…` | tidak |
| Penutupan hari | `AttendanceClosingService.close()` | `system` | `CLOSE-…` | tidak |
| Koreksi tangan / layar | `EmployeeAttendanceService.update()` | tidak berubah | tidak berubah | tidak |

`EmployeeAttendanceService` **selalu** menurunkan ulang angka lewat `apply_policy()` lalu `apply_permissions()`, dalam urutan itu. Nilai kiriman ditimpa — kalau tidak, layar mana pun yang mengirim `late_minutes` hasil hitungannya sendiri melewati kebijakan yang baru saja diatur orang.

`AttendanceImportWriter.upsert()` punya dua celah yang sudah terukur:

* **Tidak mengisi `EmployeeAttendance.shift`.** Barisnya membawa `scheduled_check_in`/`scheduled_check_out` yang benar tapi FK shift-nya kosong, jadi laporan yang mengelompokkan per shift kehilangan baris berasal-import. Pada data peragaan: 11 dari 1.167.
* **Tidak memanggil `apply_permissions()`.** Ia hanya menurunkan angka kebijakan, jadi baris berasal-import terbit tanpa `permission_state` — dan daftar pengecualian kehilangan justru baris yang paling menarik. Terukur persis: `recalculate_attendance --dry-run` atas jendela peragaan melaporkan **6 baris berubah**, keenamnya `source=import`.

Keduanya ditangani di tingkat **jalur data** — pipeline peragaan menjalankan `recalculate_attendance` sesudah seluruh baris terbit — bukan dengan mengubah writer-nya. Sesudah itu perintah yang sama melaporkan **0 baris berubah**, dan angka nol itu adalah bukti bahwa setiap angka tersimpan sepakat dengan mesin kebijakan yang berlaku.

Tanggal kerja sebuah tap ditentukan `apps/hr/imports/attendance/workdate.py` — mencoba tanggal lokal tap lalu sehari sebelumnya, memilih yang jendela jadwalnya memuat tap itu. Importer **tidak** punya definisi hari kerja sendiri.

---

## Cakupan penutupan hari

`AttendanceClosingService.close(..., employees=None)`.

| `employees` | Arti |
|---|---|
| `None` (bawaan) | seluruh pegawai yang lolos Feature Applicability, disaring `company`/`location` kalau disebut — perilaku sebelum parameter ini ada |
| daftar id atau instance | **menyempitkan** ke pegawai itu; penyaring `company`/`location` tetap berlaku, jadi cakupan tidak bisa dipakai melebar |
| daftar kosong | **tidak ada pegawai** — nol baris, berhenti sebelum query mana pun |

`close_attendance` mengekspos ini lewat `--employee` (nomor pegawai, boleh diulang) dan `--employee-prefix`. Nomor atau awalan yang tidak menjaring siapa pun **menghentikan** perintah: melaporkan "0 tidak hadir" untuk pegawai yang tidak pernah diperiksa adalah nol yang terbaca persis seperti nol yang benar.

Parameter ini **cakupan pekerjaan, bukan kelayakan**. Siapa yang punya kewajiban presensi tetap dijawab Feature Applicability, `employment_bounds()`, hari pemulihan, dan segmen roster.

Dikunci `apps/hr/tests/attendance/test_closing_scope.py` (17 test): cakupan terpilih diproses; yang tidak terpilih utuh; lini TRL tetap nol walau mesinnya menjadwalkan mereka; cakupan kosong bukan cakupan global; jalur tanpa cakupan tidak berubah; id kembar tidak menggandakan pekerjaan; cakupan tidak menembus `company`; dan tujuh test kelayakan — hari pemulihan, field break, travel out/in, sesudah berhenti, sebelum bergabung, dan Employee Group tanpa Attendance semuanya **tidak** jadi mangkir.

---

## Tiga dokumen penjelas — jalur dan batasnya

### Cuti

`EmployeeLeaveService` — `create` → `submit` → `WorkflowService.approve/reject` → `apply_workflow_status` → `set_status` → `sync_balance`.

`LeaveBalanceService.recalculate_used()` **menjumlahkan ulang dari dokumen**, bukan menambah/mengurangi inkremental. Itu yang membuat penolakan dan pembatalan mengembalikan saldo tanpa jalur pengembalian tersendiri. `LEAVE_DEDUCTING_STATUSES` = `RECORDED` + `APPROVED`.

Dua celah yang harus diperhatikan tiap keputusan alur diambil **di luar** viewset-nya:

* `WorkflowService.approve/reject` harus dioper `on_complete=completion_handler(module, document_type)`. Tanpa itu alurnya berpindah tapi status dokumennya **tidak** — dan gagalnya diam. `submit()` hanya mengopernya untuk penutupan otomatis saat alurnya kosong.
* `apply_workflow_status()` memetakan `InstanceStatus.CANCELLED → LeaveStatus.DRAFT`. Dokumen ber-status `CANCELLED` hanya lahir dari aksi `cancel` pada dokumen **RECORDED**; membatalkan instance alurnya bukan hal yang sama.

**Cuti tidak menyentuh `EmployeeAttendance`.** Tidak ada satu baris pun di `leave_completed` → `apply_workflow_status` → `set_status` yang menulis ke tabel presensi. Hari yang sudah punya baris tetap seperti adanya; `AttendanceClosingService` hanya menulis `leave` untuk hari yang **belum** punya baris (`_leave_days()` dibaca sebelum baris dibuat).

### Izin kehadiran

`AttendancePermissionService` — `create` → `submit` → `decide` → `on_workflow_done` → `AttendancePermissionEffectService.recalculate_for_permission()`.

Yang boleh ditulis hanya lima kolom: `excused_late_minutes`, `excused_early_leave_minutes`, `permission_minutes`, `is_excused_absence`, `permission_state`. Jam tap dan angka kebijakan tidak pernah disentuh.

`PERMISSION_EFFECTIVE_STATUSES` = `APPROVED` saja. `SUBMITTED`/`IN_REVIEW` dibaca resolver hanya untuk menghasilkan keadaan `pending`.

`assert_period_open()` menolak tanggal di dalam `PayrollPeriod` ber-status `FINALIZED`. Periode 2026-08 tenant peragaan berstatus `review`, jadi terbuka.

### Lembur

`EmployeeOvertimeService` adalah `BaseMasterService` biasa. **Tidak ada** `register_route`, `register_completion`, definisi alur, maupun aksi submit/approve pada viewset-nya. Nilai `SUBMITTED`/`APPROVED` pada `OvertimeStatus` tidak pernah ditulis jalur mana pun.

`PayrollSourceService._collect_overtime()` membaca `is_paid=True` **dan** status ∈ {`RECORDED`, `APPROVED`}, lalu `Sum("duration_minutes")` **per `work_date`** sebelum diubah ke jam — itu yang membuat dua catatan sehari jadi satu hari lembur.

Penyusunan tingkat ada di `PayrollCalculationService._spread_over_tiers()`, bukan di HR.

---

## Resolusi approver

`WorkflowDefinitionResolver.match()` memilih definisi lewat cakupan (`company`/`branch`/`location`/`employee_group`) dengan pemecah seri `specificity → version → pk`. Kolom kosong berarti berlaku untuk semua.

`resolve_approvers()` per step: `USER` → `MANAGER` (`OrganizationAssignment.reports_to`) → `POSITION` → `DEPARTMENT_HEAD` → `ROLE` (pemegang peran pada cakupan, **pengaju dikecualikan**) → `fallback_role`.

`_build_approvals()` menolak seluruh pengajuan kalau ada step **wajib** yang tidak menemukan approver — dokumennya tidak bergerak dan tidak ada instance yang terbentuk. Dua keadaan yang memicunya di tenant peragaan:

| Keadaan | Contoh |
|---|---|
| Pengaju berada di **puncak garis pelaporan** | `reports_to` kosong → step `MANAGER` gagal |
| Pengaju adalah **satu-satunya pemegang** peran suatu step | pemegang KTT di Sagea Mine gagal di step KTT |

Keduanya **kekurangan konfigurasi**, bukan cacat mesin: `WorkflowStep.fallback_role` tersedia dan belum diisi.

Orang yang sama pada dua step satu dokumen ditandai `SKIPPED` dengan alasan "sudah terwakili" — satu tanda tangan, bukan dua.

---

## Perintah operasional

| Perintah | Guna | Kering secara bawaan |
|---|---|---|
| `seed_hr_demo --anchor ... --dry-run / --apply` | perencana + pelaksana fondasi peragaan | ya — tanpa flag mode, menolak jalan |
| `seed_demo_roster --as-of ... --only-roster-employees` | membangun roster site lewat dokumen setup | tidak |
| `recalculate_attendance --start ... --until ...` | menerapkan ulang policy ke rentang tanggal | punya `--dry-run` |
| `close_attendance --until ... [--employee N] [--employee-prefix P]` | menerbitkan baris mangkir / cuti untuk hari terjadwal tanpa tap | punya `--dry-run` |
| `seed_hr_demo_attendance --dry-run / --apply [--actor U]` | membangun ulang presensi peragaan di jendela HR-DEMO-2 | ya — tanpa flag mode, menolak jalan |
| `seed_attendance_import_demo` | profil import, mesin, dan pemetaan nomor mesin | tidak |
| `seed_hr_demo_documents --dry-run / --apply [--actor U]` | dokumen Cuti/Izin/Lembur peragaan + konfigurasi kanoniknya | ya — tanpa flag mode, menolak jalan |
| `audit_workflow_orphans [--fix] [--include-soft]` | pengajuan alur yang dokumennya hilang | ya |
| `reset_demo_data` | membangun ulang data uji | tidak — hard delete |

---

## Kontrak reset

`reset_demo_data` melakukan hard delete pegawai berprefiks `HO` / `SGA` / `LOK`. Belasan tabel memegang `Employee` lewat FK ber-`PROTECT`, jadi urutan pelepasannya adalah kontrak, bukan gaya penulisan.

Dikunci oleh `apps/hr/tests/test_demo_reset_contract.py` (7 test):

- izin kehadiran tidak memblokir reset — termasuk baris bertanda terhapus;
- tap mesin tidak memblokir reset;
- baris payroll tidak memblokir reset, sementara kepala run tetap hidup;
- run berstatus **FINALIZED** yang memakai pegawai data uji **membatalkan seluruh reset** (satu transaksi, tidak ada penghapusan sebagian) — karena run terkunci membawa kejadian akuntansi di modul Finance yang tidak dilihat perintah ini;
- run FINALIZED milik pegawai non-data-uji **tidak** memblokir;
- pegawai di luar prefiks data uji selamat.

`BOD` dan `TRL` sengaja di luar prefiks: yang pertama bagian tetap tenant peragaan, yang kedua lini uji teknis dengan manifestnya sendiri.

---

## Pengajuan alur yatim

`WorkflowInstance` menunjuk dokumennya lewat `module` + `document_type` + `object_id` bertipe teks, tanpa foreign key. Itu keputusan yang benar untuk satu mesin yang melayani belasan tabel di tiga app — harganya dibayar dengan kemungkinan yatim.

| Bentuk | Arti |
|---|---|
| **HARD** | baris dokumennya sudah tidak ada |
| **SOFT** | baris ada tapi `is_deleted=True` — tidak terlihat di layar mana pun |
| **UNKNOWN** | `document_type` belum terdaftar di registry — dilaporkan, tidak dilewati |

`uq_workflow_open_instance` adalah **partial unique index** yang hanya mencakup status `draft` / `pending` / `returned`. Dokumen yang dibatalkan lalu diajukan ulang **sah** punya beberapa instance — itu riwayat, bukan duplikasi.

---

## Lini uji teknis (TRL)

Enam pegawai berprefiks `TRL` beserta master miliknya (`TRL-OT-TIER`, `TRL-DAILY`) adalah lini **uji teknis**, dipakai `apps/payroll/tests/test_trl_readiness.py` untuk membuktikan angka perhitungan payroll. Manifestnya di `var/trial/`.

Status per fondasi peragaan:

| | |
|---|---|
| `is_active` | **False** — tersaring dari kandidat roster dan dari pegawai payroll yang layak |
| Presensi / roster / cuti / izin / lembur / tamu / baris payroll | **nol baris** |
| Dijadwalkan mesin? | **ya** — `is_active` tidak dibaca `planned_work_days()`. Yang menahan mereka adalah cakupan eksplisit pada penutupan hari, bukan status aktifnya. |
| Akun pengguna | tidak ada |
| Dipakai sebagai dependensi peragaan | **tidak** — konfigurasi lembur peragaan memakai grup kanonik |
| Dihapus | **tidak** |

Enam baris rencana shift bertanda `TRL-2026-09-E2E` tetap ada, menempel hanya pada pegawai TRL.

---

## Keterbatasan yang diketahui

| # | Keterbatasan | Dampak | Tingkat |
|---|---|---|---|
| 1 | `OrganizationAssignment` 1:1, tanpa tanggal berlaku berlapis | pelaporan historis di bawah tingkat Location salah sesudah mutasi | HIGH |
| 2 | `division` / `department` / `section` tidak didenormalisasi ke baris transaksi | idem | HIGH |
| 3 | `AttendancePolicy` / `LeavePolicy` / `RosterPolicy` tanpa tanggal berlaku | hitung ulang menimpa sejarah | MEDIUM |
| 4 | `resolve_shift()` tidak menyaring `is_deleted` pada shift tetap | master pensiun tetap menghitung jadwal | MEDIUM |
| 5 | `RosterSetupService.candidates()` membuang siapa pun yang punya tanggal berhenti | jadwal historis pegawai yang sudah keluar tidak bisa direkonstruksi | MEDIUM |
| 6 | Tidak ada importer hari libur nasional | daftar libur diisi manual | LOW |
| 7 | Tidak ada perintah purge untuk lini TRL | residu uji teknis hanya bisa dinonaktifkan | LOW |
| 8 | `_roster_days()` tidak mengurangi hari libur | segmen WORK tetap jadi kewajiban pada hari libur nasional maupun libur lokasi | MEDIUM |
| 9 | `Employee.is_active` tidak dibaca `planned_work_days()` | pegawai nonaktif tanpa tanggal berhenti tetap dijadwalkan; penahannya cakupan proses | MEDIUM |
| 10 | Tidak ada penguncian periode pada `EmployeeAttendance` | baris periode lama bisa dihitung ulang kapan saja | MEDIUM |
| 11 | `AttendanceImportWriter` tidak mengisi FK `shift` | baris berasal-import hilang dari pengelompokan per shift | LOW |
| 11b | `AttendanceImportWriter` tidak memanggil `apply_permissions()` | baris berasal-import terbit tanpa `permission_state`; perlu hitung ulang susulan | LOW |
| 12 | Tujuh nilai `AttendanceStatus` tidak pernah ditulis jalur mana pun | `SICK`, `PERMIT`, `BUSINESS_TRIP`, `REMOTE`, `HOLIDAY`, `DAY_OFF`, `INCOMPLETE` — enum saja | LOW |
| 13 | Tidak ada jalur dari `overtime_minutes` ke `EmployeeOvertime` | bukti lembur tidak pernah jadi calon transaksi | LOW |
| 14 | `recalculate_attendance` tanpa cakupan pegawai | menghitung ulang seluruh baris di rentang tanggal | LOW |
| 15 | Slip payroll adalah snapshot beku | run yang sudah terbit tidak ikut berubah saat presensi dibangun ulang | LOW |
| 16 | `find_by_employee_number()` menuntut `is_active=True` | tap milik pegawai nonaktif tidak bisa diimpor lewat pencocokan nomor pegawai | LOW |
| 17 | **`unpaid_over_minutes` hanya dibaca pada perlakuan `PAID`** | disengaja: `split()` memotong hanya kelebihannya; `PayrollPermissionRule.clean()` bahkan **menolak** kombinasi `UNPAID` + ambang | perilaku yang disengaja |
| 17b | **`PayrollPermissionRule` tidak punya jalur tulis tervalidasi** | tidak ada service, endpoint, admin, maupun layar; kontrak `BaseService.create/update` (`full_clean()` sebelum `save()`) tidak pernah berjalan, sehingga baris yang ditolak validasi tetap bisa tersimpan | **HIGH** |
| 17c | **Satu baris tidak sah sedang tersimpan di tenant peragaan** | `temporary_out` = `UNPAID` + ambang 60 ditulis `update_or_create()` tanpa `full_clean()`; dibiarkan apa adanya supaya jejak fase 3 bisa diaudit | **INVALID CONFIGURATION — VALIDATION BYPASS** |
| 18 | Cuti yang sudah `APPROVED` tidak punya jalur pembatalan | aksi `cancel` hanya melayani dokumen `RECORDED` | MEDIUM |
| 19 | Puncak garis pelaporan tidak bisa mengajukan `leave_request` | `HR-HO-LEAVE` step 1 bertipe `MANAGER`, `fallback_role` kosong; `reports_to` HO006 kosong | MEDIUM |
| 20 | Pemegang tunggal sebuah peran tidak bisa mengajukan dokumen yang salah satu step-nya peran itu | `HR-LEAVE-SITE` step 5 (`KTT`, cakupan Location), pemohon dikecualikan dari step-nya sendiri, `fallback_role` kosong | MEDIUM |
| 20b | Role cadangan yang juga tidak ada pemegangnya tidak menolong | `HR-LEAVE-SITE` step 1 (`ADMIN-SECTION` → cadangan `ADMIN-DEPARTMENT`); Section `LOG_GENERAL` dan Department Logistics sama-sama kosong | MEDIUM |
| 20c | Pesan kegagalan step ber-role menyebut "tidak ada pemegang" walau pemegangnya adalah pemohon sendiri | diagnosis mengarahkan ke pengisian role, bukan ke pengisian `fallback_role` | LOW |
| 21 | Tidak ada alur persetujuan `EmployeeOvertime` | enum memuat `APPROVED`, tidak ada kode yang menulisnya | FUTURE |
| 22 | `EmployeeOvertime` tidak bertaut ke `EmployeeAttendance` | kaitannya lewat `(employee, work_date)` | LOW |
| 23 | Pegawai kantor pusat belum punya `OvertimeGroup` | 73 baris berbukti lembur tidak bisa diupahkan | MEDIUM |

Nomor 19, 20, 20b, dan 20c seluruhnya terbatas pada `leave_request`. **Izin kehadiran tidak terdampak**: setiap step `HR-ATT-PERMISSION` sudah membawa `fallback_role`, dan HO006 — yang cutinya tertahan — punya dua dokumen izin yang disetujui lewat alur yang sama.

Nomor 4, 5, 8, dan 9 ditangani pada tingkat **data** atau **cakupan**, bukan dengan mengubah mesin — semuanya mengubah perilaku seluruh tenant dan butuh gerbang persetujuannya sendiri.

Nomor 15 sedang berlaku di tenant peragaan: satu run payroll periode Agustus berstatus tinjauan memakai angka presensi **sebelum** pembangunan ulang HR-DEMO-2. Ia tidak dihitung ulang di fase ini dan akan dibangun ulang di HR-DEMO-5.
