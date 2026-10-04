"""
Dokumen HR peragaan manajemen — pelaksana, HR-DEMO-3.

Lima langkah, semuanya lewat jalur yang sama dengan data sungguhan:

1. **Konfigurasi** — aturan perlakuan izin dan tingkat lembur sebagai
   **master**, bukan sebagai perilaku yang ditanam di seed.
2. **Cuti** — dibuat pengaju, diajukan pengaju, diputuskan approver yang
   benar-benar diresolusi mesin alur.
3. **Izin Kehadiran** — jalur yang sama, lalu klasifikasi presensinya
   dihitung ulang service izin itu sendiri.
4. **Lembur** — dicatat lewat service-nya. **Tanpa alur persetujuan**,
   karena alurnya memang tidak ada.
5. **Bukti B** — satu baris kesimpulan penutup hari dibongkar lalu
   diterbitkan ulang, supaya perilaku penutup yang sadar cuti bisa
   dilihat sendiri.

Yang tidak dilakukan berkas ini: menetapkan status akhir langsung kalau
ada aksi sungguhan yang menghasilkannya. Cuti yang "disetujui" harus
melewati meja approver-nya; kalau tidak, yang teruji cuma kolom status.
"""

from __future__ import annotations

from datetime import date as date_cls

from django.db import transaction

from apps.hr.api.attendance.closing import AttendanceClosingService
from apps.hr.api.attendance_permission.services import (
    AttendancePermissionService,
)
from apps.hr.api.leave.services import EmployeeLeaveService
from apps.hr.api.overtime.services import EmployeeOvertimeService
from apps.hr.models import (
    AttendancePermission,
    Employee,
    EmployeeAttendance,
    EmployeeLeave,
    EmployeeOvertime,
)
from apps.hr.models.leave import LeaveStatus
from apps.hr.seeds.hr_demo_documents import (
    LEAVE_SCENARIOS,
    OVERTIME_GROUP_CODE,
    OVERTIME_GROUP_EMPLOYEES,
    OVERTIME_SCENARIOS,
    OVERTIME_TIER_BASIS,
    OVERTIME_TIERS,
    PERMISSION_RULES,
    PERMISSION_SCENARIOS,
    PROOF_B,
)
from apps.workflow.models import InstanceStatus
from apps.workflow.registry import completion_handler
from apps.workflow.services.workflow_service import WorkflowService


# Meja yang mengambil keputusan menolak pada rantai site: atasan
# langsung. Meja sebelumnya menyiapkan dan memeriksa kelengkapan — itu
# bukan meja yang menilai layak atau tidaknya seseorang cuti.
REJECT_AT_SEQUENCE = 3


# ======================================================================
# 0. Pembongkaran — hanya milik fase ini
# ======================================================================


def purge(*, plan, log) -> dict:
    """
    Membuang dokumen yang dibuat fase ini, supaya bisa dijalankan ulang.

    Penyaringnya **pegawai + tanggal skenario**, bukan seluruh tabel:
    dokumen yang diketik orang di tanggal lain tidak pernah bisa
    dibangun ulang seed mana pun.
    """
    leave_keys = [
        (s.employee_number, s.start, s.end) for s in LEAVE_SCENARIOS
    ]

    permission_keys = [
        (s.employee_number, s.work_date) for s in PERMISSION_SCENARIOS
    ]

    overtime_keys = [
        (s.employee_number, s.work_date) for s in OVERTIME_SCENARIOS
    ]

    removed = {"leave": 0, "permission": 0, "overtime": 0, "workflow": 0}

    from apps.workflow.models import WorkflowInstance

    for number, start, end in leave_keys:
        rows = EmployeeLeave.objects.filter(
            employee__employee_number=number,
            start_date=start,
            end_date=end,
        )

        for row in rows:
            removed["workflow"] += WorkflowInstance.objects.filter(
                module="hr",
                document_type="leave_request",
                object_id=str(row.pk),
            ).delete()[0]

        removed["leave"] += rows.delete()[0]

    for number, work_date in permission_keys:
        rows = AttendancePermission.objects.filter(
            employee__employee_number=number,
            date=work_date,
        )

        for row in rows:
            removed["workflow"] += WorkflowInstance.objects.filter(
                module="hr",
                document_type="attendance_permission",
                object_id=str(row.pk),
            ).delete()[0]

        removed["permission"] += rows.delete()[0]

    for number, work_date in overtime_keys:
        removed["overtime"] += EmployeeOvertime.objects.filter(
            employee__employee_number=number,
            work_date=work_date,
        ).delete()[0]

    log(
        f"  dibongkar: {removed['leave']} cuti, "
        f"{removed['permission']} izin, {removed['overtime']} lembur, "
        f"{removed['workflow']} baris alur",
    )

    return removed


