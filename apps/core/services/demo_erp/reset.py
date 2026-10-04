"""
Pembongkar baseline dataset Meinova ERP (disetujui DEMO-1C §9).

**Yang dibongkar — transaksi baseline milik dataset, dan hanya itu:**

    instance alur + approval dokumen milik pegawai dataset
    notifikasi (lonceng + log surel) milik akun demoerp.*
    run payroll + periode payroll company milik dataset (hanya pra-finalisasi)
    presensi pegawai dataset (DEMOERP-ATT-* dan CLOSE-*)
    cuti / izin kehadiran / lembur pegawai dataset (berpenanda [DEMO-ERP:…])
    → saldo cuti dihitung ulang lewat LeaveBalanceService.recalculate_used

**Yang tidak pernah dibongkar:** company/organisasi, konfigurasi Finance
company dataset, akun & role, pegawai, PayrollAssignment, roster. Semuanya
master baseline yang ditulis ulang secara idempoten oleh penerapan — dan
kode Company tetap terkunci unique walau dihapus lunak, jadi GRP/MMN/MIN
memang tidak boleh dibuang.

**Menolak** (tanpa menulis apa pun) bila company dataset punya
AccountingEvent atau Journal dalam status apa pun, bila ada run
SUBMITTED/APPROVED/FINALIZED, atau bila ada baris milik pegawai dataset
yang tidak membawa penanda dataset (baris asing).

Penghapusan memakai `delete()` pada baris yang terbukti milik dataset —
pola yang sama dengan pembongkar HR-DEMO (`seed_hr_demo_attendance`,
`seed_hr_demo_documents`, `reset_demo_data`). Riwayat Finance tidak
pernah disentuh; kalau ada, perintah berhenti.
"""

from __future__ import annotations

from django.db.models import Q

from .constants import (
    ATTENDANCE_EXTERNAL_PREFIX,
    DOCUMENT_NOTE_PREFIX,
    OWNED_COMPANY_CODES,
    USERNAME_PREFIX,
)

#: Run yang boleh dibongkar. Sesudah submit, run punya alur hidup;
#: sesudah finalize, riwayat Finance — keduanya di luar baseline.
RESETTABLE_RUN_STATUSES = ("draft", "processing", "review", "rejected", "cancelled")

#: Dokumen alur yang dibuat baseline.
BASELINE_DOCUMENT_TYPES = ("leave_request", "attendance_permission")

CLOSING_PREFIX = "CLOSE-"


class ResetRefused(Exception):
    """Pembongkaran tidak boleh jalan. Tidak ada yang ditulis."""


def _scope():
    from apps.administration.models import Company

    from .apply import owned_employees
    from .ownership import is_owned_company

    employees = owned_employees()
    companies = [
        company for company in Company.objects.filter(code__in=OWNED_COMPANY_CODES, is_deleted=False)
        if is_owned_company(company)
    ]

    return employees, companies


def preflight() -> list[str]:
    """Alasan menolak. Kosong = boleh dibongkar. Hanya membaca."""
    from apps.finance.models import AccountingEvent, Journal
    from apps.hr.models import AttendancePermission, EmployeeAttendance, EmployeeLeave, EmployeeOvertime
    from apps.payroll.models import PayrollRun
    from apps.workflow.models import WorkflowInstance

    employees, companies = _scope()
    problems = []

    for journal in Journal.objects.filter(company__in=companies).order_by("pk"):
        problems.append(
            f"Journal {journal.pk} ({journal.company.code}, status={journal.status}) — riwayat "
            "Finance milik dataset. Tidak dihapus, tidak dibalik."
        )

    for event in AccountingEvent.objects.filter(company__in=companies).order_by("pk"):
        problems.append(
            f"AccountingEvent {event.pk} {event.event_type} status={event.status} — "
            "riwayat Finance milik dataset."
        )

    for run in PayrollRun.objects.filter(company__in=companies).exclude(
        status__in=RESETTABLE_RUN_STATUSES
    ).order_by("pk"):
        problems.append(f"PayrollRun {run.document_number} status={run.status} — di luar baseline.")

    foreign_attendance = EmployeeAttendance.objects.filter(employee__in=employees).exclude(
        Q(external_id__startswith=ATTENDANCE_EXTERNAL_PREFIX) | Q(external_id__startswith=CLOSING_PREFIX)
    )

    for row in foreign_attendance.order_by("pk")[:20]:
        problems.append(
            f"Presensi asing {row.employee.employee_number} {row.work_date} external_id="
            f"{row.external_id!r} — bukan buatan dataset."
        )

    for model, field in (
        (EmployeeLeave, "notes"),
        (AttendancePermission, "reason"),
        (EmployeeOvertime, "notes"),
    ):
        foreign = model.objects.filter(employee__in=employees).exclude(
            **{f"{field}__startswith": DOCUMENT_NOTE_PREFIX}
        )

        for row in foreign.order_by("pk")[:20]:
            problems.append(
                f"{model.__name__} asing pk={row.pk} ({row.employee.employee_number}) — tanpa "
                "penanda dataset."
            )

    other_workflows = WorkflowInstance.objects.filter(subject_employee__in=employees).exclude(
        document_type__in=BASELINE_DOCUMENT_TYPES
    )

    for instance in other_workflows.order_by("pk")[:20]:
        problems.append(
            f"WorkflowInstance {instance.pk} {instance.document_type} untuk "
            f"{instance.subject_employee.employee_number} — bukan dokumen baseline."
        )

    return problems


