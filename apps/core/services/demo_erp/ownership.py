"""
Kepemilikan: baris mana yang **terbukti** milik dataset ini.

Tiga lapis, dan semuanya harus benar sekaligus:

1. Company milik dataset = kode di `OWNED_COMPANY_CODES` **dan** surel
   penanda `<kode>@demo-erp.meinova.example`. Company berkode sama tanpa
   penanda adalah milik orang lain → pemblokir, bukan diambil alih.
2. Pegawai milik dataset = nomor `EMP###` **dan** catatan berawalan
   `[DEMO-ERP:<nomor>]` **dan** penempatan di company milik dataset.
3. Dokumen/transaksi milik dataset = menunjuk pegawai milik dataset
   (atau company milik dataset untuk baris tingkat company).

Tidak ada yang disimpulkan dari rentang PK, tanggal buat, atau
"seluruh tabel". Baris yang separuh cocok — nomornya EMP### tapi tanpa
penanda, atau berpenanda tapi duduk di company lain — adalah **asing**
dan menghentikan reset.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from django.db.models import Q

from . import mapping
from .constants import (
    EMPLOYEE_NOTE_PREFIX,
    EMPLOYEE_NUMBER_PATTERN,
    OWNED_COMPANY_CODES,
    USERNAME_PREFIX,
)


def is_owned_company(company) -> bool:
    return (
        company.code in OWNED_COMPANY_CODES
        and (company.email or "").lower() == mapping.company_email(company.code)
    )


def is_owned_employee(employee) -> bool:
    organization = getattr(employee, "organization", None)
    company = getattr(organization, "company", None) if organization else None

    return bool(
        re.match(EMPLOYEE_NUMBER_PATTERN, employee.employee_number or "")
        and (employee.notes or "").startswith(
            f"{EMPLOYEE_NOTE_PREFIX}{employee.employee_number}]"
        )
        and company is not None
        and is_owned_company(company)
    )


@dataclass
class OwnershipReport:
    owned_companies: list[str] = field(default_factory=list)
    foreign: list[str] = field(default_factory=list)
    owned_counts: dict[str, int] = field(default_factory=dict)
    owned_employee_ids: list[int] = field(default_factory=list)


def inspect() -> OwnershipReport:
    """Baca saja. Mengisi daftar milik + daftar baris asing."""
    from apps.accounts.models import User
    from apps.administration.models import Company
    from apps.hr.models import Employee

    report = OwnershipReport()

    owned_company_ids = []

    for company in Company.objects.filter(code__in=OWNED_COMPANY_CODES).order_by("code"):
        if company.is_deleted:
            report.foreign.append(
                f"Company {company.code} ada dalam keadaan terhapus (soft delete). "
                "Kodenya tetap terkunci unique; tidak bisa dibuat ulang."
            )
        elif is_owned_company(company):
            report.owned_companies.append(company.code)
            owned_company_ids.append(company.pk)
        else:
            report.foreign.append(
                f"Company {company.code} sudah ada tanpa penanda dataset "
                f"(email={company.email!r}). Bukan milik dataset ini."
            )

    in_owned_company = Q(organization__company_id__in=owned_company_ids)
    looks_owned = Q(employee_number__regex=EMPLOYEE_NUMBER_PATTERN) | Q(
        notes__startswith=EMPLOYEE_NOTE_PREFIX
    )

    candidates = (
        Employee.objects
        .filter(in_owned_company | looks_owned)
        .select_related("organization__company")
        .order_by("employee_number", "pk")
    )

    for employee in candidates:
        if is_owned_employee(employee):
            report.owned_employee_ids.append(employee.pk)
            continue

        company = getattr(getattr(employee, "organization", None), "company", None)
        report.foreign.append(
            f"Pegawai {employee.employee_number} (pk={employee.pk}, company="
            f"{getattr(company, 'code', None)}, deleted={employee.is_deleted}) "
            "cocok sebagian dengan dataset ini tapi tidak membawa kepemilikan "
            "lengkap."
        )

    owned_user_ids = set(
        Employee.objects
        .filter(pk__in=report.owned_employee_ids, user__isnull=False)
        .values_list("user_id", flat=True)
    )

    for user in User.objects.filter(username__startswith=USERNAME_PREFIX).order_by("username"):
        if user.pk not in owned_user_ids:
            report.foreign.append(
                f"Akun {user.username} berawalan {USERNAME_PREFIX} tapi tidak "
                "terikat ke pegawai milik dataset ini."
            )

    report.owned_counts = owned_counts(
        company_ids=owned_company_ids,
        employee_ids=report.owned_employee_ids,
    )

    return report


def owned_querysets(*, company_ids, employee_ids) -> dict[str, object]:
    """
    Seluruh baris milik dataset, per model, dalam **urutan bongkar**
    (dependensi PROTECT dulu). Dipakai reset DEMO-1B dan dilaporkan
    hitungannya sekarang.
    """
    from apps.accounts.models import User
    from apps.administration.models import Company
    from apps.finance.models import AccountingEvent, Journal
    from apps.hr.models import (
        AttendanceLog,
        AttendancePermission,
        Employee,
        EmployeeAction,
        EmployeeAttendance,
        EmployeeLeave,
        EmployeeOvertime,
        EmployeeShiftAssignment,
        RotationPeriod,
        SiteRotation,
    )
    from apps.payroll.models import (
        PayrollInput,
        PayrollPeriod,
        PayrollRun,
        PayrollRunEmployee,
        Payslip,
    )
    from apps.workflow.models import WorkflowInstance

    by_employee = Q(employee_id__in=employee_ids)
    by_company = Q(company_id__in=company_ids)

    return {
        "finance.journal": Journal.objects.filter(by_company),
        "finance.accounting_event": AccountingEvent.objects.filter(by_company),
        "workflow.instance": WorkflowInstance.objects.filter(
            Q(subject_employee_id__in=employee_ids) | by_company
        ),
        "payroll.payslip": Payslip.objects.filter(by_employee),
        "payroll.input": PayrollInput.objects.filter(by_employee),
        "payroll.run_employee": PayrollRunEmployee.objects.filter(by_employee),
        "payroll.run": PayrollRun.objects.filter(by_company),
        "payroll.period": PayrollPeriod.objects.filter(by_company),
        "hr.attendance_log": AttendanceLog.objects.filter(by_employee),
        "hr.attendance": EmployeeAttendance.objects.filter(by_employee),
        "hr.attendance_permission": AttendancePermission.objects.filter(by_employee),
        "hr.leave": EmployeeLeave.objects.filter(by_employee),
        "hr.overtime": EmployeeOvertime.objects.filter(by_employee),
        "hr.employee_action": EmployeeAction.objects.filter(by_employee),
        "hr.shift_assignment": EmployeeShiftAssignment.objects.filter(by_employee),
        "hr.rotation_period": RotationPeriod.objects.filter(by_employee),
        "hr.site_rotation": SiteRotation.objects.filter(by_employee),
        "hr.employee": Employee.objects.filter(pk__in=employee_ids),
        "accounts.user": User.objects.filter(
            username__startswith=USERNAME_PREFIX,
            employee_profile__pk__in=employee_ids,
        ),
        "org.company": Company.objects.filter(pk__in=company_ids),
    }


def owned_counts(*, company_ids, employee_ids) -> dict[str, int]:
    return {
        name: queryset.count()
        for name, queryset in owned_querysets(
            company_ids=company_ids,
            employee_ids=employee_ids,
        ).items()
    }


def posted_history(*, company_codes=OWNED_COMPANY_CODES) -> list[str]:
    """
    Riwayat Finance yang tidak boleh dibongkar (B3). Jurnal POSTED atau
    REVERSED di company milik dataset, atau jurnal pembalik yang menunjuk
    jurnalnya. Satu saja → reset menolak.
    """
    from apps.finance.models import Journal
    from apps.finance.models.choices import JournalStatus

    rows = (
        Journal.objects
        .filter(company__code__in=company_codes)
        .filter(
            Q(status__in=[JournalStatus.POSTED, JournalStatus.REVERSED])
            | Q(reversal_of__isnull=False)
        )
        .order_by("pk")
        .values_list("pk", "company__code", "status")
    )

    return [f"Journal pk={pk} company={code} status={status}" for pk, code, status in rows]