# ======================================================================
# 1. Konfigurasi kanonik
# ======================================================================


def configure(*, log, user=None) -> dict:
    from apps.hr.models import PayrollAssignment
    from apps.payroll.models import (
        OvertimeGroup,
        OvertimeGroupTier,
        PayrollPermissionRule,
    )

    rules = 0

    for permission_type, treatment, unpaid_over in PERMISSION_RULES:
        _, created = PayrollPermissionRule.objects.update_or_create(
            company=None,
            payroll_policy=None,
            permission_type=permission_type,
            is_deleted=False,
            defaults={
                "treatment": treatment,
                "unpaid_over_minutes": unpaid_over,
                "is_active": True,
                "notes": (
                    "HR-DEMO-3 — konfigurasi kanonik perlakuan izin."
                ),
            },
        )

        rules += 1

    group = OvertimeGroup.objects.get(
        code=OVERTIME_GROUP_CODE, is_deleted=False,
    )

    if group.tier_basis != OVERTIME_TIER_BASIS:
        group.tier_basis = OVERTIME_TIER_BASIS

        group.save(update_fields=["tier_basis", "updated_at"])

    tiers = 0

    for sequence, hour_from, hour_to, multiplier in OVERTIME_TIERS:
        tier, _ = OvertimeGroupTier.objects.update_or_create(
            group=group,
            sequence=sequence,
            is_deleted=False,
            defaults={
                "hour_from": hour_from,
                "hour_to": hour_to,
                "multiplier": multiplier,
                "is_active": True,
                "description": (
                    "HR-DEMO-3 — tingkat lembur site kanonik."
                ),
            },
        )

        tier.full_clean()

        tiers += 1

    assigned = 0

    for row in (
        PayrollAssignment.objects
        .filter(
            is_deleted=False,
            employee__employee_number__in=OVERTIME_GROUP_EMPLOYEES,
        )
        .select_related("employee")
    ):
        # Kelayakan **tidak** disimpulkan dari lokasi. Yang belum
        # dinyatakan berhak lembur dilewati, bukan dinyatakan berhak
        # diam-diam supaya angka peragaannya bulat.
        if not row.overtime_eligible:
            continue

        if row.overtime_group_id == group.pk:
            continue

        row.overtime_group = group
        row.updated_by = user

        row.save(
            update_fields=["overtime_group", "updated_by", "updated_at"],
        )

        assigned += 1

    log(
        f"  konfigurasi: {rules} aturan izin, {tiers} tingkat lembur, "
        f"{assigned} penempatan kelompok lembur",
    )

    return {"rules": rules, "tiers": tiers, "assigned": assigned}


# ======================================================================
# Menjalankan alur dengan approver yang sungguhan
# ======================================================================


