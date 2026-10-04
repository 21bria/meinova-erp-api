"""
Label bahasa Inggris untuk enum Workflow.

**Sempat berbahasa Indonesia, dan itu keliru.** Alasannya masuk akal
saat ditulis — waktu itu belum ada i18n sama sekali, dan schema backend
adalah satu-satunya peta label terpusat yang tersedia. Tapi API tidak
punya cara tahu bahasa pembacanya, jadi hasilnya: **setiap** pengguna
menerima Bahasa Indonesia, termasuk yang memilih English. Layar
Workflow jadi satu-satunya bagian aplikasi yang tidak menghiraukan
pilihan bahasa orangnya.

Sekarang tempat terjemahannya sudah ada: katalog frontend
(`app/i18n/locales/<bahasa>/`), yang dipilih per pengguna. Berkas ini
kembali ke tugas aslinya — memberi **satu** kalimat Inggris untuk tiap
nilai enum, yang dipakai sebagai teks yang tampil kalau bahasa aktif
belum punya terjemahannya.

Yang tidak berubah sama sekali
------------------------------
Nilai enum-nya. `approver_type` tetap `"role"`, `approver_scope` tetap
`"location"`, `status` tetap `"approved"`. Tidak ada migration, tidak
ada baris database yang disentuh, dan tidak satu pun cabang logika
approval yang membaca berkas ini — `label_for` hanya dipanggil dari
`SerializerMethodField` dan dari `choices()` untuk dropdown.

Kenapa masih peta eksplisit, bukan `get_*_display()`
----------------------------------------------------
Label `TextChoices` ikut masuk state migration Django, jadi
memperbaikinya di model menerbitkan `AlterField` yang tidak menyentuh
satu byte pun di database. Peta di sini menghindarinya — dan sekaligus
menutup satu label Indonesia yang memang tertinggal di model
(`ApproverScope.TENANT = "tenant", "Seluruh Tenant"`), yang tanpa peta
ini akan bocor ke layar lewat `get_approver_scope_display()`.
"""

from apps.workflow.models import (
    ApprovalMode,
    ApprovalStatus,
    ApproverScope,
    ApproverType,
    AssignmentType,
    InstanceStatus,
    WorkflowStatus,
)


APPROVER_TYPE_LABELS = {
    ApproverType.MANAGER: "Direct Manager",
    ApproverType.ROLE: "Role Holder",
    ApproverType.USER: "Specific User",
    ApproverType.POSITION: "Position Hierarchy",
    ApproverType.DEPARTMENT_HEAD: "Department Head",
}


APPROVER_SCOPE_LABELS = {
    ApproverScope.TENANT: "Entire Tenant",
    ApproverScope.COMPANY: "Company",
    ApproverScope.BRANCH: "Branch",
    ApproverScope.LOCATION: "Location",
    ApproverScope.DIVISION: "Division",
    ApproverScope.DEPARTMENT: "Department",
    ApproverScope.SECTION: "Section",
}


APPROVAL_MODE_LABELS = {
    ApprovalMode.ANY: "Any Approver",
    ApprovalMode.ALL: "All Approvers",
}


WORKFLOW_STATUS_LABELS = {
    WorkflowStatus.DRAFT: "Draft",
    WorkflowStatus.ACTIVE: "Active",
    WorkflowStatus.INACTIVE: "Inactive",
}


INSTANCE_STATUS_LABELS = {
    InstanceStatus.DRAFT: "Draft",
    InstanceStatus.PENDING: "Pending",
    InstanceStatus.APPROVED: "Approved",
    InstanceStatus.REJECTED: "Rejected",
    InstanceStatus.RETURNED: "Returned",
    InstanceStatus.CANCELLED: "Cancelled",
}


APPROVAL_STATUS_LABELS = {
    ApprovalStatus.PENDING: "Pending",
    ApprovalStatus.APPROVED: "Approved",
    ApprovalStatus.REJECTED: "Rejected",
    ApprovalStatus.RETURNED: "Returned",
    ApprovalStatus.SKIPPED: "Skipped",
    ApprovalStatus.CANCELLED: "Cancelled",
}


# Dari mana nama approver itu datang. Istilahnya sengaja sama persis
# dengan `APPROVER_TYPE_LABELS` — dua daftar yang menyebut hal yang sama
# dengan kata berbeda membuat jejak dokumen terbaca seperti mekanisme
# lain.
ASSIGNMENT_TYPE_LABELS = {
    AssignmentType.USER: "Specific User",
    AssignmentType.ROLE: "Role Holder",
    AssignmentType.POSITION: "Position Hierarchy",
    AssignmentType.MANAGER: "Direct Manager",
    AssignmentType.DEPARTMENT_HEAD: "Department Head",
    AssignmentType.FALLBACK_ROLE: "Fallback Role",
}


def label_for(mapping: dict, value) -> str:
    """
    Kalimat untuk satu nilai enum, dengan nilainya sendiri sebagai
    cadangan.

    Nilai yang belum punya terjemahan tampil apa adanya, **bukan**
    kosong: pilihan yang hilang dari dropdown karena seseorang menambah
    anggota enum tanpa menambah barisnya di sini adalah kegagalan yang
    diam.
    """
    if value in (None, ""):
        return ""

    return mapping.get(value, str(value))


def choices(mapping: dict) -> list[dict]:
    """
    Bentuk `{label, value}` yang dibaca generator schema.

    Urutannya urutan tulis peta di atas — itu urutan yang tampil di
    dropdown, dan urutan yang bisa ditebak lebih berguna daripada
    urutan abjad yang berubah tiap kali istilahnya diperbaiki.
    """
    return [
        {"label": label, "value": str(value)}
        for value, label in mapping.items()
    ]
