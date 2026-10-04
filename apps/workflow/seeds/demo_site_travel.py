"""
Skenario data uji alur persetujuan: site dan kantor pusat.

Menjalankan **tiga** dokumen sampai selesai lewat kotak masuk generik:

* Travel Request pegawai site  → enam meja alur site
* Cuti pegawai site            → enam meja yang sama
* Cuti pegawai kantor pusat    → alur HO, tiga meja, tanpa satu pun
  meja site

Yang paling penting dibuktikan di sini bukan "alurnya jalan", melainkan
**tidak ada yang nyasar**: role `HR-ADMIN` dan `HR-MANAGER` dipegang dua
orang di dua lokasi, dan yang memisahkan mereka `approver_scope`. Kalau
cakupannya salah, dokumen Sagea akan mendarat di meja Jakarta dan
sebaliknya — dan itu tetap terlihat "berhasil" kalau yang diperiksa cuma
status akhirnya.

Susunan orangnya **tidak dibentuk di sini.** `seed_demo_workforce`
pemilik tunggalnya: nomor pegawai, jabatan, akun, role, garis
pelaporan, dan section. Dulu dua seed sama-sama membentuk orang yang
sama dengan username berbeda (`demo.siteadmin` vs
`demo.siteadmin@example.test`), dan hasilnya persis kekacauan yang mau
dihilangkan. Di sini cuma dicari dan dipakai.

Aman diulang: dokumen uji ditandai di `notes` dan dibersihkan lebih
dulu.
"""

from __future__ import annotations

from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.administration.models import LeaveType, RotationPurpose
from apps.hr.api.leave.services import EmployeeLeaveService
from apps.hr.api.travel_request.services import (
    TravelRequestPurposeService,
    TravelRequestService,
)
from apps.hr.models import Employee, EmployeeLeave, TravelRequest
from apps.workflow.models import InstanceStatus
from apps.workflow.services import (
    WorkflowApprovalService,
    WorkflowService,
)


MARKER = "[data uji alur]"


# Siapa yang mengajukan apa. Nomor pegawainya menunjuk `WORKFORCE` di
# `apps/hr/seeds/demo_workforce.py`; kalau susunan di sana berubah,
# yang di sini ikut, bukan dibentuk ulang.
SCENARIOS = [
    {
        "key": "site_travel",
        "title": "Travel Request — pegawai site",
        "employee_number": "SGA002",
        "document": "travel_request",
    },
    {
        "key": "site_leave",
        "title": "Cuti — pegawai site",
        "employee_number": "SGA002",
        "document": "leave_request",
    },
    {
        "key": "ho_leave",
        "title": "Cuti — pegawai kantor pusat",
        "employee_number": "HO003",
        "document": "leave_request",
    },
]


def _employee(number: str) -> Employee | None:
    return (
        Employee.objects
        .filter(employee_number=number, is_deleted=False)
        .select_related(
            "user",
            "organization__location",
            "organization__section",
            "employment",
        )
        .first()
    )


def _clear_previous() -> int:
    removed = 0

    for model, document_type in [
        (TravelRequest, "travel_request"),
        (EmployeeLeave, "leave_request"),
    ]:
        for document in model.objects.filter(notes__contains=MARKER):
            WorkflowService.history_for(
                document=document,
                module="hr",
                document_type=document_type,
            ).delete()

            if model is TravelRequest:
                # `travels`, bukan `arrangements` — itu `related_name`
                # yang dipakai `TravelArrangement.request`.
                document.travels.all().delete()
                document.purposes.all().delete()

            document.delete()

            removed += 1

    return removed


# ----------------------------------------------------------------------
# Pembuatan dokumen
# ----------------------------------------------------------------------


def _create_travel_request(employee, today):
    request = TravelRequestService.create(
        data={
            "employee": employee,
            "start_date": today + timedelta(days=30),
            "end_date": today + timedelta(days=44),
            "notes": f"{MARKER} kepulangan cuti lapangan",
        },
        user=employee.user,
    )

    purpose = (
        RotationPurpose.objects
        .filter(is_deleted=False)
        .order_by("deducts_leave", "code")
        .first()
    )

    if purpose is not None:
        TravelRequestPurposeService.create(
            data={
                "request": request,
                "purpose": purpose,
                "start_date": request.start_date,
                "end_date": request.end_date,
            },
            user=employee.user,
        )

    request.refresh_from_db()

    return request


def _create_leave(employee, today):
    leave_type = (
        LeaveType.objects
        .filter(is_deleted=False)
        .order_by("code")
        .first()
    )

    if leave_type is None:
        return None

    # Tujuh hari, bukan dua: step HR Manager di alur kantor pusat
    # bersyarat `total_days >= 5`, dan cuti pendek membuat meja itu
    # dilewati — skenario terlihat berhasil sambil menguji satu meja
    # lebih sedikit.
    return EmployeeLeaveService.create(
        data={
            "employee": employee,
            "leave_type": leave_type,
            "start_date": today + timedelta(days=30),
            "end_date": today + timedelta(days=36),
            "notes": f"{MARKER} pengajuan cuti",
        },
        user=employee.user,
    )