def _run_workflow(
    *,
    workflow,
    decision: str,
    log,
    comment: str = "",
    reject_at_sequence: int | None = None,
    document_type: str,
) -> list:
    """
    Menjalankan seluruh meja yang tersisa, masing-masing oleh orang yang
    memang diresolusi mesin alur untuk meja itu.

    Bukan superuser. Mesin memang mengizinkan superuser memutuskan
    apa pun — jaring supaya tenant yang datanya belum lengkap tidak
    terkunci — tapi memakainya di sini berarti yang teruji cuma jalan
    pintasnya, dan rantai enam meja site tidak pernah benar-benar
    dijalani siapa pun.
    """
    # Handler penutup **wajib dioper tiap keputusan**, persis seperti
    # yang dilakukan layarnya. `submit()` cuma mengopernya untuk
    # penutupan otomatis saat alurnya kosong; keputusan berikutnya yang
    # tidak membawanya akan memindahkan alur tanpa memindahkan status
    # dokumennya — dan gagalnya diam.
    on_complete = completion_handler(
        module="hr",
        document_type=document_type,
    )

    trail = []
    guard = 0

    while workflow.status == InstanceStatus.PENDING and guard < 12:
        guard += 1

        approval = (
            workflow.pending_approvals
            .select_related("step", "approver", "approver_employee")
            .first()
        )

        if approval is None or approval.approver is None:
            trail.append(
                (
                    getattr(getattr(approval, "step", None), "name", "?"),
                    None,
                    "approver tidak ketemu",
                ),
            )

            break

        actor = approval.approver

        # Penolakan diambil di meja yang memang memutuskan, bukan di
        # meja pertama yang kebetulan ditemukan. Rantai enam meja site
        # dimulai dari "Prepared By" — penolakan di sana menggambarkan
        # keputusan yang tidak pernah diambil siapa pun di lapangan.
        rejecting = (
            decision == "reject"
            and (
                reject_at_sequence is None
                or approval.step.sequence >= reject_at_sequence
            )
        )

        handler = (
            WorkflowService.reject
            if rejecting
            else WorkflowService.approve
        )

        handler(
            instance=workflow,
            user=actor,
            comment=comment if rejecting else "Diteruskan.",
            on_complete=on_complete,
        )

        trail.append(
            (
                approval.step.name,
                actor.username,
                "reject" if rejecting else "approve",
            ),
        )

        workflow.refresh_from_db()

        if rejecting:
            break

    return trail


# ======================================================================
# 2. Cuti
# ======================================================================


def create_leave(*, plan, log, hr_user=None) -> list:
    from apps.administration.models.references.hr import LeaveType

    types = {
        row.code: row
        for row in LeaveType.objects.filter(is_deleted=False)
    }

    results = []

    for scenario in LEAVE_SCENARIOS:
        employee = Employee.objects.select_related("user").get(
            employee_number=scenario.employee_number, is_deleted=False,
        )

        requester = employee.user

        payload = {
            "employee": employee,
            "leave_type": types[scenario.leave_type],
            "start_date": scenario.start,
            "end_date": scenario.end,
            "is_half_day": scenario.is_half_day,
            "notes": scenario.reason,
        }

        trail = []

        if scenario.target in (LeaveStatus.RECORDED, LeaveStatus.CANCELLED):
            # Jalur pencatatan: HR menyatakan cuti yang sudah terjadi.
            # Tidak lewat alur sama sekali — dan itu memang bedanya.
            leave = EmployeeLeaveService.create(
                data={**payload, "status": LeaveStatus.RECORDED},
                user=hr_user,
            )

            trail.append(("Dicatat HR", getattr(hr_user, "username", None), "recorded"))

            if scenario.target == LeaveStatus.CANCELLED:
                # Aksi pembatalan dokumen — **bukan** membatalkan
                # instance alurnya. Yang kedua mengembalikan dokumen ke
                # DRAFT, dan itu semantik yang berbeda.
                EmployeeLeaveService.set_status(
                    instance=leave,
                    status=LeaveStatus.CANCELLED,
                    user=hr_user,
                )

                trail.append(
                    ("Dibatalkan HR", getattr(hr_user, "username", None), "cancelled"),
                )
        else:
            leave = EmployeeLeaveService.create(
                data={**payload, "status": LeaveStatus.DRAFT},
                user=requester,
            )

            if scenario.target != LeaveStatus.DRAFT:
                workflow = EmployeeLeaveService.submit(
                    instance=leave,
                    user=requester,
                    notes=scenario.reason,
                )

                trail.append(
                    ("Diajukan", getattr(requester, "username", None), "submitted"),
                )

                if scenario.target == LeaveStatus.APPROVED:
                    trail += _run_workflow(
                        workflow=workflow, decision="approve", log=log,
                        comment="Disetujui.",
                        document_type="leave_request",
                    )
                elif scenario.target == LeaveStatus.REJECTED:
                    trail += _run_workflow(
                        workflow=workflow, decision="reject", log=log,
                        reject_at_sequence=REJECT_AT_SEQUENCE,
                        document_type="leave_request",
                        comment=(
                            "Beban kerja regu sedang puncak; ajukan "
                            "ulang setelah blok kerja ini selesai."
                        ),
                    )

        leave.refresh_from_db()

        results.append({
            "key": scenario.key,
            "document": leave.document_number,
            "employee": scenario.employee_number,
            "type": scenario.leave_type,
            "status": leave.status,
            "target": scenario.target,
            "days": leave.total_days,
            "trail": trail,
        })

        log(
            f"  {scenario.key} {scenario.employee_number} "
            f"{scenario.leave_type} {leave.status} "
            f"({leave.total_days} hari)",
        )

    return results


