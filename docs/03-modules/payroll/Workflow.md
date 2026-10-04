# Payroll — Workflow

**Belum ada.** Tidak ada dokumen payroll yang melewati engine approval, karena **belum ada model payroll run**.

---

## Yang sudah siap

Engine approval (`apps/workflow`) **generik dan sudah terbukti** — dipakai Cuti, Travel Request, Employee Action, Roster Setup, dan Roster Adjustment.

Menyambungkannya tidak butuh satu baris pun kode baru di sisi engine:

1. Kolom `status` `TextChoices` (DRAFT/SUBMITTED/APPROVED/REJECTED/CANCELLED/RETURNED)
2. `@action` `submit/` + `withdraw/`
3. Callback `@register_completion("payroll", "payroll_run")`, **di-import dari `AppConfig.ready()`**
4. `registry.register_route()` supaya kotak masuk bisa menautkan
5. `WorkflowDefinition` diseed
6. Deret nomor di `seed_administration --only=numbering`
7. `action.submit()`/`approve()` di schema

Checklist lengkap: [Build A Module](../../02-Framework/Build-A-Module.md#kalau-modulnya-dokumen-berapproval).

---

## Yang perlu diputuskan lebih dulu

### Apa yang disetujui: satu run, atau per pegawai?

Kalau satu run untuk ratusan pegawai, aturan yang sama dengan **Roster Setup** berlaku:

- **Step per-pegawai boleh, tapi hanya kalau seluruh baris batch menghasilkan approver yang sama.** "Atasan langsung" dari tiga ratus orang bukan satu orang — dan untuk payroll run se-perusahaan, praktisnya itu berarti mejanya memang harus Role/User. Polanya ada di `RosterSetupService.batch_approver_findings()`: `resolve_approvers()` dijalankan untuk setiap subjek batch, lalu hasilnya dibandingkan; lebih dari satu = ditolak dengan menyebut kelompoknya
- Cakupan approver tidak bisa ditentukan kalau satu batch bercampur banyak company

### Kapan angkanya dibekukan?

Payroll run harus membaca `PayrollAssignment` yang **`is_current` pada tanggal periode**, bukan yang terbaru. Dan begitu disetujui, angkanya sebaiknya **dibekukan di baris run**, bukan dihitung ulang tiap dibuka.

Pola yang sama dengan `WorkflowInstance.context` — cuplikan nilai dokumen yang dibekukan saat pengajuan, supaya syarat sebuah step tidak berubah di tengah jalan.

### Efek samping saat disetujui

Ikuti aturan yang sudah berlaku:

- **Berjalan saat disetujui**, bukan saat diketik
- **`on_complete` tidak melempar** — kegagalannya ditempel ke kolom error pada dokumennya dan diulang lewat `POST .../apply/`
- **Idempotensi dijaga kolom yang dibaca ulang di bawah `select_for_update`**, bukan `status` yang sudah di tangan

### Kerahasiaan

Slip gaji sangat sensitif. Ia masuk `EmployeeDataPolicy`, dan **wajib ditutup di tiga jalur**: serializer, endpoint sub-resource, dan export CSV.

Di CSV, kolomnya **dibuang seluruhnya** — bukan dikosongkan per baris, karena CSV yang sebagian selnya terisi membocorkan polanya.
