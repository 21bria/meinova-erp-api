# ERD

Diagram relasi antar model inti. 168 model total — yang digambar di sini hanya yang perlu dipahami untuk membaca modul HR.

Konvensi penamaannya di [Naming Convention](Naming-Convention.md), pola desainnya di [Database Design](Database-Design.md).

---

## Struktur organisasi

```mermaid
erDiagram
    Company ||--o{ Branch : ""
    Company ||--o{ Location : ""
    Branch  ||--o{ Location : "nullable"
    Company ||--o{ Division : ""
    Division ||--o{ Department : "nullable"
    Department ||--o{ Section : "nullable"
    Company ||--o{ Position : ""
    Position ||--o{ Position : "reports_to"
    Company ||--o{ CostCenter : ""
```

**Hanya Company yang wajib.** Seluruh level di bawahnya nullable dan boleh dilompati — `Location.branch` boleh kosong.

Konsekuensinya: kode unik **per company**, dan penyaringan memakai pola "cocok dengan induk **ATAU** induknya null".

---

## Employee dan empat penempatannya

```mermaid
erDiagram
    User ||--o| Employee : "employee_profile"
    Employee ||--|| OrganizationAssignment : "organization"
    Employee ||--|| EmploymentAssignment : "employment"
    Employee ||--o{ PayrollAssignment : "effective-dated"
    Employee ||--o{ EmployeeBankAccount : ""
    Employee ||--o{ EmployeeEducation : ""
    Employee ||--o{ EmployeeFamily : ""
    Employee ||--o{ EmployeeDocument : ""
    Employee ||--o{ EmployeeMedicalEvent : ""

    OrganizationAssignment }o--|| Company : ""
    OrganizationAssignment }o--o| Location : ""
    OrganizationAssignment }o--o| Section : ""
    EmploymentAssignment }o--o| RosterPolicy : ""
    EmploymentAssignment }o--o| RosterCrew : "jalur lama"
    EmploymentAssignment }o--o| WorkCalendar : ""
    EmploymentAssignment }o--o| City : "point_of_hire"
    PayrollAssignment }o--o| TaxStatus : "PTKP"
```

!!! danger "Accessor akun → pegawai adalah `user.employee_profile`"
    Bukan `user.employee`. `getattr` mengembalikan `None` tanpa error — kesalahan ini pernah membuat "pegawainya sendiri" tidak pernah cocok di `EmployeeDataPolicy`.

`Employee` sendiri hanya identitas. Yang menentukan perilakunya ada di `EmploymentAssignment` — terutama `roster_policy`/`roster_crew`, yang membelah hampir semua perhitungan HR jadi cabang HO vs site.

---

## Cuti

```mermaid
erDiagram
    EmployeeLeave }o--|| Employee : ""
    EmployeeLeave }o--|| LeaveType : ""
    LeaveBalance }o--|| Employee : ""
    LeaveBalance }o--|| LeaveType : ""
    LeavePolicy }o--o| Company : "cakupan"
    LeavePolicy }o--|| LeaveType : ""
    LeavePolicy ||..o{ LeaveBalance : "generate_leave_balances"
    EmployeeLeave ||..o| WorkflowInstance : "module=hr, type=leave_request"
```

`LeaveBalance.used` **disimpan** (supaya bisa disortir), tapi selalu **dijumlahkan ulang penuh** dari record `EmployeeLeave`.

`LeavePolicy` menyimpan **aturannya**, bukan angkanya — angkanya diterbitkan `generate_leave_balances`, dan kolom `adjustment` tidak pernah disentuh generator.

---

## Roster & Travel Request

