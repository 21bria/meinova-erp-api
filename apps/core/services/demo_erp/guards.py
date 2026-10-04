"""
Pagar tenant dan sidik jari data yang dilindungi.

**Rumus sidik jari** (supaya angkanya bisa dibandingkan ulang oleh siapa
pun, bukan cuma oleh kode ini):

    rows   = list(QS.order_by("pk").values_list(*kolom))
    sha256 = hashlib.sha256(
        json.dumps(rows, default=str, sort_keys=True).encode()
    ).hexdigest()

`kolom` = seluruh kolom konkret model **kecuali** `updated_at` dan
`last_login`. Keduanya berubah karena hal yang bukan isi — upsert yang
menulis nilai yang sama, atau orang yang login — dan sidik jari di sini
menjawab "apakah isinya berubah", bukan "apakah barisnya disentuh".
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from django.conf import settings
from django.db import connection
from django.db.models import Q, QuerySet
from django_tenants.utils import get_public_schema_name, get_tenant_model

from .constants import (
    ALLOWED_TENANTS,
    OWNED_COMPANY_CODES,
    PROTECTED_COMPANY_CODES,
    PROTECTED_EMPLOYEE_PREFIXES,
    USERNAME_PREFIX,
)


class DemoGuardError(Exception):
    """Perintah harus berhenti sebelum membaca apa pun dari tenant."""


EXCLUDED_DIGEST_COLUMNS = frozenset({"updated_at", "last_login"})


# ======================================================================
# Tenant
# ======================================================================


def allowed_tenants() -> frozenset[str]:
    """Bisa dipersempit/diganti lewat settings (test memakainya)."""
    return frozenset(getattr(settings, "DEMO_ERP_ALLOWED_TENANTS", ALLOWED_TENANTS))


def resolve_tenant(schema_name: str | None):
    if not schema_name:
        raise DemoGuardError("--tenant wajib disebut. Tidak ada tenant bawaan.")

    if schema_name == get_public_schema_name():
        raise DemoGuardError("Schema public ditolak: dataset peragaan milik tenant.")

    if schema_name not in allowed_tenants():
        raise DemoGuardError(
            f"Tenant {schema_name!r} tidak diizinkan untuk dataset ini "
            f"(yang diizinkan: {', '.join(sorted(allowed_tenants()))})."
        )

    tenant = get_tenant_model().objects.filter(schema_name=schema_name).first()

    if tenant is None:
        raise DemoGuardError(f"Tenant {schema_name!r} tidak ditemukan.")

    return tenant


def verify_active_schema(tenant) -> str:
    """
    Dipanggil **di dalam** `schema_context`. Membuktikan koneksi memang
    menunjuk schema tenant itu, dari dua arah: penanda django-tenants dan
    `search_path` PostgreSQL.
    """
    if connection.schema_name != tenant.schema_name:
        raise DemoGuardError(
            f"Koneksi menunjuk {connection.schema_name!r}, bukan "
            f"{tenant.schema_name!r}."
        )

    with connection.cursor() as cursor:
        cursor.execute("SELECT current_schema()")
        current = cursor.fetchone()[0]

    if current != tenant.schema_name:
        raise DemoGuardError(
            f"search_path PostgreSQL = {current!r}, bukan {tenant.schema_name!r}."
        )

    return current


def enforce_read_only_transaction() -> None:
    """
    Mode kering: transaksi yang sedang terbuka dijadikan READ ONLY di
    tingkat PostgreSQL. Tulisan apa pun — termasuk yang tidak sengaja
    dari fungsi yang dikira hanya membaca — gagal di database, bukan
    diandalkan pada disiplin kode.
    """
    with connection.cursor() as cursor:
        cursor.execute("SET TRANSACTION READ ONLY")


# ======================================================================
# Sidik jari
# ======================================================================


@dataclass(frozen=True)
class Fingerprint:
    count: int
    sha256: str


def fingerprint(queryset: QuerySet) -> Fingerprint:
    model = queryset.model
    columns = [
        field.attname
        for field in model._meta.concrete_fields
        if field.attname not in EXCLUDED_DIGEST_COLUMNS
    ]
    rows = list(queryset.order_by("pk").values_list(*columns))
    payload = json.dumps(rows, default=str, sort_keys=True).encode()

    return Fingerprint(len(rows), hashlib.sha256(payload).hexdigest())


def _cast_filter(prefix_field: str) -> Q:
    query = Q()

    for prefix in PROTECTED_EMPLOYEE_PREFIXES:
        query |= Q(**{f"{prefix_field}__startswith": prefix})

    return query


def protected_querysets() -> dict[str, QuerySet]:
    """
    Seluruh yang dilindungi, per nama. Tambahan untuk dataset ini
    (GRP/MMN/MIN, EMP###, demoerp.*) **dikeluarkan** dari cakupan: yang
    diukur adalah bahwa yang lain tidak berubah, bukan bahwa tenant
    tidak bertambah.
    """
    from django.contrib.auth.models import Permission

    from apps.accounts.models import (
        Menu,
        Role,
        RoleAssignment,
        RoleAssignmentAuthority,
        RoleMenuPermission,
        User,
    )
    from apps.administration.models import (
        Branch,
        Company,
        CompanyType,
        ContractType,
        CostCenter,
        Department,
        Division,
        EmployeeGroup,
        EmploymentStatus,
        EmploymentType,
        Holiday,
        JobCategory,
        JobLevel,
        LeavePolicy,
        LeaveType,
        Location,
        LocationType,
        Position,
        RosterPolicy,
        RosterShiftRotation,
        Section,
        Shift,
        WorkCalendar,
    )
    from apps.finance.models import (
        Account,
        AccountingDimension,
        AccountingEvent,
        AccountingPeriod,
        AccountingPolicy,
        AccountingPolicyLine,
        AccountingPolicyRule,
        AccountMapping,
        FiscalYear,
        Journal,
    )
    from apps.hr.models import (
        AttendanceLog,
        AttendancePermission,
        Employee,
        EmployeeAttendance,
        EmployeeLeave,
        EmployeeOvertime,
        EmploymentAssignment,
        OrganizationAssignment,
        PayrollAssignment,
    )
    from apps.payroll.models import (
        AllowanceTemplate,
        AllowanceTemplateLine,
        DeductionTemplate,
        DeductionTemplateLine,
        OvertimeGroup,
        PayrollGroup,
        PayrollPeriod,
        PayrollPermissionRule,
        PayrollPolicy,
        PayrollRun,
    )
    from apps.workflow.models import (
        WorkflowDefinition,
        WorkflowStep,
        WorkflowStepFallback,
    )

    not_owned_company = ~Q(company__code__in=OWNED_COMPANY_CODES)
    protected_company = Q(company__code__in=PROTECTED_COMPANY_CODES)
    cast = _cast_filter("employee_number")
    cast_of = _cast_filter("employee__employee_number")
    existing_users = ~Q(username__startswith=USERNAME_PREFIX)

    return {
        # --- RBAC ------------------------------------------------------
        "rbac.role": Role.objects.all(),
        "rbac.role_permission": Role.permissions.through.objects.all(),
        "rbac.permission": Permission.objects.all(),
        "rbac.menu": Menu.objects.all(),
        "rbac.role_menu_permission": RoleMenuPermission.objects.all(),
        "rbac.user.existing": User.objects.filter(existing_users),
        "rbac.role_assignment.existing": RoleAssignment.objects.exclude(
            user__username__startswith=USERNAME_PREFIX
        ),
        "rbac.role_authority.existing": RoleAssignmentAuthority.objects.exclude(
            assignment__user__username__startswith=USERNAME_PREFIX
        ),
        # --- Workflow --------------------------------------------------
        "workflow.definition": WorkflowDefinition.objects.all(),
        "workflow.step": WorkflowStep.objects.all(),
        "workflow.step_fallback": WorkflowStepFallback.objects.all(),
        # --- Finance Core (company lain) -------------------------------
        "finance.account": Account.objects.filter(not_owned_company),
        "finance.account_mapping": AccountMapping.objects.filter(not_owned_company),
        "finance.policy": AccountingPolicy.objects.filter(not_owned_company),
        "finance.policy_rule": AccountingPolicyRule.objects.exclude(
            policy__company__code__in=OWNED_COMPANY_CODES
        ),
        "finance.policy_line": AccountingPolicyLine.objects.exclude(
            rule__policy__company__code__in=OWNED_COMPANY_CODES
        ),
        "finance.fiscal_year": FiscalYear.objects.filter(not_owned_company),
        "finance.accounting_period": AccountingPeriod.objects.exclude(
            fiscal_year__company__code__in=OWNED_COMPANY_CODES
        ),
        "finance.dimension": AccountingDimension.objects.all(),
        "finance.journal.other": Journal.objects.filter(not_owned_company),
        "finance.event.other": AccountingEvent.objects.filter(not_owned_company),
        # --- Organisasi MNI/MMR/MLS ------------------------------------
        "org.company.protected": Company.objects.filter(code__in=PROTECTED_COMPANY_CODES),
        "org.branch.protected": Branch.objects.filter(protected_company),
        "org.location.protected": Location.objects.filter(protected_company),
        "org.division.protected": Division.objects.filter(protected_company),
        "org.department.protected": Department.objects.filter(protected_company),
        "org.section.protected": Section.objects.filter(protected_company),
        "org.position.protected": Position.objects.filter(protected_company),
        "org.cost_center.protected": CostCenter.objects.filter(protected_company),
        # --- Referensi organisasi & HR ---------------------------------
        "ref.company_type": CompanyType.objects.all(),
        "ref.location_type": LocationType.objects.all(),
        "ref.job_level": JobLevel.objects.all(),
        "ref.job_category": JobCategory.objects.all(),
        "ref.employee_group": EmployeeGroup.objects.all(),
        "ref.employment_type": EmploymentType.objects.all(),
        "ref.employment_status": EmploymentStatus.objects.all(),
        "ref.contract_type": ContractType.objects.all(),
        # --- Kalender / roster / cuti ----------------------------------
        "schedule.work_calendar": WorkCalendar.objects.all(),
        "schedule.holiday": Holiday.objects.all(),
        "schedule.shift": Shift.objects.all(),
        # DEMO-1F: policy roster MMN milik dataset (`roster_policy.POLICIES`)
        # ditulis seed sendiri; yang dilindungi = policy company lain.
        "schedule.roster_policy": RosterPolicy.objects.exclude(company__code__in=OWNED_COMPANY_CODES),
        "schedule.roster_rotation": RosterShiftRotation.objects.exclude(
            policy__company__code__in=OWNED_COMPANY_CODES
        ),
        "leave.type": LeaveType.objects.all(),
        "leave.policy": LeavePolicy.objects.all(),
        # --- Konfigurasi payroll ---------------------------------------
        "payroll.group": PayrollGroup.objects.all(),
        "payroll.policy": PayrollPolicy.objects.all(),
        "payroll.allowance_template": AllowanceTemplate.objects.all(),
        "payroll.allowance_line": AllowanceTemplateLine.objects.all(),
        "payroll.deduction_template": DeductionTemplate.objects.all(),
        "payroll.deduction_line": DeductionTemplateLine.objects.all(),
        "payroll.overtime_group": OvertimeGroup.objects.all(),
        "payroll.permission_rule": PayrollPermissionRule.objects.all(),
        "payroll.period.other": PayrollPeriod.objects.filter(not_owned_company),
        "payroll.run.other": PayrollRun.objects.filter(not_owned_company),
        # --- Awalan HR-DEMO + TRL (dibuang DEMO-1D; kini himpunan kosong,
        #     tetap disidik supaya kemunculan ulangnya terdeteksi) ---------
        "cast.employee": Employee.objects.filter(cast),
        "cast.organization": OrganizationAssignment.objects.filter(cast_of),
        "cast.employment": EmploymentAssignment.objects.filter(cast_of),
        "cast.payroll_assignment": PayrollAssignment.objects.filter(cast_of),
        "cast.attendance": EmployeeAttendance.objects.filter(cast_of),
        "cast.attendance_log": AttendanceLog.objects.filter(cast_of),
        "cast.leave": EmployeeLeave.objects.filter(cast_of),
        "cast.attendance_permission": AttendancePermission.objects.filter(cast_of),
        "cast.overtime": EmployeeOvertime.objects.filter(cast_of),
    }


def protected_snapshot() -> dict[str, Fingerprint]:
    return {name: fingerprint(qs) for name, qs in protected_querysets().items()}


def diff_snapshots(before: dict[str, Fingerprint], after: dict[str, Fingerprint]) -> list[str]:
    changed = []

    for name in sorted(set(before) | set(after)):
        if before.get(name) != after.get(name):
            changed.append(name)

    return changed