# ======================================================================
# 3. Izin Kehadiran
# ======================================================================


def create_permissions(*, plan, log) -> list:
    results = []

    for scenario in PERMISSION_SCENARIOS:
        employee = Employee.objects.select_related("user").get(
            employee_number=scenario.employee_number, is_deleted=False,
        )

        requester = employee.user

        permission = AttendancePermissionService.create(
            data={
                "employee": employee,
                "date": scenario.work_date,
                "permission_type": scenario.permission_type,
                "start_time": scenario.start_time,
                "end_time": scenario.end_time,
                "reason": scenario.reason,
            },
            user=requester,
        )

        workflow = AttendancePermissionService.submit(
            permission=permission,
            user=requester,
        )

        trail = [("Diajukan", getattr(requester, "username", None), "submitted")]

        trail += _run_workflow(
            workflow=workflow, decision="approve", log=log,
            comment="Disetujui.",
            document_type="attendance_permission",
        )

        permission.refresh_from_db()

        results.append({
            "key": scenario.key,
            "document": permission.document_number,
            "employee": scenario.employee_number,
            "date": scenario.work_date,
            "type": scenario.permission_type,
            "status": permission.status,
            "trail": trail,
        })

        log(
            f"  {scenario.key} {scenario.employee_number} "
            f"{scenario.work_date} {scenario.permission_type} "
            f"{permission.status}",
        )

    return results


# ======================================================================
# 4. Lembur
# ======================================================================


def create_overtime(*, plan, log, user=None) -> list:
    results = []

    for scenario in OVERTIME_SCENARIOS:
        employee = Employee.objects.get(
            employee_number=scenario.employee_number, is_deleted=False,
        )

        overtime = EmployeeOvertimeService.create(
            data={
                "employee": employee,
                "work_date": scenario.work_date,
                "start_time": scenario.start_time,
                "end_time": scenario.end_time,
                "status": scenario.status,
                "is_paid": scenario.is_paid,
                "reason": scenario.reason,
            },
            user=user,
        )

        results.append({
            "key": scenario.key,
            "employee": scenario.employee_number,
            "date": scenario.work_date,
            "minutes": overtime.duration_minutes,
            "hours": overtime.duration_hours,
            "status": overtime.status,
            "is_paid": overtime.is_paid,
        })

        log(
            f"  {scenario.key} {scenario.employee_number} "
            f"{scenario.work_date} {overtime.duration_minutes}m "
            f"{overtime.status} paid={overtime.is_paid}",
        )

    return results


# ======================================================================
# 5. Bukti B — penutup hari yang sadar cuti
# ======================================================================