```mermaid
erDiagram
    RosterPolicy ||--o{ RosterTravelDay : "(site, POH) → hari"
    RosterPolicy ||--o{ EmploymentAssignment : ""

    RosterSetupRequest ||--o{ RosterSetupLine : ""
    RosterSetupRequest }o--|| Location : "satu batch = satu site"
    RosterSetupLine }o--|| Employee : ""
    RosterSetupLine ||..|| SiteRotation : "commit"

    SiteRotation ||--o{ RotationPeriod : "berversi"
    SiteRotation ||--o{ RosterPlanVersion : ""
    RotationPeriod }o--o| RotationPurpose : ""
    RotationPeriod }o--o| EmployeeLeave : "SET_NULL"

    TravelRequest }o--o| RotationPeriod : "usulan tanggal, nullable"
    TravelRequest ||--o{ TravelRequestPurpose : ""
    TravelRequest ||--o{ TravelArrangement : "satu baris = satu etape"
    TravelRequestPurpose }o--|| RotationPurpose : ""
    TravelRequestPurpose }o--o| EmployeeLeave : "diterbitkan saat disetujui"

    RosterAdjustment }o--|| SiteRotation : ""
    RosterAdjustment ||..o{ RotationCreditTransaction : "kompensasi"
    RotationCreditTransaction }o--|| Employee : "ledger append-only"
    RotationCreditBalance }o--|| Employee : "dihitung dari ledger"
```

Tiga hal yang paling sering salah dibaca dari diagram ini:

1. **`TravelRequest.rotation_period` nullable** — roster bukan syarat TR.
2. **Tanggal penerbangan hanya di `TravelArrangement`.** `RotationPeriod` cuma menghitung perkiraan jendela travel. Jangan kembalikan baris travel ke roster.
3. **`RotationPurpose` bukan `LeaveType`.** Master tersendiri, karena Field Break tidak memotong saldo sementara Cuti Tahunan memotong. `deducts_leave` yang jadi penentu.

---

## Engine workflow

```mermaid
erDiagram
    WorkflowDefinition ||--o{ WorkflowStep : ""
    WorkflowStep ||--o{ WorkflowStepFallback : "cadangan berjenjang"
    WorkflowDefinition ||--o{ WorkflowInstance : ""
    WorkflowInstance ||--o{ WorkflowApproval : "kotak tanda tangan"
    WorkflowApproval }o--|| User : "approver"
    WorkflowApproval }o--o| User : "acted_by (delegasi)"
    WorkflowDelegation }o--|| User : ""
```

!!! warning "Tidak ada FK dari `WorkflowInstance` ke dokumen"
    Dokumen ditunjuk `module` + `document_type` + `object_id` (**string**), bukan `GenericForeignKey`. Engine jadi tidak perlu mengenal model modul mana pun.

    Konsekuensinya **tidak ada integritas referensial** di level database — yang menjaganya constraint `uq_workflow_open_instance` dan kenyataan bahwa penghapusan dokumen selalu soft.

---

## RBAC

```mermaid
erDiagram
    User }o--o{ Role : "user.roles"
    Role }o--o{ Permission : "708 baris auth.Permission"
    Role ||--o{ RoleMenuPermission : ""
    Role ||--o{ RoleDataPermission : ""
    RoleMenuPermission }o--|| Menu : ""
    Menu ||--o{ Menu : "grup → item"
```

!!! danger "`User.groups` bawaan Django diwarisi tapi TIDAK dibaca satu baris kode pun"
    Dua sistem paralel. Yang berlaku hanya `roles`, dibaca lewat `RolePermissionBackend`.

`RoleDataPermission` **tidak punya kolom `can_view`** — itu milik `RoleMenuPermission`. Dua model bersaudara dengan bentuk berbeda, dan sudah dua kali menjatuhkan kode yang menyalinnya.

---

## Master aturan berjenjang

Lima master mengikuti pola yang sama: kolom cakupan + skor `specificity`.

```mermaid
erDiagram
    WorkflowDefinition }o--o| Company : "specificity 8/4/2/1"
    LeavePolicy }o--o| Company : ""
    RosterPolicy }o--o| Company : ""
    EmployeeActionPolicy }o--o| Company : ""
    EmployeeDataPolicy }o--o| Company : ""
```

Semuanya punya `company` / `location` / `employee_group` (sebagian juga `branch`). **Kosong berarti "berlaku untuk semua", bukan "tidak berlaku".**

---

## Menggambar ERD lengkap

Belum ada ERD 168 model yang di-generate otomatis. Kalau perlu:

```bash
pip install django-extensions pygraphviz
python manage.py graph_models hr administration -o erd-hr.png
```

Untuk multi-tenant, jalankan pada satu app agar hasilnya terbaca — diagram seluruh model tidak berguna sebagai gambar.