def _submit(document, *, document_type, employee):
    if document_type == "travel_request":
        return TravelRequestService.submit(
            request=document,
            user=employee.user,
            notes="Diajukan dari data uji.",
        )

    return EmployeeLeaveService.submit(
        instance=document,
        user=employee.user,
        notes="Diajukan dari data uji.",
    )


def _status(document):
    document.refresh_from_db()

    return document.status


# ----------------------------------------------------------------------
# Menjalankan satu skenario
# ----------------------------------------------------------------------


def _run_scenario(config, *, today, log) -> dict:
    employee = _employee(config["employee_number"])

    log("")
    log(f"  ── {config['title']}")

    if employee is None:
        log(
            f"     ! {config['employee_number']} tidak ada — jalankan "
            "`tenant_command seed_demo_workforce` dulu."
        )

        return {"ok": False}

    if employee.user_id is None:
        log(f"     ! {employee.employee_number} belum punya akun pengguna.")

        return {"ok": False}

    organization = employee.organization

    log(
        f"     Pengaju : {employee.full_name} "
        f"({employee.employee_number}) — {organization.location}"
        + (f" / {organization.section}" if organization.section_id else "")
    )

    document_type = config["document"]

    document = (
        _create_travel_request(employee, today)
        if document_type == "travel_request"
        else _create_leave(employee, today)
    )

    if document is None:
        log("     ! Master jenis cuti kosong — jalankan seed referensi HR.")

        return {"ok": False}

    number = getattr(document, "document_number", None) or f"#{document.pk}"

    workflow = _submit(document, document_type=document_type, employee=employee)

    log(f"     Dokumen : {number} → alur {workflow.definition.code}")
    log("")

    for row in WorkflowApprovalService.history_for(instance=workflow):
        who = (
            row.approver_employee.full_name
            if row.approver_employee_id
            else (row.approver.username if row.approver_id else "—")
        )

        where = "—"

        if row.approver_employee_id:
            assignment = getattr(row.approver_employee, "organization", None)

            where = str(getattr(assignment, "location", None) or "—")

        log(
            f"       #{row.sequence} {row.name:32} {row.status:9} "
            f"{who[:20]:22} {where}"
        )

    log("")

    # Batasnya diturunkan dari jumlah step, bukan angka tetap: alur ini
    # tumbuh dari tiga meja jadi enam, dan angka mati membuat skenario
    # berhenti di tengah tanpa terlihat seperti kegagalan.
    for _ in range(workflow.approvals.count() + 2):
        workflow.refresh_from_db()

        if workflow.status != InstanceStatus.PENDING:
            break

        pending = workflow.pending_approvals.select_related(
            "approver",
            "approver_employee",
        ).first()

        if pending is None or pending.approver_id is None:
            log("       ! Tidak ada approver berakun — alur berhenti.")

            break

        actor = pending.approver

        # Lewat kotak masuknya, bukan langsung ke service — inilah jalur
        # yang dilewati pengguna sungguhan, jadi kalau penyaringan kotak
        # masuk salah, skenario ini yang lebih dulu berhenti.
        in_inbox = (
            WorkflowApprovalService.pending_for(actor)
            .filter(pk=pending.pk)
            .exists()
        )

        if not in_inbox:
            log(
                f"       ! Baris #{pending.sequence} tidak muncul di kotak "
                f"masuk {actor.username} — alur berhenti."
            )

            break

        from apps.workflow.registry import completion_handler

        WorkflowService.approve(
            instance=workflow,
            user=actor,
            comment=f"Disetujui lewat kotak masuk {actor.username}.",
            on_complete=completion_handler(
                module="hr",
                document_type=document_type,
            ),
        )

        log(
            f"       ✓ #{pending.sequence} {pending.name:32} "
            f"oleh {actor.username:22} dokumen → {_status(document)}"
        )

    workflow.refresh_from_db()

    log("")
    log(
        f"     Hasil   : workflow={workflow.status}, "
        f"dokumen={_status(document)}"
    )

    return {
        "ok": True,
        "number": number,
        "workflow": workflow.status,
        "status": _status(document),
        "steps": workflow.approvals.count(),
    }


@transaction.atomic
def run(*, log=print) -> dict:
    removed = _clear_previous()

    if removed:
        log(f"  Membersihkan {removed} dokumen uji sebelumnya.")

    today = timezone.localdate()

    results = {}

    for config in SCENARIOS:
        results[config["key"]] = _run_scenario(config, today=today, log=log)

    return results