def proof_b(*, log, user=None) -> dict:
    """
    Membongkar **satu** baris kesimpulan penutup hari lalu
    menerbitkannya ulang.

    Yang dibongkar bukan bukti: baris mangkir tidak punya tap sama
    sekali, dan `AttendanceLog` tidak disentuh. Yang dibongkar sebuah
    **kesimpulan** — dan kesimpulan yang dibuat sebelum cutinya ada
    memang sudah bukan kesimpulan yang benar.

    Pagarnya diperiksa di sini, bukan dipercayakan ke pemanggil: baris
    yang bukan buatan penutup hari, yang punya jam tap, atau yang di
    luar jendela, menghentikan langkah ini.
    """
    employee = Employee.objects.select_related(
        "organization__company", "organization__location",
        "employment__employee_group",
        "employment__roster_crew__work_schedule",
        "employment__working_calendar", "employment__shift",
    ).get(employee_number=PROOF_B["employee_number"], is_deleted=False)

    work_date: date_cls = PROOF_B["work_date"]

    row = EmployeeAttendance.objects.filter(
        employee=employee, work_date=work_date, is_deleted=False,
    ).first()

    if row is None:
        raise RuntimeError(
            f"Bukti B: baris {employee.employee_number} {work_date} "
            f"tidak ada.",
        )

    if not (row.external_id or "").startswith("CLOSE-"):
        raise RuntimeError(
            f"Bukti B: baris {row.external_id!r} bukan kesimpulan "
            f"penutup hari. Dibatalkan.",
        )

    if row.check_in is not None or row.check_out is not None:
        raise RuntimeError(
            "Bukti B: baris ini memuat jam tap. Bukti mentah tidak "
            "pernah dibongkar. Dibatalkan.",
        )

    from apps.hr.api.attendance.schedule import scheduled_work_days

    before = {
        "status": row.status,
        "source": row.source,
        "external_id": row.external_id,
        "check_in": row.check_in,
        "check_out": row.check_out,
        "scheduled": work_date in scheduled_work_days(
            employee, work_date, work_date,
        ),
        "leave_approved": EmployeeLeave.objects.filter(
            employee=employee,
            status__in=[LeaveStatus.APPROVED, LeaveStatus.RECORDED],
            start_date__lte=work_date,
            end_date__gte=work_date,
            is_deleted=False,
        ).exists(),
    }

    if not before["leave_approved"]:
        raise RuntimeError(
            "Bukti B: cuti yang disetujui belum ada untuk tanggal ini. "
            "Dibatalkan.",
        )

    row.delete()

    gone = not EmployeeAttendance.objects.filter(
        employee=employee, work_date=work_date, is_deleted=False,
    ).exists()

    result = AttendanceClosingService.close(
        start=work_date,
        end=work_date,
        employees=[employee.id],
        user=user,
    )

    after_row = EmployeeAttendance.objects.filter(
        employee=employee, work_date=work_date, is_deleted=False,
    ).first()

    after = {
        "status": getattr(after_row, "status", None),
        "source": getattr(after_row, "source", None),
        "external_id": getattr(after_row, "external_id", None),
        "check_in": getattr(after_row, "check_in", None),
        "check_out": getattr(after_row, "check_out", None),
        "notes": getattr(after_row, "notes", ""),
    }

    log(
        f"  bukti B: {employee.employee_number} {work_date} "
        f"{before['status']} -> {after['status']} "
        f"(closing: {result['absent']} mangkir, {result['leave']} cuti)",
    )

    return {
        "employee": employee.employee_number,
        "work_date": work_date,
        "before": before,
        "row_absent_between": gone,
        "closing": result,
        "after": after,
    }


# ======================================================================
# Orkestrasi
# ======================================================================


@transaction.atomic
def run(*, plan, log, hr_user=None) -> dict:
    if plan.is_blocked:
        raise RuntimeError("Rencana masih terhalang. Tidak ada yang dijalankan.")

    return {
        "purged": purge(plan=plan, log=log),
        "config": configure(log=log, user=hr_user),
        "leave": create_leave(plan=plan, log=log, hr_user=hr_user),
        "permission": create_permissions(plan=plan, log=log),
        "overtime": create_overtime(plan=plan, log=log, user=hr_user),
        "proof_b": proof_b(log=log, user=hr_user),
    }
