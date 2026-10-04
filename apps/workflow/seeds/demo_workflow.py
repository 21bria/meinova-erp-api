"""
Data uji alur cuti Head Office, termasuk delegasi.

Susunan orangnya — akun, role, garis pelaporan — **dibentuk
`seed_demo_workforce`**, bukan di sini. Seed ini hanya menjalankan
skenarionya: pegawai kantor pusat mengajukan cuti sendiri, atasannya
menyetujui, HR Manager menyetujui, saldonya terpotong.

Aman diulang. Cuti yang dibuatnya ditandai di `notes` supaya bisa
dikenali dan dibersihkan sebelum dibuat ulang — kalau tidak, tiap
pemanggilan menumpuk pengajuan baru dan saldo pegawai uji ikut turun
terus.
"""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.administration.models import LeaveType
from apps.hr.api.leave.services import EmployeeLeaveService
from apps.hr.models import Employee, EmployeeLeave, LeaveStatus
from apps.workflow.models import (
    InstanceStatus,
    WorkflowDelegation,
)
from apps.workflow.services import (
    WorkflowApprovalService,
    WorkflowService,
)


MARKER = "[data uji workflow]"


# Siapa yang dipakai skenario ini. Susunannya **dibentuk
# `seed_demo_workforce`**, di sini cuma ditunjuk — nomor pegawai saja,
# tanpa email/role/atasan, supaya tidak ada dua sumber kebenaran untuk
# orang yang sama.
#
# Semuanya pegawai kantor pusat: skenario ini menguji alur cuti HO dan
# delegasinya. Pegawai site punya skenarionya sendiri di
# `site_travel_demo.py`, dan mencampurnya membuat "kenapa dokumen HO
# lewat meja site" jadi pertanyaan yang tidak perlu ada.
PEOPLE = [
    {
        "employee_number": "HO003",
        "note": "Pengaju — staf kantor pusat",
    },
    {
        "employee_number": "HO005",
        "note": "Atasan langsung pengaju",
    },
    {
        "employee_number": "HO001",
        "note": "HR Manager kantor pusat — meja terakhir",
    },
    {
        "employee_number": "HO004",
        "note": "Penerima kuasa saat HR Manager berhalangan",
    },
]


# ----------------------------------------------------------------------
# Penyiapan
# ----------------------------------------------------------------------


def _employee(number: str) -> Employee | None:
    return (
        Employee.objects
        .filter(employee_number=number, is_deleted=False)
        .select_related("user", "organization", "employment")
        .first()
    )


def prepare_people() -> tuple[dict[str, Employee], list[str]]:
    """
    Mencari orang-orangnya — **tidak** membentuknya.

    Akun, role, dan garis pelaporan dimiliki `seed_demo_workforce`.
    Dulu seed ini ikut membentuknya, dan dua seed yang membentuk orang
    yang sama menghasilkan dua akun berbeda untuk satu pegawai
    (`demo.hostaff` dan `demo.hostaff@example.test`) plus garis
    pelaporan yang berganti-ganti tergantung mana yang dijalankan
    terakhir. Yang tampak di layar: meja yang seharusnya milik satu
    orang diisi orang lain, tanpa ada yang salah konfigurasi.

    Pegawai yang belum punya akun dilaporkan sebagai kurang, bukan
    dibuatkan diam-diam.
    """
    people: dict[str, Employee] = {}
    missing: list[str] = []

    for config in PEOPLE:
        employee = _employee(config["employee_number"])

        if employee is None or employee.user_id is None:
            missing.append(config["employee_number"])

            continue

        people[config["employee_number"]] = employee

    return people, missing


# ----------------------------------------------------------------------
# Skenario
# ----------------------------------------------------------------------


def _clear_previous(employee: Employee) -> int:
    """
    Membersihkan pengajuan uji sebelumnya.

    Dihapus keras, bukan soft delete: ini data uji, dan instance
    workflow yang tertinggal akan menghalangi pengajuan baru lewat
    constraint 'satu dokumen satu pengajuan berjalan'.
    """
    leaves = EmployeeLeave.objects.filter(
        employee=employee,
        notes__contains=MARKER,
    )

    removed = 0

    for leave in leaves:
        WorkflowService.history_for(
            document=leave,
            module="hr",
            document_type="leave_request",
        ).delete()

        leave.delete()

        removed += 1

    return removed


def _leave_type() -> LeaveType | None:
    return (
        LeaveType.objects
        .filter(code="ANNUAL", is_deleted=False)
        .first()
    )


