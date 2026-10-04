"""
Verifikasi baseline — **hanya membaca**.

Kesiapan Finance dibuktikan tanpa finalize: gerbang akuntansi payroll
(`PayrollAccountingGate.evaluate`), resolusi kebijakan
(`AccountingPolicyService.resolve`), dan penyusunan baris draf
(`AccountingPolicyService.build_lines`, didokumentasikan tidak pernah
menyimpan) dijalankan di dalam savepoint yang di-rollback. Hasilnya
menjawab "kalau run ini difinalisasi, PAYROLL_POSTED akan jatuh ke
kebijakan mana dan akun mana" — tanpa satu kejadian atau jurnal pun.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.db import transaction

from .constants import OWNED_COMPANY_CODES


def finance_history_counts() -> dict:
    from apps.finance.models import AccountingEvent, Journal

    return {
        "accounting_events_owned": AccountingEvent.objects.filter(
            company__code__in=OWNED_COMPANY_CODES
        ).count(),
        "journals_owned": Journal.objects.filter(company__code__in=OWNED_COMPANY_CODES).count(),
        "accounting_events_tenant": AccountingEvent.objects.count(),
        "journals_tenant": Journal.objects.count(),
    }


def payroll_runs() -> list:
    from apps.payroll.models import PayrollRun

    return [
        {
            "document_number": run.document_number,
            "company": run.company.code,
            "period": run.period.code,
            "status": run.status,
            "employees": run.employee_count,
            "total_earning": run.total_earning,
            "total_deduction": run.total_deduction,
            "total_net": run.total_net,
        }
        for run in PayrollRun.objects.filter(
            company__code__in=OWNED_COMPANY_CODES, is_deleted=False
        ).select_related("company", "period").order_by("company__code", "period__code")
    ]


def payroll_lines() -> list:
    from apps.payroll.models import PayrollRunEmployee

    rows = []

    for line in (
        PayrollRunEmployee.objects.filter(
            run__company__code__in=OWNED_COMPANY_CODES, run__is_deleted=False, is_deleted=False
        )
        .select_related("run__period", "employee")
        .order_by("employee__employee_number", "run__period__code")
    ):
        components = {
            component.code: component.amount
            for component in line.components.filter(is_deleted=False).order_by("sequence")
        } if hasattr(line, "components") else {}

        rows.append({
            "employee": line.employee.employee_number,
            "period": line.run.period.code,
            "status": getattr(line, "status", ""),
            "gross_earning": line.gross_earning,
            "total_deduction": line.total_deduction,
            "net_pay": line.net_pay,
            "employer_contribution": line.employer_contribution,
            "components": components,
        })

    return rows


def finance_readiness() -> list:
    """Per run: gerbang → kebijakan → baris draf. Di-rollback."""
    from apps.finance.models import Account
    from apps.finance.services.policy import AccountingPolicyService
    from apps.payroll.models import PayrollRun
    from apps.payroll.services.accounting_gate import PayrollAccountingGate

    results = []

    for run in PayrollRun.objects.filter(
        company__code__in=OWNED_COMPANY_CODES, is_deleted=False
    ).select_related("company", "period").order_by("company__code", "period__code"):
        entry = {"run": run.document_number, "company": run.company.code, "period": run.period.code}

        try:
            with transaction.atomic():
                gate = PayrollAccountingGate.evaluate(run=run)
                policy = AccountingPolicyService.resolve(
                    event_type="PAYROLL_POSTED",
                    company_id=run.company_id,
                    on_date=run.period.end_date,
                )
                lines = (
                    AccountingPolicyService.build_lines(
                        policy=policy,
                        payload=gate.payload,
                        company_id=run.company_id,
                        on_date=run.period.end_date,
                    )
                    if policy is not None else []
                )
                transaction.set_rollback(True)
        except Exception as exc:  # noqa: BLE001 - dilaporkan, bukan ditelan
            entry["ready"] = False
            entry["error"] = f"{type(exc).__name__}: {getattr(exc, 'code', '')} {exc}"
            results.append(entry)
            continue

        accounts = {
            account.pk: account for account in Account.objects.filter(pk__in={l.account_id for l in lines})
        }
        debit = sum((l.amount for l in lines if l.side == "debit"), Decimal("0"))
        credit = sum((l.amount for l in lines if l.side == "credit"), Decimal("0"))

        entry.update({
            "policy": getattr(policy, "code", None),
            "auto_post": getattr(policy, "auto_post", None),
            "period_code": gate.period_code,
            "period_status": gate.period_status,
            "period_problem": gate.period_problem,
            "currency": gate.currency,
            "draft_lines": len(lines),
            "debit": debit,
            "credit": credit,
            "balanced": debit == credit,
            "accounts": sorted(
                {
                    f"{accounts[l.account_id].code} {accounts[l.account_id].name} "
                    f"(aktif={accounts[l.account_id].is_active})"
                    for l in lines
                }
            ),
            "ready": (
                policy is not None
                and bool(lines)
                and debit == credit
                and not gate.period_problem
                and all(accounts[l.account_id].is_active for l in lines)
            ),
        })
        results.append(entry)

    return results


def attendance_summary(employee_ids, start: date, end: date) -> list:
    from apps.hr.models import Employee
    from apps.reports.api.hr.period_summary.services import HRPeriodSummaryService

    summary = HRPeriodSummaryService.build_for(
        Employee.objects.filter(pk__in=employee_ids), start, end,
    )

    return [
        {
            "employee": row.employee_number,
            "scheduled": row.scheduled,
            "present": row.present,
            "absent": row.absent,
            "field_break": row.field_break,
            "late": row.late,
            "early": row.early,
            "ot_minutes": row.ot_regular_minutes + row.ot_off_minutes + row.ot_holiday_minutes,
            "leave": {k: str(v) for k, v in row.leave_days.items()},
        }
        for row in sorted(summary.rows, key=lambda r: r.employee_number)
    ]


def finance_configuration(company_codes=("MMN", "MIN"), dates=(date(2026, 8, 31), date(2026, 9, 30))) -> list:
    """
    Kesiapan konfigurasi Finance tanpa payload run: kebijakan yang
    diresolusi untuk PAYROLL_POSTED, setiap kunci peran yang dipakai
    baris kebijakan itu (dibaca dari basis data, bukan ditulis di sini)
    → akun lewat `AccountMappingService.resolve`, dan periode akuntansi
    yang memuat tanggal kejadian.
    """
    from apps.administration.models import Company
    from apps.finance.models import AccountingPeriod, AccountingPolicyLine
    from apps.finance.services.mapping import AccountMappingService, MappingContext
    from apps.finance.services.policy import AccountingPolicyService

    results = []

    for code in company_codes:
        company = Company.objects.get(code=code, is_deleted=False)

        for on_date in dates:
            entry = {"company": code, "event_date": on_date}
            policy = AccountingPolicyService.resolve(
                event_type="PAYROLL_POSTED", company_id=company.pk, on_date=on_date,
            )
            entry["policy"] = getattr(policy, "code", None)
            entry["auto_post"] = getattr(policy, "auto_post", None)

            keys = sorted(
                set(
                    AccountingPolicyLine.objects.filter(
                        rule__policy=policy, is_deleted=False,
                    ).values_list("mapping_key", flat=True)
                )
            ) if policy is not None else []

            mapped, problems = {}, []

            for key in keys:
                try:
                    account = AccountMappingService.resolve(
                        mapping_key=key,
                        context=MappingContext(company_id=company.pk, event_type="PAYROLL_POSTED"),
                    )
                except Exception as exc:  # noqa: BLE001 - dilaporkan
                    problems.append(f"{key}: {type(exc).__name__}")
                    continue

                if account.company_id != company.pk or not account.is_active:
                    problems.append(f"{key}: akun {account.code} bukan milik {code} atau nonaktif")

                mapped[key] = f"{account.code} {account.name}"

            period = AccountingPeriod.objects.filter(
                fiscal_year__company=company, start_date__lte=on_date, end_date__gte=on_date,
                is_deleted=False,
            ).first()

            entry.update({
                "mapping_keys": len(keys),
                "mappings": mapped,
                "problems": problems,
                "accounting_period": getattr(period, "code", None),
                "period_status": getattr(period, "status", None),
                "ready": policy is not None and bool(keys) and not problems
                and getattr(period, "status", None) == "open",
            })
            results.append(entry)

    return results


def attendance_status_breakdown(employee_ids, start: date, end: date) -> list:
    from django.db.models import Count

    from apps.hr.models import EmployeeAttendance

    return list(
        EmployeeAttendance.objects.filter(
            employee_id__in=employee_ids, work_date__gte=start, work_date__lte=end, is_deleted=False,
        )
        .values("source", "status", "shift__code")
        .annotate(rows=Count("id"))
        .order_by("source", "shift__code", "status")
    )


# ======================================================================
# Rekonsiliasi payroll (DEMO-1C §5)
# ======================================================================


def reconcile_payroll() -> list:
    """
    Identitas yang dipakai mesin hitung sendiri, diperiksa ulang:

    * total run = Σ total baris (earning, deduction, net);
    * per baris: gross − total_deduction = net;
    * per baris: Σ EARNING − (Σ DEDUCTION − total_deduction) = gross
      (potongan yang tidak masuk total_deduction adalah pengurang
      pendapatan, mis. ABSENT);
    * per baris: Σ EMPLOYER_CONTRIBUTION = employer_contribution;
    * setiap baris yang ikut punya mata uang.
    """
    from apps.payroll.models import PayrollRun

    results = []

    for run in PayrollRun.objects.filter(
        company__code__in=OWNED_COMPANY_CODES, is_deleted=False
    ).select_related("company", "period").order_by("company__code", "period__code"):
        lines = list(run.employees.filter(is_deleted=False, is_excluded=False).select_related("employee", "currency")
                     if hasattr(run, "employees") else [])
        problems = []
        sums = {"gross": Decimal("0"), "deduction": Decimal("0"), "net": Decimal("0")}

        for line in lines:
            sums["gross"] += line.gross_earning
            sums["deduction"] += line.total_deduction
            sums["net"] += line.net_pay

            if line.currency_id is None:
                problems.append(f"{line.employee.employee_number}: tanpa mata uang")

            if line.gross_earning - line.total_deduction != line.net_pay:
                problems.append(f"{line.employee.employee_number}: gross − deduction ≠ net")

            by_type = {"earning": Decimal("0"), "deduction": Decimal("0"), "employer_contribution": Decimal("0")}

            for component in line.components.filter(is_deleted=False):
                by_type[component.component_type] = by_type.get(component.component_type, Decimal("0")) + component.amount

            if by_type["earning"] - (by_type["deduction"] - line.total_deduction) != line.gross_earning:
                problems.append(f"{line.employee.employee_number}: komponen ≠ gross")

            if by_type["employer_contribution"] != line.employer_contribution:
                problems.append(f"{line.employee.employee_number}: komponen pemberi kerja ≠ total")

        for key, field in (("gross", "total_earning"), ("deduction", "total_deduction"), ("net", "total_net")):
            if sums[key] != getattr(run, field):
                problems.append(f"run {field} {getattr(run, field)} ≠ Σ baris {sums[key]}")

        results.append({
            "run": run.document_number,
            "company": run.company.code,
            "period": run.period.code,
            "status": run.status,
            "lines": len(lines),
            "lines_without_currency": sum(1 for line in lines if line.currency_id is None),
            "gross": run.total_earning,
            "deduction": run.total_deduction,
            "net": run.total_net,
            "problems": problems,
            "reconciled": not problems,
        })

    return results


# ======================================================================
# Sidik jari logis dataset (DEMO-1C §10)
# ======================================================================


def _digest(rows) -> str:
    import hashlib
    import json

    payload = json.dumps(sorted(rows, key=lambda r: json.dumps(r, default=str)), default=str)

    return hashlib.sha256(payload.encode()).hexdigest()


def logical_digest() -> dict:
    """
    Isi bisnis dataset tanpa PK, tanpa nomor dokumen dari deret, tanpa cap
    waktu — dua baseline yang sama secara bisnis menghasilkan angka yang
    sama walau PK dan sequence PostgreSQL berbeda. Rumus per bagian:
    sha256(json.dumps(sorted(baris, key=json.dumps), default=str)).
    """
    from apps.accounts.models import RoleAssignment
    from apps.administration.models import (
        Company,
        CostCenter,
        Department,
        Location,
        NotificationSetting,
        Position,
        RosterPolicy,
    )
    from apps.finance.models import Account, AccountingPeriod, AccountingPolicy, AccountMapping
    from apps.hr.models import (
        AttendancePermission,
        EmployeeAttendance,
        EmploymentAssignment,
        EmployeeBankAccount,
        EmployeeEducation,
        EmployeeFamily,
        LeaveBalance,
        EmployeeLeave,
        EmployeeOvertime,
        EmployeeShiftAssignment,
        PayrollAssignment,
        RotationPeriod,
        SiteRotation,
    )
    from apps.payroll.models import PayrollPeriod, PayrollRun, PayrollRunComponent, PayrollRunEmployee
    from apps.workflow.models import WorkflowApproval

    from .apply import owned_employees

    employees = owned_employees()
    codes = OWNED_COMPANY_CODES
    co = {"company__code__in": codes, "is_deleted": False}

    sections = {
        "org.company": [
            (c.code, c.name, getattr(c.parent, "code", None), c.email)
            for c in Company.objects.filter(code__in=codes, is_deleted=False)
        ],
        "org.location": list(Location.objects.filter(**co).values_list("company__code", "code", "name", "location_type__code")),
        "org.department": list(Department.objects.filter(**co).values_list("company__code", "code", "name", "location__code", "division__code")),
        "org.position": list(Position.objects.filter(**co).values_list("company__code", "code", "name", "department__code", "job_level__code", "is_manager", "reports_to__code")),
        "org.cost_center": list(CostCenter.objects.filter(**co).values_list("company__code", "code", "name", "department__code")),
        "finance.account": list(Account.objects.filter(**co).values_list("company__code", "code", "name", "is_active")),
        "finance.mapping": list(AccountMapping.objects.filter(**co).values_list("code", "mapping_key", "account__code")),
        "finance.policy": list(AccountingPolicy.objects.filter(**co).values_list("code", "event_type", "auto_post")),
        "finance.period": list(AccountingPeriod.objects.filter(fiscal_year__company__code__in=codes, is_deleted=False).values_list("fiscal_year__company__code", "code", "status")),
        "access": [
            (a.user.username, a.role.code, a.authority_mode, a.authority_level,
             tuple(sorted((x.resource_type, x.resource_id is not None) for x in a.authorities.all())))
            for a in RoleAssignment.objects.filter(user__employee_profile__in=employees).select_related("user", "role")
        ] if hasattr(RoleAssignment, "authorities") else [
            (a.user.username, a.role.code, a.authority_mode, a.authority_level)
            for a in RoleAssignment.objects.filter(user__employee_profile__in=employees).select_related("user", "role")
        ],
        "employee": [
            (e.employee_number, e.first_name, e.last_name, e.notes, getattr(e.user, "username", None),
             e.organization.company.code, getattr(e.organization.location, "code", None),
             getattr(e.organization.department, "code", None), getattr(e.organization.position, "code", None),
             getattr(e.organization.job_level, "code", None), getattr(e.organization.cost_center, "code", None),
             getattr(e.organization.reports_to, "employee_number", None),
             getattr(e.employment.employment_type, "code", None), getattr(e.employment.employee_group, "code", None),
             e.employment.join_date, e.employment.contract_start, e.employment.contract_end,
             getattr(e.employment.roster_policy, "code", None), e.employment.roster_cycle_start,
             getattr(e.employment.working_calendar, "code", None), getattr(e.employment.shift, "code", None))
            for e in employees
        ],
        # DEMO-1D: tiga tulisan seed yang sebelumnya tidak ikut disidik.
        "account.user": [
            (u.username, u.email, u.first_name, u.last_name, u.is_active,
             NotificationSetting.objects.filter(user=u).values_list("email_enabled", flat=True).first())
            for u in (e.user for e in employees) if u is not None
        ],
        # DEMO-1E: identitas & data pribadi dari `identity.IDENTITIES`.
        "employee.identity": [
            (e.employee_number, e.nik, e.tax_number, e.passport_number,
             getattr(e.gender, "code", None), getattr(e.religion, "code", None),
             getattr(e.nationality, "code", None), getattr(e.blood_type, "code", None),
             getattr(e.marital_status, "code", None), e.birth_place, e.birth_date, e.address,
             getattr(e.province, "code", None), getattr(e.city, "code", None),
             getattr(e.district, "code", None), getattr(e.village, "code", None),
             e.personal_email, e.work_email, e.phone, e.mobile,
             e.emergency_contact_name, e.emergency_contact_phone)
            for e in employees
        ],
        "employee.family": list(EmployeeFamily.objects.filter(employee__in=employees, is_deleted=False).values_list(
            "employee__employee_number", "relationship__code", "full_name", "gender__code", "birth_date",
            "phone", "is_dependent", "is_emergency_contact", "notes")),
        "employee.bank": list(EmployeeBankAccount.objects.filter(employee__in=employees, is_deleted=False).values_list(
            "employee__employee_number", "bank__code", "account_number", "account_name", "branch_name",
            "currency__code", "is_primary", "notes")),
        "employee.education": list(EmployeeEducation.objects.filter(employee__in=employees, is_deleted=False).values_list(
            "employee__employee_number", "education__code", "degree__code", "study_field__code",
            "institution_name", "city", "country", "graduation_year", "is_highest_education", "notes")),
        "payroll.statutory": list(PayrollAssignment.objects.filter(employee__in=employees, is_deleted=False).values_list(
            "employee__employee_number", "tax_number_payroll", "bpjs_kesehatan_number",
            "bpjs_ketenagakerjaan_number", "payment_method")),
        "leave.balance": list(LeaveBalance.objects.filter(employee__in=employees, is_deleted=False).values_list(
            "employee__employee_number", "leave_type__code", "year", "entitlement", "carried_over",
            "opening_balance", "adjustment", "opening_used", "carried_over_used", "advance_used", "used")),
        "payroll.period": list(PayrollPeriod.objects.filter(**co).values_list(
            "company__code", "payroll_group__code", "code", "start_date", "end_date", "cutoff_date",
            "payment_date", "status", "working_days")),
        "payroll.assignment": list(PayrollAssignment.objects.filter(employee__in=employees, is_deleted=False).values_list(
            "employee__employee_number", "effective_from", "basic_salary", "currency__code", "payroll_group__code",
            "allowance_template__code", "deduction_template__code", "tax_status__code", "overtime_eligible",
            "overtime_group__code", "is_current")),
        # DEMO-1F: konfigurasi policy roster MMN milik dataset.
        "roster.policy_config": [
            (p.company.code, getattr(p.location, "code", None), p.code, p.name, p.is_default, p.is_active,
             p.cycle_work_days, p.cycle_off_days, p.roster_start_basis, p.rolling_horizon_months,
             p.min_rest_hours, p.default_travel_out_days, p.default_travel_in_days, p.travel_day_mode,
             p.travel_creates_segment, p.travel_out_counts_as_roster_day, p.travel_in_counts_as_roster_day,
             p.count_transit_overnight, p.travel_variance_credit_eligible, p.travel_variance_credit_max_days,
             p.credit_enabled, p.conversion_ratio, p.credit_rounding, p.credit_carry_remainder,
             p.credit_max_balance_days, p.credit_expiry_months, p.credit_allow_negative,
             p.request_lead_days, p.notify_lead_days,
             tuple(sorted(p.urgent_purposes.values_list("code", flat=True))),
             tuple(p.shift_rotations.filter(is_deleted=False).order_by("sequence").values_list(
                 "sequence", "shift__code", "block_days", "notes")) if hasattr(p, "shift_rotations") else (),
             tuple(sorted(p.travel_days.filter(is_deleted=False).values_list(
                 "point_of_hire__code", "point_of_hire__province__code", "travel_out_days", "travel_in_days"))))
            for p in RosterPolicy.objects.filter(
                pk__in=EmploymentAssignment.objects.filter(employee__in=employees).values("roster_policy"),
                is_deleted=False,
            ).select_related("company", "location")
        ],
        "roster.rotation": list(SiteRotation.objects.filter(employee__in=employees, is_deleted=False).values_list(
            "employee__employee_number", "effective_from", "status")),
        "roster.period": list(RotationPeriod.objects.filter(employee__in=employees, is_deleted=False).values_list(
            "employee__employee_number", "segment_type", "start_date", "end_date")),
        "roster.shift": list(EmployeeShiftAssignment.objects.filter(employee__in=employees, is_deleted=False).values_list(
            "employee__employee_number", "layer", "kind", "start_date", "end_date", "shift__code")),
        "attendance": list(EmployeeAttendance.objects.filter(employee__in=employees, is_deleted=False).values_list(
            "employee__employee_number", "work_date", "status", "source", "shift__code", "check_in", "check_out",
            "late_minutes", "early_leave_minutes", "overtime_minutes", "worked_minutes", "external_id",
            "is_excused_absence", "permission_state")),
        "leave": list(EmployeeLeave.objects.filter(employee__in=employees, is_deleted=False).values_list(
            "employee__employee_number", "leave_type__code", "start_date", "end_date", "total_days", "status", "notes")),
        "permission": list(AttendancePermission.objects.filter(employee__in=employees, is_deleted=False).values_list(
            "employee__employee_number", "date", "permission_type", "status", "reason", "allow_outside_shift")),
        "overtime": list(EmployeeOvertime.objects.filter(employee__in=employees, is_deleted=False).values_list(
            "employee__employee_number", "work_date", "start_time", "end_time", "duration_minutes", "status", "is_paid", "notes")),
        "workflow": list(WorkflowApproval.objects.filter(instance__subject_employee__in=employees).values_list(
            "instance__subject_employee__employee_number", "instance__document_type", "instance__status",
            "step__sequence", "approver__username", "status")),
        "payroll.run": list(PayrollRun.objects.filter(**co).values_list(
            "company__code", "period__code", "run_type", "status", "employee_count",
            "total_earning", "total_deduction", "total_net")),
        "payroll.line": list(PayrollRunEmployee.objects.filter(run__company__code__in=codes, run__is_deleted=False, is_deleted=False).values_list(
            "run__company__code", "run__period__code", "employee__employee_number", "status", "is_excluded",
            "gross_earning", "total_deduction", "net_pay", "employer_contribution", "currency__code")),
        "payroll.component": list(PayrollRunComponent.objects.filter(
            run_employee__run__company__code__in=codes, run_employee__run__is_deleted=False, is_deleted=False,
        ).values_list("run_employee__run__company__code", "run_employee__run__period__code",
                      "run_employee__employee__employee_number", "component_type", "code", "amount")),
    }

    digests = {name: {"rows": len(rows), "sha256": _digest(rows)} for name, rows in sections.items()}
    digests["overall"] = {
        "rows": sum(v["rows"] for v in digests.values()),
        "sha256": _digest([(k, v["sha256"]) for k, v in sorted(digests.items())]),
    }

    return digests


# ======================================================================
# Populasi & kelengkapan pegawai (DEMO-1E)
# ======================================================================


def population() -> dict:
    """Tenant peragaan hanya memuat EMP001–EMP040 — pegawai lain = selisih."""
    import re

    from apps.hr.models import Employee

    from .constants import EMPLOYEE_NUMBER_PATTERN

    numbers = sorted(Employee._base_manager.filter(is_deleted=False).values_list("employee_number", flat=True))
    dataset = [n for n in numbers if re.match(EMPLOYEE_NUMBER_PATTERN, n)]

    return {
        "total": len(numbers),
        "dataset": len(dataset),
        "expected": dataset == [f"EMP{n:03d}" for n in range(1, 41)],
        "other": [n for n in numbers if n not in dataset],
        "soft_deleted": Employee._base_manager.filter(is_deleted=True).count(),
    }


#: Kolom wajib peragaan vs kolom yang sengaja opsional (alasan di laporan).
REQUIRED_IDENTITY = (
    "nik", "birth_place", "birth_date", "gender", "marital_status", "nationality", "religion",
    "blood_type", "personal_email", "work_email", "phone", "mobile", "address", "province", "city",
    "district", "village", "emergency_contact_name", "emergency_contact_phone", "tax_number",
)
OPTIONAL_IDENTITY = ("passport_number",)
REQUIRED_EMPLOYMENT = (
    "organization.company", "organization.branch", "organization.location", "organization.division",
    "organization.department", "organization.position", "organization.job_level",
    "organization.cost_center", "employment.employment_status", "employment.employment_type",
    "employment.employee_group", "employment.join_date",
)
OPTIONAL_EMPLOYMENT = (
    "organization.section", "organization.job_grade", "employment.point_of_hire",
    "employment.probation_type", "employment.work_schedule",
)


def employee_completeness() -> dict:
    """Jumlah KOSONG per kolom untuk EMP001–EMP040, plus data pribadi."""
    from apps.hr.models import EmployeeBankAccount, EmployeeEducation, EmployeeFamily, PayrollAssignment

    from .apply import owned_employees

    employees = owned_employees()

    def value(employee, path):
        obj = employee
        for part in path.split("."):
            obj = getattr(obj, part, None)
            if obj is None:
                return None
        return obj

    def missing(paths):
        return {p: sum(1 for e in employees if value(e, p) in (None, "")) for p in paths}

    reports_to_missing = [
        e.employee_number for e in employees if e.organization.reports_to_id is None
    ]

    def lacking(model, **extra):
        have = set(model.objects.filter(employee__in=employees, is_deleted=False, **extra)
                   .values_list("employee_id", flat=True))
        return sum(1 for e in employees if e.pk not in have)

    return {
        "employees": len(employees),
        "required_identity": missing(REQUIRED_IDENTITY),
        "optional_identity": missing(OPTIONAL_IDENTITY),
        "required_employment": missing(REQUIRED_EMPLOYMENT),
        "optional_employment": missing(OPTIONAL_EMPLOYMENT),
        "reports_to_missing": reports_to_missing,
        "calendar_or_roster_missing": sum(
            1 for e in employees
            if not (e.employment.working_calendar_id or e.employment.roster_policy_id)
        ),
        "contract_dates_missing_for_contract": sum(
            1 for e in employees
            if e.employment.contract_type_id and not (e.employment.contract_start and e.employment.contract_end)
        ),
        "bank_account_missing": lacking(EmployeeBankAccount, is_primary=True),
        "family_missing": lacking(EmployeeFamily),
        "emergency_family_missing": lacking(EmployeeFamily, is_emergency_contact=True),
        "education_missing": lacking(EmployeeEducation, is_highest_education=True),
        "payroll_assignment_missing": lacking(PayrollAssignment, is_current=True),
        "statutory_missing": sum(
            1 for a in PayrollAssignment.objects.filter(employee__in=employees, is_current=True, is_deleted=False)
            if not (a.tax_number_payroll and a.bpjs_kesehatan_number and a.bpjs_ketenagakerjaan_number)
        ),
    }


def company_set() -> list[str]:
    """Seluruh company di tenant (termasuk yang dihapus lunak) — DEMO-1F."""
    from apps.administration.models import Company

    return sorted(Company._base_manager.values_list("code", flat=True))


def legacy_references() -> dict:
    """
    Pegawai dataset yang masih menyentuh objek di luar GRP/MMN/MIN lewat
    organisasi, kepegawaian (roster/kalender), rotasi, atau baris setup.
    Harus kosong sesudah DEMO-1F.
    """
    from apps.hr.models import EmploymentAssignment, OrganizationAssignment, RosterSetupLine, SiteRotation

    from .apply import owned_employees
    from .constants import OWNED_COMPANY_CODES

    employees = owned_employees()
    found = {}
    checks = {
        "organization.company": OrganizationAssignment.objects.filter(employee__in=employees).exclude(
            company__code__in=OWNED_COMPANY_CODES),
        "organization.location": OrganizationAssignment.objects.filter(
            employee__in=employees, location__isnull=False).exclude(
            location__company__code__in=OWNED_COMPANY_CODES),
        "employment.roster_policy": EmploymentAssignment.objects.filter(
            employee__in=employees, roster_policy__isnull=False).exclude(
            roster_policy__company__code__in=OWNED_COMPANY_CODES),
        "employment.working_calendar": EmploymentAssignment.objects.filter(
            employee__in=employees, working_calendar__company__isnull=False).exclude(
            working_calendar__company__code__in=OWNED_COMPANY_CODES),
        "site_rotation.roster_policy": SiteRotation.objects.filter(
            employee__in=employees, roster_policy__isnull=False).exclude(
            roster_policy__company__code__in=OWNED_COMPANY_CODES),
        "roster_setup_line.roster_policy": RosterSetupLine.objects.filter(
            employee__in=employees, roster_policy__isnull=False).exclude(
            roster_policy__company__code__in=OWNED_COMPANY_CODES),
    }
    for name, qs in checks.items():
        n = qs.count()
        if n:
            found[name] = n

    return found