def execute(*, log) -> dict:
    from apps.accounts.models import User
    from apps.administration.models import Notification
    from apps.hr.api.leave.services import LeaveBalanceService
    from apps.hr.models import (
        AttendanceLog,
        AttendanceLogVerification,
        AttendancePermission,
        EmployeeAttendance,
        EmployeeLeave,
        EmployeeOvertime,
    )
    from apps.notifications.models import NotificationLog
    from apps.payroll.models import PayrollPeriod, PayrollRun
    from apps.workflow.models import WorkflowApproval, WorkflowInstance

    problems = preflight()

    if problems:
        raise ResetRefused("Pembongkaran ditolak:\n  - " + "\n  - ".join(problems))

    employees, companies = _scope()
    users = User.objects.filter(username__startswith=USERNAME_PREFIX, employee_profile__in=employees)
    counts: dict[str, int] = {}

    def remove(name, queryset):
        deleted, _ = queryset.delete()
        counts[name] = deleted
        log(f"   reset {name}: {deleted}")

    instances = WorkflowInstance.objects.filter(
        subject_employee__in=employees, document_type__in=BASELINE_DOCUMENT_TYPES,
    )
    remove("workflow.approval", WorkflowApproval.objects.filter(instance__in=instances))
    remove("workflow.instance", instances)
    remove("notification.log", NotificationLog.objects.filter(recipient__in=users))
    remove("notification.in_app", Notification.objects.filter(user__in=users))
    remove("payroll.run", PayrollRun.objects.filter(company__in=companies))
    remove("payroll.period", PayrollPeriod.objects.filter(company__in=companies))
    # Bukti verifikasi tap Self Service menunjuk log-nya dengan PROTECT dan
    # menolak `delete()` biasa; pembongkaran demo ini satu-satunya jalur
    # yang memang boleh membuangnya — dengan cakupan yang sama.
    deleted, _ = AttendanceLogVerification.objects.filter(
        log__employee__in=employees,
    ).purge_for_governed_reset()
    counts["hr.attendance_log_verification"] = deleted
    log(f"   reset hr.attendance_log_verification: {deleted}")
    remove("hr.attendance_log", AttendanceLog.objects.filter(employee__in=employees))
    remove("hr.attendance", EmployeeAttendance.objects.filter(employee__in=employees))
    remove("hr.attendance_permission", AttendancePermission.objects.filter(employee__in=employees))
    remove("hr.overtime", EmployeeOvertime.objects.filter(employee__in=employees))

    leaves = EmployeeLeave.objects.filter(employee__in=employees)
    affected = set(
        leaves.values_list("employee_id", "leave_type_id", "start_date__year")
    )
    remove("hr.leave", leaves)

    by_id = {employee.pk: employee for employee in employees}

    from apps.administration.models import LeaveType

    for employee_id, leave_type_id, year in sorted(affected):
        LeaveBalanceService.recalculate_used(
            employee=by_id[employee_id],
            leave_type=LeaveType.objects.get(pk=leave_type_id),
            year=year,
        )

    counts["leave_balance.resynced"] = len(affected)

    return counts


# ======================================================================
# Reset penuh (DEMO-1E): pegawai dataset ikut dibangun ulang dari sumber
# ======================================================================


def dataset_target():
    """EMP001–EMP040 sebagai sasaran mesin pembuangan yang sudah diaudit."""
    from .constants import EMPLOYEE_NUMBER_PATTERN
    from .legacy_cleanup import Target

    return Target(
        key="demoerp-full",
        numbers=tuple(f"EMP{n:03d}" for n in range(1, 41)),
        pattern=EMPLOYEE_NUMBER_PATTERN,
        username_prefix=USERNAME_PREFIX,
        dataset_owned=True,
    )


def execute_full(*, log) -> dict:
    """
    Pembongkar baseline (di atas) + pegawai, akun, penugasan, roster, dan
    data pribadi EMP001–EMP040 lewat `legacy_cleanup.execute`. Organisasi,
    konfigurasi Finance, dan master bersama tetap. Menolak dengan aturan
    yang sama: riwayat Finance, run lewat REVIEW, atau baris asing.
    """
    from . import legacy_cleanup

    counts = execute(log=log)
    log("   -- reset penuh: pegawai + akun dataset")
    counts.update({f"full.{k}": v for k, v in legacy_cleanup.execute(log=log, target=dataset_target()).items()})

    return counts