def _create_leave(employee, leave_type, *, start, end, label, user):
    return EmployeeLeaveService.create(
        data={
            "employee": employee,
            "leave_type": leave_type,
            "start_date": start,
            "end_date": end,
            "status": LeaveStatus.DRAFT,
            "notes": f"{MARKER} {label}",
        },
        user=user,
    )


def _trail(instance) -> list[str]:
    lines = []

    for row in WorkflowApprovalService.history_for(instance=instance):
        approver = "—"

        if row.approver_employee_id:
            approver = row.approver_employee.full_name
        elif row.approver_id:
            approver = row.approver.email

        line = (
            f"      #{row.sequence} {row.name:42} "
            f"{row.status:9} {approver}"
        )

        if row.was_delegated:
            line += f"  (ditekan {row.acted_by.email})"

        if row.status == "skipped" and row.assignment_reference:
            line += f"\n           ↳ {row.assignment_reference}"

        lines.append(line)

    return lines


def _approve_all(instance, people, log, limit=None) -> None:
    """
    Menjalankan alurnya sampai berhenti, satu keputusan per putaran.

    `limit` membatasi berapa keputusan yang diambil — dipakai skenario
    yang sengaja berhenti di tengah.

    Approver dicari dari kotak masuk masing-masing orang, bukan dari
    baris yang sedang pending — persis jalur yang dilewati pengguna
    sungguhan, jadi kalau penyaringan kotak masuk salah, skenario ini
    yang lebih dulu berhenti.
    """
    from apps.workflow.registry import completion_handler

    handler = completion_handler(
        module="hr",
        document_type="leave_request",
    )

    taken = 0

    for _ in range(10):
        if limit is not None and taken >= limit:
            return

        instance.refresh_from_db()

        if instance.status != InstanceStatus.PENDING:
            return

        # Approver diambil dari baris yang sedang ditunggu, bukan dari
        # daftar orang yang disiapkan skenario ini: step Kepala
        # Departemen bisa jatuh ke siapa saja yang memegang jabatan
        # bertanda Manager di department pengaju, dan membatasinya ke
        # daftar tetap membuat skenario berhenti di tengah tanpa alasan
        # yang benar.
        pending = instance.pending_approvals.select_related(
            "approver",
            "approver_employee",
        ).first()

        if pending is None or pending.approver_id is None:
            log(
                "      ! Baris berjalan tidak punya approver berakun — "
                "alur berhenti."
            )

            return

        actor = pending.approver

        # Diperiksa lewat kotak masuknya, bukan langsung disetujui:
        # inilah jalur yang dilewati pengguna sungguhan, jadi kalau
        # penyaringan kotak masuk salah, skenario ini yang lebih dulu
        # berhenti.
        in_inbox = (
            WorkflowApprovalService.pending_for(
                actor,
                module="hr",
                document_type="leave_request",
            )
            .filter(pk=pending.pk)
            .exists()
        )

        if not in_inbox:
            log(
                f"      ! Baris #{pending.sequence} tidak muncul di "
                f"kotak masuk {actor.email} — alur berhenti."
            )

            return

        name = (
            pending.approver_employee.full_name
            if pending.approver_employee_id
            else actor.email
        )

        WorkflowService.approve(
            instance=instance,
            user=actor,
            comment=f"Disetujui oleh {name}.",
            on_complete=handler,
        )

        taken += 1

        log(
            f"      ✓ {pending.name} disetujui {name} ({actor.email})"
        )


def _balance_line(employee, leave_type, year) -> str:
    from apps.hr.models import LeaveBalance

    balance = (
        LeaveBalance.objects
        .filter(
            employee=employee,
            leave_type=leave_type,
            year=year,
            is_deleted=False,
        )
        .first()
    )

    if balance is None:
        return "belum ada baris saldo"

    return (
        f"jatah {balance.entitlement}, terpakai {balance.used}, "
        f"sisa {balance.remaining}"
    )


