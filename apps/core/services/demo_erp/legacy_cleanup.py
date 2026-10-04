"""
Pembuangan pemeran HR-DEMO lama dari tenant peragaan (DEMO-1D, 28 Sep 2026).

Disetujui eksplisit: tenant manajemen hanya memuat EMP001–EMP040 (+ TRL
teknis). Persetujuan ini **mencabut B2 untuk 30 pegawai di bawah saja** —
bukan untuk master, konfigurasi, organisasi MNI/MMR/MLS, roster policy,
RBAC, definisi alur, atau Finance.

**Sasaran = nomor pegawai persis**, bukan pola, tanggal buat, atau rentang
PK. Pegawai berpola sama di luar daftar = blocker (dataset bertambah sejak
diaudit).

**Yang dibuang — hanya milik sasaran:**

    alur + approval yang subjeknya pegawai sasaran
    notifikasi (bel + log) untuk akun sasaran atau tentang dokumen/pegawai sasaran
    jejak audit tentang baris milik sasaran
    run payroll yang seluruh barisnya pegawai sasaran (+ periode yang hanya dipakainya)
    presensi, tap mesin, pendaftaran mesin, izin, lembur, cuti, saldo cuti,
    perubahan kepegawaian, roster (rotasi, periode, versi, penyesuaian,
    kredit, setup, penugasan shift)
    pegawai (CASCADE: penempatan, kepegawaian, payroll assignment, data pribadi)
    avatar yang hanya dipakai pegawai sasaran (UploadDeleteService.purge)
    akun `demo.*` sasaran (CASCADE: role assignment + authority, favorit, layout)

**Yang sengaja tidak dihapus, tapi berubah karena `on_delete=SET_NULL`:**
`AuditTrail.user` pada jejak tentang baris yang dipertahankan dan
`RosterTravelDay.updated_by`. Nilai konfigurasinya tidak berubah.

**Menolak** (tanpa menulis apa pun) bila: ada relasi berisi yang belum
diaudit, run sasaran bercampur pegawai lain atau sudah lewat REVIEW, ada
AccountingEvent/Journal yang menunjuk run sasaran, ada pegawai non-sasaran
yang melapor ke sasaran, ada approval akun sasaran di alur non-sasaran,
atau akun sasaran bukan `demo.*` biasa.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from django.db.models import Q

@dataclass(frozen=True)
class Target:
    """Satu kelompok pegawai yang disetujui untuk dibuang."""

    key: str
    #: Daftar yang disetujui — persis, tidak diturunkan dari pola.
    numbers: tuple[str, ...]
    #: Hanya untuk mendeteksi pegawai berpola sama yang **tidak** ada di daftar.
    pattern: str
    username_prefix: str
    #: Master yang lahir khusus untuk kelompok ini: ((label model, kode), …).
    #: Dibuang sesudah pegawainya, dan hanya bila tak ada pemakai lain.
    exclusive_masters: tuple[tuple[str, str], ...] = ()
    #: DEMO-1E: sasaran = pegawai DEMOERP sendiri (reset penuh `seed_demo_erp`).
    #: Pemeriksaan "duduk di company DEMOERP" dibalik: setiap sasaran **wajib**
    #: milik dataset (tiga lapis kepemilikan). Tidak terdaftar di `TARGETS`,
    #: jadi `purge_legacy_hr_demo` tidak bisa memakainya.
    dataset_owned: bool = False


LEGACY_HR_DEMO = Target(
    key="legacy-hr-demo",
    numbers=(
        ("BOD001", "BOD002")
        + tuple(f"HO{n:03d}" for n in range(1, 10))
        + tuple(f"SGA{n:03d}" for n in range(1, 12))
        + tuple(f"LOK{n:03d}" for n in range(1, 9))
    ),
    pattern=r"^(BOD|HO|SGA|LOK)\d+$",
    username_prefix="demo.",
)

#: Dataset trial TRL-2026-09-E2E (`seed_trial_dataset`). Master eksklusifnya
#: dari manifest `var/trial/TRL-2026-09-E2E.json` (`created_exclusive_trial_objects`),
#: dicocokkan lewat kode. `PayrollLeaveRule` UNPAID se-tenant **tidak** ikut —
#: manifest menandainya keputusan sadar, dan ia berlaku untuk semua pegawai.
TRIAL = Target(
    key="trl",
    numbers=tuple(f"TRL{n:02d}" for n in range(1, 7)),
    pattern=r"^TRL",
    username_prefix="trl.",
    exclusive_masters=(
        ("payroll.OvertimeGroup", "TRL-OT-TIER"),
        ("payroll.PayrollPolicy", "TRL-DAILY"),
    ),
)

TARGETS = {target.key: target for target in (LEGACY_HR_DEMO, TRIAL)}

#: Run payroll yang boleh ikut dibuang. Sesudah submit ada alur hidup,
#: sesudah finalize ada riwayat Finance.
REMOVABLE_RUN_STATUSES = ("draft", "processing", "review", "rejected", "cancelled")

#: Relasi balik Employee yang ditangani langkah eksplisit atau CASCADE.
HANDLED_EMPLOYEE_RELATIONS = frozenset({
    ("hr.OrganizationAssignment", "employee"),
    ("hr.OrganizationAssignment", "reports_to"),  # dicek: hanya sesama sasaran
    ("hr.EmploymentAssignment", "employee"),
    ("hr.PayrollAssignment", "employee"),
    ("hr.EmployeeAction", "employee"),
    ("hr.EmployeeAction", "requested_by"),
    ("hr.EmployeeBankAccount", "employee"),
    ("hr.EmployeeFamily", "employee"),
    ("hr.EmployeeEducation", "employee"),
    ("hr.EmployeeExperience", "employee"),
    ("hr.EmployeeCertificate", "employee"),
    ("hr.EmployeeDocument", "employee"),
    ("hr.EmployeeMedicalEvent", "employee"),
    ("hr.EmployeeTraining", "employee"),
    ("hr.EmployeeLeave", "employee"),
    ("hr.LeaveBalance", "employee"),
    ("hr.LeaveOpeningBalance", "employee"),
    ("hr.EmployeeOvertime", "employee"),
    ("hr.EmployeeShiftAssignment", "employee"),
    ("hr.SiteRotation", "employee"),
    ("hr.RotationPeriod", "employee"),
    ("hr.RotationCreditTransaction", "employee"),
    ("hr.RotationCreditBalance", "employee"),
    ("hr.RosterSetupLine", "employee"),
    ("hr.RosterAdjustment", "employee"),
    ("hr.EmployeeAttendance", "employee"),
    ("hr.AttendanceDeviceEmployee", "employee"),
    ("hr.AttendanceLog", "employee"),
    ("hr.AttendancePermission", "employee"),
    ("payroll.PayrollRunEmployee", "employee"),
    ("workflow.WorkflowInstance", "subject_employee"),
    ("workflow.WorkflowApproval", "approver_employee"),  # dicek: hanya di alur sasaran
})

#: Relasi balik User yang ditangani (dibuang bersama akun atau lewat langkah eksplisit).
HANDLED_USER_RELATIONS = frozenset({
    ("accounts.RoleAssignment", "user"),
    ("administration.Notification", "user"),
    ("administration.NotificationSetting", "user"),
    ("administration.UserDashboardLayout", "user"),
    ("administration.FavoriteApp", "user"),
    ("administration.FavoriteMenu", "user"),
    ("hr.Employee", "user"),
    ("notifications.NotificationLog", "recipient"),
    ("workflow.WorkflowInstance", "submitted_by"),  # dicek: hanya alur sasaran
    ("workflow.WorkflowApproval", "approver"),
    ("workflow.WorkflowApproval", "acted_by"),
})

#: SET_NULL pada baris yang **dipertahankan** — disetujui (audit DEMO-1D).
ACCEPTED_SET_NULL = frozenset({
    ("administration.AuditTrail", "user"),
    ("administration.RosterTravelDay", "updated_by"),
})

#: Kolom jejak (created_by/updated_by/…) dianggap aman bila seluruh
#: barisnya milik pegawai sasaran — barisnya ikut terbuang.
AUDIT_COLUMNS = frozenset({"created_by", "updated_by", "deleted_by", "applied_by"})


class LegacyCleanupRefused(Exception):
    """Preflight menolak. Tidak ada yang ditulis."""


@dataclass
class Scope:
    employee_ids: list[int]
    user_ids: list[int]
    run_ids: list[int]
    period_ids: list[int]
    instance_ids: list[int]
    setup_request_ids: list[int]
    avatar_file_ids: list[int]
    target: Target = LEGACY_HR_DEMO
    found_numbers: list[str] = field(default_factory=list)
    #: {label model: [pk]} master eksklusif yang ditemukan lewat kodenya.
    master_ids: dict[str, list[int]] = field(default_factory=dict)


def _related(model):
    """Relasi balik termasuk yang tersembunyi (`related_name='+'`)."""
    return [
        rel for rel in model._meta.get_fields(include_hidden=True)
        if (rel.one_to_many or rel.one_to_one) and rel.auto_created and not rel.concrete
    ]


def build_scope(target: Target = LEGACY_HR_DEMO) -> Scope:
    from django.apps import apps

    from apps.hr.models import Employee, RosterSetupLine
    from apps.payroll.models import PayrollRun, PayrollRunEmployee
    from apps.workflow.models import WorkflowInstance

    employees = Employee._base_manager.filter(employee_number__in=target.numbers)
    employee_ids = sorted(employees.values_list("pk", flat=True))
    user_ids = sorted(u for u in employees.values_list("user_id", flat=True) if u)

    run_ids = sorted(set(
        PayrollRunEmployee._base_manager.filter(employee_id__in=employee_ids)
        .values_list("run_id", flat=True)
    ))
    period_ids = sorted(set(
        PayrollRun._base_manager.filter(pk__in=run_ids).values_list("period_id", flat=True)
    ))
    instance_ids = sorted(
        WorkflowInstance._base_manager.filter(
            Q(subject_employee_id__in=employee_ids) | Q(submitted_by_id__in=user_ids)
        ).values_list("pk", flat=True)
    )
    setup_request_ids = sorted(set(
        RosterSetupLine._base_manager.filter(employee_id__in=employee_ids)
        .values_list("request_id", flat=True)
    ))
    avatar_file_ids = sorted(
        pk for pk in employees.values_list("avatar_file_id", flat=True) if pk
    )

    return Scope(
        employee_ids=employee_ids,
        user_ids=user_ids,
        run_ids=run_ids,
        period_ids=period_ids,
        instance_ids=instance_ids,
        setup_request_ids=setup_request_ids,
        avatar_file_ids=avatar_file_ids,
        target=target,
        found_numbers=sorted(employees.values_list("employee_number", flat=True)),
        master_ids={
            label: sorted(apps.get_model(label)._base_manager.filter(code=code).values_list("pk", flat=True))
            for label, code in target.exclusive_masters
        },
    )


# ======================================================================
# Preflight
# ======================================================================


def preflight(scope: Scope) -> list[str]:
    """Alasan menolak. Kosong = boleh dibuang. Hanya membaca."""
    from django.contrib.auth import get_user_model

    from apps.administration.models import Company
    from apps.finance.models import AccountingEvent, Journal
    from apps.hr.models import Employee, OrganizationAssignment, RosterSetupLine
    from apps.payroll.models import PayrollRun, PayrollRunEmployee
    from apps.workflow.models import WorkflowApproval, WorkflowInstance

    from .constants import OWNED_COMPANY_CODES

    User = get_user_model()
    problems: list[str] = []
    employee_ids, user_ids = set(scope.employee_ids), set(scope.user_ids)

    # --- cakupan pegawai ---------------------------------------------
    target = scope.target
    stray = Employee._base_manager.filter(employee_number__regex=target.pattern).exclude(
        employee_number__in=target.numbers
    )
    for number in stray.values_list("employee_number", flat=True):
        problems.append(f"CAKUPAN: {number} berpola {target.key} tapi tidak ada di daftar persetujuan.")

    problems += _check_exclusive_masters(scope)

    if target.dataset_owned:
        from .ownership import is_owned_employee

        for employee in Employee._base_manager.filter(pk__in=employee_ids):
            if not is_owned_employee(employee):
                problems.append(f"PROVENANCE: {employee.employee_number} bukan milik dataset DEMOERP.")
    else:
        owned = OrganizationAssignment._base_manager.filter(
            employee_id__in=employee_ids, company__code__in=OWNED_COMPANY_CODES
        )
        for number in owned.values_list("employee__employee_number", flat=True):
            problems.append(f"PROVENANCE: {number} duduk di company milik DEMOERP.")

    outsiders = OrganizationAssignment._base_manager.filter(reports_to_id__in=employee_ids).exclude(
        employee_id__in=employee_ids
    )
    for number in outsiders.values_list("employee__employee_number", flat=True):
        problems.append(f"HIERARKI: {number} (bukan sasaran) melapor ke pegawai sasaran.")

    from apps.hr.models import EmployeeAction

    foreign_action = EmployeeAction._base_manager.filter(requested_by_id__in=employee_ids).exclude(
        employee_id__in=employee_ids
    )
    for action in foreign_action:
        problems.append(f"ACTION: employee action {action.pk} untuk pegawai non-sasaran diminta sasaran.")

    # --- akun ----------------------------------------------------------
    for user in User._base_manager.filter(pk__in=user_ids):
        if not user.username.startswith(target.username_prefix) or user.is_superuser or user.is_staff:
            problems.append(f"AKUN: {user.username} bukan akun data uji {target.username_prefix}* biasa.")

    shared = Employee._base_manager.filter(user_id__in=user_ids).exclude(pk__in=employee_ids)
    for number in shared.values_list("employee_number", flat=True):
        problems.append(f"AKUN: akun sasaran juga dipakai {number}.")

    # --- payroll + Finance -----------------------------------------------
    mixed = PayrollRunEmployee._base_manager.filter(run_id__in=scope.run_ids).exclude(
        employee_id__in=employee_ids
    )
    for run_id in sorted(set(mixed.values_list("run_id", flat=True))):
        problems.append(f"PAYROLL: run {run_id} memuat pegawai di luar sasaran.")

    for run in PayrollRun._base_manager.filter(pk__in=scope.run_ids).exclude(
        status__in=REMOVABLE_RUN_STATUSES
    ):
        problems.append(f"PAYROLL: {run.document_number} status={run.status} — di luar pra-finalisasi.")

    other_runs = PayrollRun._base_manager.filter(period_id__in=scope.period_ids).exclude(
        pk__in=scope.run_ids
    )
    for run in other_runs:
        problems.append(f"PAYROLL: periode {run.period_id} juga dipakai {run.document_number}.")

    run_keys = [str(pk) for pk in scope.run_ids]
    for model in (AccountingEvent, Journal):
        linked = model._base_manager.filter(source_module="payroll", source_id__in=run_keys)
        for row in linked:
            problems.append(f"FINANCE: {model.__name__} {row.pk} menunjuk run sasaran {row.source_id}.")

    # --- alur -----------------------------------------------------------
    foreign_subject = WorkflowInstance._base_manager.filter(pk__in=scope.instance_ids).exclude(
        subject_employee_id__in=employee_ids
    )
    for instance in foreign_subject:
        problems.append(f"ALUR: instance {instance.pk} diajukan akun sasaran untuk subjek lain.")

    foreign_approval = WorkflowApproval._base_manager.filter(
        Q(approver_id__in=user_ids) | Q(acted_by_id__in=user_ids) | Q(approver_employee_id__in=employee_ids)
    ).exclude(instance_id__in=scope.instance_ids)
    for approval in foreign_approval:
        problems.append(f"ALUR: approval {approval.pk} milik sasaran pada instance {approval.instance_id} non-sasaran.")

    mixed_setup = RosterSetupLine._base_manager.filter(request_id__in=scope.setup_request_ids).exclude(
        employee_id__in=employee_ids
    )
    for request_id in sorted(set(mixed_setup.values_list("request_id", flat=True))):
        problems.append(f"ROSTER: setup {request_id} memuat baris pegawai di luar sasaran.")

    # --- relasi yang belum diaudit ----------------------------------------
    problems += _unaudited(Employee, employee_ids, HANDLED_EMPLOYEE_RELATIONS, employee_ids)
    problems += _unaudited(User, user_ids, HANDLED_USER_RELATIONS, employee_ids)

    return problems


def _check_exclusive_masters(scope: Scope) -> list[str]:
    """
    Master eksklusif hanya boleh dipakai baris yang ikut terbuang. Relasi
    ditemukan dari metadata; pemakai di luar pegawai sasaran = blocker.
    """
    from django.apps import apps

    problems = []

    for label, code in scope.target.exclusive_masters:
        ids = scope.master_ids.get(label, [])

        if len(ids) > 1:
            problems.append(f"MASTER: {label} {code} ada {len(ids)} baris — kode tidak unik.")

        model = apps.get_model(label)

        for rel in _related(model):
            related_model, name = rel.related_model, rel.field.name
            rows = related_model._base_manager.filter(**{f"{name}__in": ids})

            if not rows.exists():
                continue

            if rel.field.remote_field.on_delete.__name__ == "CASCADE" and related_model._meta.label.startswith(label):
                continue  # baris anak master itu sendiri (tingkat lembur)

            has_employee = any(f.name == "employee" for f in related_model._meta.fields)
            if has_employee and not rows.exclude(employee_id__in=scope.employee_ids).exists():
                continue

            problems.append(
                f"MASTER: {label} {code} dipakai {rows.count()} baris "
                f"{related_model._meta.label}.{name} di luar pegawai sasaran."
            )

    return problems


def _unaudited(model, ids, handled, employee_ids) -> list[str]:
    from apps.hr.models import Employee

    problems = []

    if not ids:
        return problems

    for rel in _related(model):
        related_model = rel.related_model
        name = rel.field.name
        key = (related_model._meta.label, name)
        rows = related_model._base_manager.filter(**{f"{name}__in": ids})

        if key in handled or key in ACCEPTED_SET_NULL or not rows.exists():
            continue

        if name in AUDIT_COLUMNS:
            if related_model is Employee and not rows.exclude(pk__in=employee_ids).exists():
                continue

            owner = [
                f.name for f in related_model._meta.fields
                if f.is_relation and f.related_model is Employee and f.name == "employee"
            ]
            if owner and not rows.exclude(employee_id__in=employee_ids).exists():
                continue

        problems.append(
            f"DEPENDENCY BARU: {key[0]}.{name} memuat {rows.count()} baris yang menunjuk "
            f"{model.__name__} sasaran — belum diaudit."
        )

    return problems


# ======================================================================
# Eksekusi
# ======================================================================


def execute(*, log, target: Target = LEGACY_HR_DEMO) -> dict[str, int]:
    """Dipanggil di dalam `transaction.atomic()` pemanggil."""
    from django.contrib.auth import get_user_model

    from apps.administration.models import AuditTrail, Notification
    from apps.hr.models import (
        AttendanceDeviceEmployee,
        AttendanceLog,
        AttendanceLogVerification,
        AttendancePermission,
        Employee,
        EmployeeAction,
        EmployeeAttendance,
        EmployeeLeave,
        EmployeeOvertime,
        EmployeeShiftAssignment,
        LeaveBalance,
        LeaveOpeningBalance,
        RosterAdjustment,
        RosterPlanVersion,
        RosterSetupLine,
        RosterSetupRequest,
        RotationCreditBalance,
        RotationCreditTransaction,
        RotationPeriod,
        SiteRotation,
    )
    from apps.notifications.models import NotificationLog
    from apps.payroll.models import PayrollPeriod, PayrollRun
    from apps.uploads.models import UploadedFile
    from apps.uploads.services.delete_service import UploadDeleteService
    from apps.workflow.models import WorkflowApproval, WorkflowInstance

    User = get_user_model()
    scope = build_scope(target)
    problems = preflight(scope)

    if problems:
        raise LegacyCleanupRefused("Pembuangan ditolak:\n  - " + "\n  - ".join(problems))

    emp = scope.employee_ids
    counts: dict[str, int] = {}

    # Penunjuk tanpa FK (alur, notifikasi, audit) dicatat sebelum barisnya hilang.
    instances = WorkflowInstance._base_manager.filter(pk__in=scope.instance_ids)
    document_keys = Q()
    for module, document_type, object_id in instances.values_list("module", "document_type", "object_id"):
        document_keys |= Q(object_type=f"{module}-{document_type}", object_id=object_id)
    document_keys |= Q(object_type__startswith="employee-", object_id__in=[str(pk) for pk in emp])
    document_keys |= Q(object_type="hr-roster_setup", object_id__in=[str(pk) for pk in scope.setup_request_ids])

    owned_models = {
        EmployeeAttendance: Q(employee_id__in=emp),
        EmployeeLeave: Q(employee_id__in=emp),
        AttendancePermission: Q(employee_id__in=emp),
        EmployeeOvertime: Q(employee_id__in=emp),
        EmployeeAction: Q(employee_id__in=emp),
        EmployeeShiftAssignment: Q(employee_id__in=emp),
        LeaveOpeningBalance: Q(employee_id__in=emp),
        LeaveBalance: Q(employee_id__in=emp),
        RosterSetupLine: Q(employee_id__in=emp),
        RosterSetupRequest: Q(pk__in=scope.setup_request_ids),
        RotationPeriod: Q(employee_id__in=emp),
        SiteRotation: Q(employee_id__in=emp),
        RosterAdjustment: Q(employee_id__in=emp),
        Employee: Q(pk__in=emp),
        PayrollRun: Q(pk__in=scope.run_ids),
        PayrollPeriod: Q(pk__in=scope.period_ids),
    }
    audit_keys = Q(pk__in=[])
    for model, condition in owned_models.items():
        ids = [str(pk) for pk in model._base_manager.filter(condition).values_list("pk", flat=True)]
        if ids:
            audit_keys |= Q(module=model._meta.app_label, object_type=model._meta.model_name, object_id__in=ids)

    def remove(name, queryset):
        deleted, _ = queryset.delete()
        counts[name] = deleted
        log(f"   {name:34} {deleted}")

    remove("workflow.approval", WorkflowApproval._base_manager.filter(instance_id__in=scope.instance_ids))
    remove("workflow.instance", instances)
    remove("notification.log", NotificationLog._base_manager.filter(Q(recipient_id__in=scope.user_ids) | document_keys))
    remove("notification.in_app", Notification._base_manager.filter(Q(user_id__in=scope.user_ids) | document_keys))
    remove("audit_trail (baris milik sasaran)", AuditTrail._base_manager.filter(audit_keys))

    # Payroll: run (CASCADE baris + komponen) lalu periode yang hanya dipakainya.
    remove("payroll.run (+baris, komponen)", PayrollRun._base_manager.filter(pk__in=scope.run_ids))
    remove("payroll.period", PayrollPeriod._base_manager.filter(pk__in=scope.period_ids))

    # Dokumen & presensi (PROTECT ke pegawai).
    remove("hr.attendance_permission", AttendancePermission._base_manager.filter(employee_id__in=emp))
    remove("hr.employee_action", EmployeeAction._base_manager.filter(
        Q(employee_id__in=emp) | Q(requested_by_id__in=emp)
    ))
    remove("hr.overtime", EmployeeOvertime._base_manager.filter(employee_id__in=emp))
    # Bukti verifikasi tap Self Service (PROTECT ke log, `delete()` biasa
    # ditolak) — dibuang lewat jalur pembongkaran yang dijaga, cakupan sama.
    deleted, _ = AttendanceLogVerification.objects.filter(
        log__employee_id__in=emp,
    ).purge_for_governed_reset()
    counts["hr.attendance_log_verification"] = deleted
    log(f"   {'hr.attendance_log_verification':34} {deleted}")
    remove("hr.attendance_log", AttendanceLog._base_manager.filter(employee_id__in=emp))
    remove("hr.attendance", EmployeeAttendance._base_manager.filter(employee_id__in=emp))
    remove("hr.attendance_device_employee", AttendanceDeviceEmployee._base_manager.filter(employee_id__in=emp))

    # Roster: ledger dulu, lalu rencana (versi & periode ikut CASCADE).
    remove("hr.rotation_credit_transaction", RotationCreditTransaction._base_manager.filter(employee_id__in=emp))
    remove("hr.rotation_credit_balance", RotationCreditBalance._base_manager.filter(employee_id__in=emp))
    remove("hr.roster_adjustment", RosterAdjustment._base_manager.filter(employee_id__in=emp))
    remove("hr.rotation_period", RotationPeriod._base_manager.filter(employee_id__in=emp))
    remove("hr.roster_plan_version", RosterPlanVersion._base_manager.filter(plan__employee_id__in=emp))
    remove("hr.site_rotation", SiteRotation._base_manager.filter(employee_id__in=emp))
    remove("hr.roster_setup_line", RosterSetupLine._base_manager.filter(employee_id__in=emp))
    remove("hr.roster_setup_request", RosterSetupRequest._base_manager.filter(pk__in=scope.setup_request_ids))
    remove("hr.shift_assignment", EmployeeShiftAssignment._base_manager.filter(employee_id__in=emp))

    # Cuti sesudah alurnya.
    remove("hr.leave", EmployeeLeave._base_manager.filter(employee_id__in=emp))
    remove("hr.leave_opening_balance", LeaveOpeningBalance._base_manager.filter(employee_id__in=emp))
    remove("hr.leave_balance", LeaveBalance._base_manager.filter(employee_id__in=emp))

    # Pegawai: CASCADE penempatan, kepegawaian, payroll assignment, data pribadi.
    remove("hr.employee (+cascade)", Employee._base_manager.filter(pk__in=emp))

    # Avatar yang hanya dipakai sasaran. Berkas fisik dihapus on_commit.
    purged = 0
    for upload in UploadedFile._base_manager.filter(pk__in=scope.avatar_file_ids):
        UploadDeleteService.purge(instance=upload)
        purged += 1
    counts["uploads.avatar"] = purged
    log(f"   {'uploads.avatar':34} {purged}")

    # Akun: CASCADE role assignment + authority, favorit, layout, setelan.
    remove("account.user (+cascade)", User._base_manager.filter(pk__in=scope.user_ids))

    # Master eksklusif paling akhir, sesudah seluruh pemakainya hilang.
    from django.apps import apps

    for label, ids in scope.master_ids.items():
        model = apps.get_model(label)
        remove(f"{label} (+cascade)", model._base_manager.filter(pk__in=ids))
        remove(
            f"audit_trail {model._meta.model_name}",
            AuditTrail._base_manager.filter(
                module=model._meta.app_label, object_type=model._meta.model_name,
                object_id__in=[str(pk) for pk in ids],
            ),
        )

    return counts


def orphan_check(scope: Scope) -> list[str]:
    """Seluruh kolom FK di schema aktif yang masih menunjuk ID yang dibuang."""
    from django.db import connection

    targets = {"hr_employee": scope.employee_ids, "auth_users": scope.user_ids}
    found = []

    with connection.cursor() as cursor:
        cursor.execute(
            """
            select kcu.table_name, kcu.column_name, ccu.table_name
              from information_schema.table_constraints tc
              join information_schema.key_column_usage kcu
                on tc.constraint_name = kcu.constraint_name and tc.table_schema = kcu.table_schema
              join information_schema.constraint_column_usage ccu
                on ccu.constraint_name = tc.constraint_name and ccu.table_schema = tc.table_schema
             where tc.table_schema = current_schema() and tc.constraint_type = 'FOREIGN KEY'
               and ccu.table_name = any(%s)
            """,
            [list(targets)],
        )
        columns = cursor.fetchall()

        for table, column, referenced in columns:
            ids = targets[referenced]
            if not ids:
                continue
            cursor.execute(f'select count(*) from "{table}" where "{column}" = any(%s)', [ids])
            count = cursor.fetchone()[0]
            if count:
                found.append(f"{table}.{column} -> {referenced}: {count}")

        employee_keys = [str(pk) for pk in scope.employee_ids]
        for table, condition in (
            ("master_notification", "object_type like 'employee-%%' and object_id = any(%s)"),
            ("notification_log", "object_type like 'employee-%%' and object_id = any(%s)"),
            ("master_audit_trail", "module = 'hr' and object_type = 'employee' and object_id = any(%s)"),
        ):
            cursor.execute(f"select count(*) from {table} where {condition}", [employee_keys])
            count = cursor.fetchone()[0]
            if count:
                found.append(f"{table} (penunjuk teks ke pegawai sasaran): {count}")

    return found
