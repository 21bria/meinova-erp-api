"""
Pengajuan alur yang dokumennya sudah tidak ada.

`WorkflowInstance` menunjuk dokumennya lewat tiga kolom teks —
`module`, `document_type`, `object_id` — dan **bukan** lewat foreign
key. Itu keputusan yang benar: satu mesin alur melayani dua belas tabel
di tiga app, dan FK generik ke semuanya berarti mesin alur ikut berubah
tiap ada dokumen baru.

Harganya dibayar di sini. Tidak ada cascade, tidak ada `ProtectedError`,
tidak ada apa pun yang mencegah dokumennya dihapus lebih dulu — dan yang
tertinggal adalah pengajuan yang menunjuk baris yang tidak ada. Di layar
monitoring ia muncul sebagai dokumen tanpa judul yang tidak bisa dibuka;
di database ia tetap memegang `subject_employee` lewat FK ber-`PROTECT`,
jadi suatu hari ia menggagalkan penghapusan pegawai dengan pesan yang
tidak pernah menyebut kata "workflow".

Dua bentuk yatim, dan bedanya penting
-------------------------------------
**HARD** — barisnya benar-benar tidak ada lagi. Tidak ada yang bisa
dipulihkan; satu-satunya tindakan yang masuk akal adalah membuang
pengajuannya.

**SOFT** — barisnya masih ada tapi `is_deleted=True`. Seluruh queryset
aplikasi menyaring `is_deleted=False`, jadi bagi pengguna dokumen itu
sudah hilang, sementara pengajuannya masih berdiri. Ini yang paling
menyesatkan: datanya ada, layarnya kosong.

Yang **tidak** dilakukan berkas ini
-----------------------------------
Menebak. `document_type` yang tidak terdaftar di `REGISTRY` dilaporkan
sebagai `unknown`, bukan dilewati diam-diam — jenis dokumen baru yang
lupa didaftarkan harus terbaca sebagai pekerjaan yang belum selesai,
bukan sebagai "tidak ada yatim".
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module


#: `document_type` → (modul model, nama kelas).
#:
#: Sengaja daftar tertulis, bukan penelusuran otomatis lewat
#: `ContentType`: `document_type` adalah kosakata bisnis yang dipilih
#: tiap service, dan tidak selalu sama dengan nama model
#: (`leave_request` → `EmployeeLeave`).
REGISTRY: dict[str, tuple[str, str]] = {
    "attendance_permission": ("apps.hr.models", "AttendancePermission"),
    "employee_action": ("apps.hr.models", "EmployeeAction"),
    "leave_request": ("apps.hr.models", "EmployeeLeave"),
    "roster_setup": ("apps.hr.models", "RosterSetupRequest"),
    "roster_adjustment": ("apps.hr.models", "RosterAdjustment"),
    "site_rotation": ("apps.hr.models", "SiteRotation"),
    "travel_request": ("apps.hr.models", "TravelRequest"),
    "business_trip": ("apps.hr.models", "BusinessTrip"),
    "visitor_request": ("apps.hr.models", "VisitorRequest"),
    "visitor_pass": ("apps.hr.models", "VisitorPass"),
    "external_visitor": ("apps.hr.models", "ExternalVisitor"),
    "payroll_run": ("apps.payroll.models", "PayrollRun"),
    "payslip": ("apps.payroll.models", "Payslip"),
    "journal": ("apps.finance.models", "Journal"),
}


HARD = "hard"
SOFT = "soft"
UNKNOWN = "unknown"
LIVE = "live"


@dataclass(frozen=True)
class OrphanRow:
    instance_id: int
    module: str
    document_type: str
    object_id: str
    document_number: str
    status: str
    kind: str
    note: str

    @property
    def is_orphan(self) -> bool:
        return self.kind in {HARD, SOFT}


def _model_for(document_type: str):
    target = REGISTRY.get(document_type)

    if target is None:
        return None

    module_path, model_name = target

    return getattr(import_module(module_path), model_name)


def scan() -> list[OrphanRow]:
    """
    Seluruh `WorkflowInstance` tenant yang sedang aktif, beserta
    keadaan dokumennya.

    Read-only. Tidak menyentuh satu baris pun.
    """
    from apps.workflow.models import WorkflowInstance

    rows: list[OrphanRow] = []

    instances = (
        WorkflowInstance.objects
        .all()
        .order_by("id")
        .values(
            "id",
            "module",
            "document_type",
            "object_id",
            "document_number",
            "status",
        )
    )

    for row in instances:
        model = _model_for(row["document_type"])

        if model is None:
            rows.append(
                OrphanRow(
                    instance_id=row["id"],
                    module=row["module"],
                    document_type=row["document_type"],
                    object_id=row["object_id"],
                    document_number=row["document_number"],
                    status=row["status"],
                    kind=UNKNOWN,
                    note=(
                        "Jenis dokumen belum terdaftar di REGISTRY — "
                        "tidak bisa diperiksa, dan itu temuan."
                    ),
                ),
            )

            continue

        # `object_id` bertipe teks dan bisa berisi apa saja. Yang bukan
        # bilangan bukan sekadar "tidak ketemu" — ia penanda bahwa ada
        # yang menulis kolom ini dengan bentuk yang tidak pernah bisa
        # dicocokkan.
        try:
            pk = int(row["object_id"])
        except (TypeError, ValueError):
            rows.append(
                OrphanRow(
                    instance_id=row["id"],
                    module=row["module"],
                    document_type=row["document_type"],
                    object_id=row["object_id"],
                    document_number=row["document_number"],
                    status=row["status"],
                    kind=HARD,
                    note="object_id bukan bilangan.",
                ),
            )

            continue

        document = model.objects.filter(pk=pk).first()

        if document is None:
            kind, note = HARD, "Barisnya sudah tidak ada."
        elif getattr(document, "is_deleted", False):
            kind, note = (
                SOFT,
                "Baris ada tapi bertanda terhapus — tidak terlihat di "
                "layar mana pun.",
            )
        else:
            kind, note = LIVE, ""

        rows.append(
            OrphanRow(
                instance_id=row["id"],
                module=row["module"],
                document_type=row["document_type"],
                object_id=row["object_id"],
                document_number=row["document_number"],
                status=row["status"],
                kind=kind,
                note=note,
            ),
        )

    return rows


def duplicates(rows: list[OrphanRow]) -> dict[tuple[str, str, str], list[int]]:
    """
    Dokumen yang punya lebih dari satu pengajuan.

    Bukan yatim, tapi ditemukan lewat pemindaian yang sama dan
    memperlihatkan kelas masalah yang sama: tidak ada integritas
    referensial yang mencegahnya.
    """
    seen: dict[tuple[str, str, str], list[int]] = {}

    for row in rows:
        key = (row.module, row.document_type, row.object_id)

        seen.setdefault(key, []).append(row.instance_id)

    return {key: ids for key, ids in seen.items() if len(ids) > 1}