@transaction.atomic
def run(*, log=print) -> dict:
    people, missing = prepare_people()

    if missing:
        log(
            f"  ! Pegawai {', '.join(missing)} tidak ada di tenant ini. "
            "Jalankan dulu `tenant_command seed_demo_workforce`."
        )

    applicant = people.get("HO003")
    leave_type = _leave_type()

    if applicant is None or leave_type is None:
        return {
            "created": 0,
            "missing": missing,
            "note": "Pengaju atau master Cuti Tahunan belum ada.",
        }

    removed = _clear_previous(applicant)

    if removed:
        log(f"  Membersihkan {removed} pengajuan uji sebelumnya.")

    today = timezone.localdate()
    year = today.year

    log("")
    log(f"  Pengaju     : {applicant.full_name} ({applicant.employee_number})")
    log(f"  Lokasi      : {applicant.organization.location}")
    log(f"  Saldo awal  : {_balance_line(applicant, leave_type, year)}")

    scenarios = [
        {
            "label": "cuti pendek (2 hari)",
            "start": today + timedelta(days=14),
            "end": today + timedelta(days=15),
            "approve": True,
            "expect": (
                "Dua meja: Atasan Langsung lalu HR Manager. Sejak "
                "syarat 5 hari dicabut, cuti pendek pun naik ke sana."
            ),
        },
        {
            "label": "cuti panjang (10 hari kalender)",
            "start": today + timedelta(days=40),
            "end": today + timedelta(days=49),
            "approve": True,
            "expect": (
                "Sama seperti di atas — yang dibedakan cuma lamanya, "
                "supaya potongan saldo yang besar ikut terlihat."
            ),
        },
        {
            "label": "cuti menunggu keputusan",
            "start": today + timedelta(days=70),
            "end": today + timedelta(days=74),
            "approve": False,
            "expect": (
                "Sengaja ditinggal menunggu, supaya kotak masuk "
                "approver ada isinya."
            ),
        },
        {
            "label": "cuti berhenti di tengah",
            "start": today + timedelta(days=95),
            "end": today + timedelta(days=104),
            # Satu tahap disetujui lalu berhenti. Tanpa baris seperti
            # ini, layar monitoring cuma berisi 0% dan 100% — dan bar
            # progres yang tidak pernah menunjukkan angka di antaranya
            # tidak membuktikan apa pun.
            "approve": 1,
            "expect": (
                "Satu tahap disetujui lalu berhenti — contoh dokumen "
                "yang progresnya di tengah."
            ),
        },
    ]

    created = 0

    for scenario in scenarios:
        log("")
        log(f"  ── {scenario['label']}")
        log(f"     {scenario['expect']}")

        leave = _create_leave(
            applicant,
            leave_type,
            start=scenario["start"],
            end=scenario["end"],
            label=scenario["label"],
            user=applicant.user,
        )

        instance = EmployeeLeaveService.submit(
            instance=leave,
            user=applicant.user,
            notes="Diajukan dari data uji.",
        )

        leave.refresh_from_db()

        log(
            f"     Diajukan → alur {instance.definition.code}, "
            f"hari kerja terpotong {leave.total_days}"
        )

        for line in _trail(instance):
            log(line)

        if scenario["approve"]:
            _approve_all(
                instance,
                people,
                log,
                limit=(
                    scenario["approve"]
                    if isinstance(scenario["approve"], int)
                    and not isinstance(scenario["approve"], bool)
                    else None
                ),
            )

            instance.refresh_from_db()
            leave.refresh_from_db()

            log(
                f"     Selesai → workflow {instance.status}, "
                f"cuti {leave.status}"
            )

        created += 1

    # Surat kuasa: HR Manager berhalangan, staf lain yang menekan
    # tombolnya. Approver-nya tetap tercatat HR Manager — yang berubah
    # cuma siapa yang boleh memutuskan.
    delegation = _ensure_delegation(people)

    if delegation is not None:
        log("")
        log(
            f"  Surat kuasa : {delegation.delegator.email} → "
            f"{delegation.delegate.email} "
            f"({delegation.starts_at:%d/%m/%Y} – "
            f"{delegation.ends_at:%d/%m/%Y}, cakupan "
            f"{delegation.module}/{delegation.document_type})"
        )

    log("")
    log(f"  Saldo akhir : {_balance_line(applicant, leave_type, year)}")

    return {
        "created": created,
        "missing": missing,
        "people": len(people),
        "delegation": delegation is not None,
    }


def _ensure_delegation(people) -> WorkflowDelegation | None:
    delegator = people.get("HO001")
    delegate = people.get("HO004")

    if delegator is None or delegate is None:
        return None

    if delegator.user_id is None or delegate.user_id is None:
        return None

    now = timezone.now()

    delegation, _ = WorkflowDelegation.objects.update_or_create(
        delegator=delegator.user,
        delegate=delegate.user,
        module="hr",
        document_type="leave_request",
        defaults={
            "starts_at": now - timedelta(days=1),
            "ends_at": now + timedelta(days=30),
            "reason": f"{MARKER} HR Manager sedang cuti.",
            "is_active": True,
            "is_deleted": False,
        },
    )

    return delegation
