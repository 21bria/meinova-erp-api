"""
Penerapan baseline dataset Meinova ERP (DEMO-1B).

Setiap tulisan lewat service/seed kanonik yang sudah ada — tidak ada
`update_or_create` ke tabel bisnis dari sini:

    organisasi   seed_organization(OrganizationDataset)
    Finance      seed_chart_of_accounts / seed_fiscal_years / seed_payroll_policy
    akun         User + NotificationSettingService + grant_role
    pegawai      EmployeeService.create (OrganizationService/EmploymentService)
    gaji pokok   PayrollAssignmentService.create
    identitas    identity.IDENTITIES → EmployeeService.update, EmployeeFamilyService,
                 EmployeeBankService, EmployeeEducationService,
                 PayrollAssignmentService.update (NPWP/BPJS; status pajak tetap)
    roster       RosterSetupService.create → preview → commit (tanpa alur, seperti HR-DEMO-1)
    presensi     EmployeeAttendanceService.create → AttendanceClosingService.close(employees=…)
    dokumen      EmployeeLeaveService / AttendancePermissionService / EmployeeOvertimeService,
                 approver = yang diresolusi mesin (`_run_workflow` HR-DEMO-3)
    payroll      PayrollPeriodService → PayrollRunService.create/generate_employees/calculate

**Baseline berhenti di REVIEW.** Tidak ada finalize, tidak ada
PAYROLL_POSTED, AccountingEvent, atau jurnal (keputusan DEMO-1B §14).

Setiap fase idempoten terhadap kunci bisnisnya: baris yang sudah ada
dan milik dataset dilewati, bukan ditulis ulang.
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from . import mapping
from .constants import (
    ATTENDANCE_EXTERNAL_PREFIX,
    DOCUMENT_NOTE_PREFIX,
    FISCAL_YEAR,
    OWNED_COMPANY_CODES,
    REFERENCE_DATE,
)
from .organization import BRANCH_CODE, build_dataset
from .planner import planned_people
from .workbook import Workbook


class ApplyError(Exception):
    """Fase gagal; transaksi pemanggil harus di-rollback."""


#: Jendela presensi: awal penugasan workbook s.d. sehari sebelum tanggal acuan.
ATTENDANCE_START = date(2026, 8, 1)
ATTENDANCE_END = REFERENCE_DATE - timedelta(days=1)

#: Tanggal mulai kerja pegawai tetap (keputusan DEMO-1B §1).
PERMANENT_JOIN_DATE = date(2025, 1, 1)

#: Status pajak baseline. DEMO-1E melengkapi status kawin & keluarga
#: (`identity.derived_tax_status`), tapi 18 pegawai akan berpindah ke K/n dan
#: net pay enam run naik Rp 4.411.967,74 — ditahan TK/0 sampai disetujui (§E).
TAX_STATUS = "TK/0"

#: Horizon rencana roster dari 1 Agustus: menutup seluruh September
#: dan skenario cuti 29–30 September.
ROSTER_HORIZON_MONTHS = 3

#: Blok lembur per hari, menit.
OVERTIME_BLOCK_MINUTES = 120

DEVICE_CODE = "DEMOERP"


@dataclass
class ApplyResult:
    phases: dict[str, dict] = field(default_factory=dict)
    documents: list[dict] = field(default_factory=list)
    unsupported: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


# ======================================================================
# Entry
# ======================================================================


def run(workbook: Workbook, *, log) -> ApplyResult:
    result = ApplyResult()
    ctx = _Context(workbook=workbook, log=log, result=result)

    for name, phase in (
        ("organization", _organization),
        ("finance", _finance),
        ("roster_policies", _roster_policies),
        ("users", _users),
        ("employees", _employees),
        ("payroll_assignments", _payroll_assignments),
        ("identity", _identity),
        ("roster", _roster),
        ("attendance", _attendance),
        ("documents", _documents),
        ("closing", _closing),
        ("payroll", _payroll),
    ):
        log(f"-- fase {name}")
        result.phases[name] = phase(ctx) or {}
        log(f"   {result.phases[name]}")

    return result


@dataclass
class _Context:
    workbook: Workbook
    log: object
    result: ApplyResult
    people: dict = field(default_factory=dict)
    companies: dict = field(default_factory=dict)
    employees: dict = field(default_factory=dict)
    users: dict = field(default_factory=dict)
    overtime: dict | None = None

    def __post_init__(self):
        self.people = planned_people(self.workbook)

    def company(self, code):
        from apps.administration.models import Company

        if code not in self.companies:
            self.companies[code] = Company.objects.get(code=code, is_deleted=False)

        return self.companies[code]

    def org(self, model, company, code):
        return model.objects.get(company=self.company(company), code=code, is_deleted=False)

    def reference(self, model, code):
        return model.objects.get(code=code, is_deleted=False)


def join_date(ctx: _Context, employee_id: str) -> date:
    """
    Keputusan DEMO-1B §1: kontrak = Contract Start dataset; tetap =
    2025-01-01. Pegawai kontrak tanpa masa kontrak di dataset tidak
    punya Contract Start — ia memakai tanggal mulai kerja peragaan yang
    sama dengan pegawai tetap.
    """
    for row in ctx.workbook.contracts:
        if row.employee_id == employee_id:
            return row.start

    return PERMANENT_JOIN_DATE


# ======================================================================
# Organisasi & Finance
# ======================================================================


def _organization(ctx: _Context) -> dict:
    from apps.administration.seeds.organization import seed_organization

    dataset = build_dataset(ctx.workbook)
    seed_organization(dataset)

    return {
        "companies": len(dataset.companies),
        "branches": len(dataset.branches),
        "locations": len(dataset.locations),
        "divisions": len(dataset.divisions),
        "departments": len(dataset.departments),
        "cost_centers": len(dataset.cost_centers),
        "positions": len(dataset.positions),
    }


def _finance(ctx: _Context) -> dict:
    """Mesin bootstrap Finance yang sama dengan `seed_finance`, per company."""
    from apps.finance.seeds import (
        seed_chart_of_accounts,
        seed_fiscal_years,
        seed_payroll_policy,
    )

    summary = {}

    for code in OWNED_COMPANY_CODES:
        company = ctx.company(code)
        coa = seed_chart_of_accounts(company=company)
        fiscal = seed_fiscal_years(companies=[company], year=FISCAL_YEAR)
        policy = seed_payroll_policy(company=company)
        summary[code] = {"coa": coa, "fiscal": fiscal, "policy": policy}

    return summary


def _roster_policies(ctx: _Context) -> dict:
    """
    DEMO-1F: policy roster MMN dari `roster_policy.POLICIES` lewat
    RosterPolicyService / RosterShiftRotationService / RosterTravelDayService.
    Idempoten per kunci bisnis (company + kode, urutan rotasi, kota POH);
    hanya kolom yang berbeda yang ditulis.
    """
    from apps.administration.api.reference.hr.views.roster_policy import (
        RosterPolicyService,
        RosterShiftRotationService,
        RosterTravelDayService,
    )
    from apps.administration.models import (
        Location,
        RosterPolicy,
        RosterShiftRotation,
        RosterTravelDay,
        RotationPurpose,
        Shift,
    )

    from . import roster_policy as source

    counts = {"policies_created": 0, "policies_updated": 0, "rotations_written": 0,
              "travel_days_written": 0, "stale_removed": 0}
    company = ctx.company(source.COMPANY)
    location = ctx.org(Location, source.COMPANY, source.LOCATION)
    purposes = [RotationPurpose.objects.get(code=c, is_deleted=False) for c in source.URGENT_PURPOSES]

    for spec in source.POLICIES:
        wanted = {**spec.fields(), "company": company, "location": location}
        policy = RosterPolicy.objects.filter(company=company, code=spec.code, is_deleted=False).first()

        if policy is None:
            policy = RosterPolicyService.create(data={**wanted, "urgent_purposes": purposes}, user=None)
            counts["policies_created"] += 1
        else:
            diff = {k: v for k, v in wanted.items() if getattr(policy, k) != v}
            if set(policy.urgent_purposes.values_list("code", flat=True)) != set(source.URGENT_PURPOSES):
                diff["urgent_purposes"] = purposes
            if diff:
                policy = RosterPolicyService.update(instance=policy, data=diff, user=None)
                counts["policies_updated"] += 1

        # Rotasi shift per urutan.
        existing = {r.sequence: r for r in RosterShiftRotation.objects.filter(policy=policy, is_deleted=False)}
        for sequence, shift_code, days in source.ROTATION:
            data = {"policy": policy, "sequence": sequence, "block_days": days, "notes": source.ROTATION_NOTE,
                    "shift": Shift.objects.get(code=shift_code, is_deleted=False), "is_active": True}
            row = existing.pop(sequence, None)
            if row is None:
                RosterShiftRotationService.create(data=data, user=None)
                counts["rotations_written"] += 1
            else:
                diff = {k: v for k, v in data.items() if getattr(row, k) != v}
                if diff:
                    RosterShiftRotationService.update(instance=row, data=diff, user=None)
                    counts["rotations_written"] += 1
        for row in existing.values():
            row.delete()
            counts["stale_removed"] += 1

        # Hari perjalanan per kota POH.
        existing = {
            (t.point_of_hire.code, t.point_of_hire.province.code): t
            for t in RosterTravelDay.objects.filter(policy=policy, is_deleted=False)
            .select_related("point_of_hire__province")
        }
        for city_key, out_days, in_days in spec.travel_days:
            data = {"policy": policy, "point_of_hire": source.resolve_city(city_key),
                    "travel_out_days": out_days, "travel_in_days": in_days, "is_active": True}
            row = existing.pop(city_key, None)
            if row is None:
                RosterTravelDayService.create(data=data, user=None)
                counts["travel_days_written"] += 1
            else:
                diff = {k: v for k, v in data.items() if getattr(row, k) != v}
                if diff:
                    RosterTravelDayService.update(instance=row, data=diff, user=None)
                    counts["travel_days_written"] += 1
        for row in existing.values():
            row.delete()
            counts["stale_removed"] += 1

    return counts


# ======================================================================
# Akun & role
# ======================================================================


def _users(ctx: _Context) -> dict:
    from django.contrib.auth import get_user_model

    from apps.accounts.models import Role
    from apps.accounts.services.role_assignment import grant_role
    from apps.administration.api.notification.services.notification_service import (
        NotificationSettingService,
    )
    from apps.core.services.demo_password import demo_password

    User = get_user_model()
    grants = mapping.scope_grants(ctx.workbook)
    created = granted = emails_updated = 0

    for employee_id, person in ctx.people.items():
        user = User.objects.filter(username=person.username).first()

        if user is None:
            user = User.objects.create_user(
                username=person.username,
                email=mapping.user_email(person.row),
                password=demo_password(),
                first_name=person.row.first_name,
                last_name=person.row.last_name,
            )
            created += 1
        elif user.email != mapping.user_email(person.row):
            # Alamat akun mengikuti sumber (DEMO-1E). Hanya kolom `email`,
            # pola `demo_account_emails`: password/penanda aktif tidak ditulis ulang.
            user.email = mapping.user_email(person.row)
            user.full_clean(exclude=["password"])
            user.save(update_fields=["email"])
            emails_updated += 1

        # Surel notifikasi dimatikan **per akun** dan tersimpan: dicek
        # saat worker mengirim, jadi antrean yang terbentuk sekarang
        # tidak pernah terkirim walau worker nanti jalan dengan `.env`
        # yang mengaktifkan surel. Lonceng in-app tetap hidup.
        setting = NotificationSettingService.get_settings(user)

        if setting.email_enabled:
            setting.email_enabled = False
            setting.save(update_fields=["email_enabled"])

        ctx.users[employee_id] = user

        for grant in [mapping.BASE_GRANT] + grants.get(employee_id, []):
            role = Role.objects.get(code=grant.role, is_deleted=False, is_active=True)
            before = user.role_assignments.filter(role=role).exists() if hasattr(
                user, "role_assignments"
            ) else None

            grant_role(
                user,
                role,
                mode=grant.mode,
                level=grant.level or "",
                authorities=[_authority(ctx, kind, key) for kind, key in grant.authorities],
            )

            if before is False:
                granted += 1

    return {
        "users_created": created, "users_total": len(ctx.users), "grants_added": granted,
        "emails_updated": emails_updated,
    }


def _authority(ctx: _Context, kind: str, key):
    from apps.administration.models import Department, Location

    if kind == "own":
        return ("own", None)

    if kind == "company":
        return ("company", ctx.company(key).pk)

    company, code = key.split("/")

    if kind == "location":
        return ("location", ctx.org(Location, company, code).pk)

    if kind == "department":
        return ("department", ctx.org(Department, company, code).pk)

    raise ApplyError(f"Jenis authority tidak dikenal: {kind}")


# ======================================================================
# Pegawai
# ======================================================================


def _creation_order(ctx: _Context) -> list[str]:
    """Atasan lebih dulu: urut kedalaman rantai reports_to."""

    def depth(employee_id):
        row, steps = ctx.workbook.employee(employee_id), 0

        while row.reports_to:
            row, steps = ctx.workbook.employee(row.reports_to), steps + 1

        return steps

    return sorted(ctx.people, key=lambda e: (depth(e), e))


def _employees(ctx: _Context) -> dict:
    from apps.administration.models import (
        Branch,
        ContractType,
        CostCenter,
        Department,
        Division,
        EmployeeGroup,
        EmploymentStatus,
        EmploymentType,
        JobLevel,
        Location,
        Position,
        Shift,
        WorkCalendar,
    )
    from apps.hr.api.employee.services.employee_service import EmployeeService
    from apps.hr.models import Employee

    from . import ownership

    schedule_of = {row.employee_id: mapping.SCHEDULE[row.policy_code] for row in ctx.workbook.roster_assignments}
    contracts = {row.employee_id: row for row in ctx.workbook.contracts}
    created = existing = 0

    for employee_id in _creation_order(ctx):
        person = ctx.people[employee_id]
        row = person.row

        found = Employee.objects.filter(employee_number=employee_id, is_deleted=False).first()

        if found is not None:
            if not ownership.is_owned_employee(found):
                raise ApplyError(f"{employee_id} ada tapi bukan milik dataset ini.")

            ctx.employees[employee_id] = found
            existing += 1
            continue

        company = person.company
        location = ctx.org(Location, company, person.location)
        department = ctx.org(Department, company, person.department)
        joined = join_date(ctx, employee_id)
        schedule = schedule_of[employee_id]
        contract = contracts.get(employee_id)

        organization = {
            "company": ctx.company(company),
            "branch": ctx.org(Branch, company, BRANCH_CODE),
            "location": location,
            "division": department.division,
            "department": department,
            "position": ctx.org(Position, company, person.position),
            "job_level": ctx.reference(JobLevel, person.job_level),
            "cost_center": ctx.org(CostCenter, company, f"{company}-{person.department}"),
            "reports_to": ctx.employees.get(row.reports_to) if row.reports_to else None,
            "organization_effective_date": joined,
        }

        employment = {
            "employment_type": ctx.reference(EmploymentType, mapping.EMPLOYMENT_TYPE[row.employment]),
            "employment_status": ctx.reference(EmploymentStatus, mapping.EMPLOYMENT_STATUS[row.status]),
            "employee_group": ctx.reference(EmployeeGroup, person.group),
            "join_date": joined,
            "employment_effective_date": joined,
        }

        if contract is not None:
            employment.update({
                "contract_type": ctx.reference(ContractType, mapping.CONTRACT_TYPE),
                "contract_start": contract.start,
                "contract_end": contract.end,
            })

        if schedule.roster_policy is None:
            employment.update({
                "working_calendar": WorkCalendar.objects.get(
                    code=schedule.working_calendar, company__isnull=True, is_deleted=False,
                ),
                "shift": ctx.reference(Shift, schedule.shift),
            })

        employee = EmployeeService.create(
            {
                "employee_number": employee_id,
                "first_name": row.first_name,
                "last_name": row.last_name,
                "work_email": mapping.user_email(row),
                "notes": mapping.employee_note(row),
                "user": ctx.users[employee_id],
                "is_active": True,
                "organization": organization,
                "employment": employment,
            },
            user=None,
        )

        ctx.employees[employee_id] = employee
        created += 1

    return {"created": created, "existing": existing}


def _payroll_assignments(ctx: _Context) -> dict:
    from apps.administration.models import Currency
    from apps.hr.api.payroll_assignment.services import PayrollAssignmentService
    from apps.hr.models import PayrollAssignment
    from apps.payroll.models import (
        AllowanceTemplate,
        DeductionTemplate,
        OvertimeGroup,
        PayrollGroup,
        TaxStatus,
    )

    created = existing = 0

    for employee_id in sorted(ctx.people):
        employee = ctx.employees[employee_id]
        row = ctx.people[employee_id].row

        if PayrollAssignment.objects.filter(employee=employee, is_deleted=False).exists():
            existing += 1
            continue

        salary, _basis = mapping.basic_salary(row, ctx.workbook)
        site = mapping.overtime_eligible(row)

        PayrollAssignmentService.create(
            data={
                "employee": employee,
                "effective_from": join_date(ctx, employee_id),
                "basic_salary": Decimal(salary),
                "currency": Currency.objects.get(code="IDR", is_deleted=False),
                "payroll_group": ctx.reference(PayrollGroup, "MONTHLY"),
                "allowance_template": ctx.reference(AllowanceTemplate, "STANDARD"),
                "deduction_template": ctx.reference(DeductionTemplate, "STANDARD"),
                "tax_status": ctx.reference(TaxStatus, TAX_STATUS),
                "overtime_eligible": site,
                "overtime_group": ctx.reference(OvertimeGroup, "SHIFT") if site else None,
                "payment_method": "bank_transfer",
            },
            user=None,
        )
        created += 1

    return {"created": created, "existing": existing}


# ======================================================================
# Identitas & data pribadi (DEMO-1E)
# ======================================================================


def _master(label: str, code: str):
    from django.apps import apps as django_apps

    model = django_apps.get_model(label)
    qs = model.objects.filter(code=code)

    if any(f.name == "is_deleted" for f in model._meta.fields):
        qs = qs.filter(is_deleted=False)

    found = list(qs[:2])

    if len(found) != 1:
        raise ApplyError(f"Master {label} {code!r}: {len(found)} baris (harus tepat satu).")

    return found[0]


def identity_fields(identity, row) -> dict:
    """Kolom Employee yang diisi tabel identitas — nilai, bukan PK."""
    return {
        "nik": identity.nik,
        "tax_number": identity.tax_number,
        "passport_number": identity.passport_number,
        "gender": _master("administration.Gender", identity.gender),
        "religion": _master("administration.Religion", identity.religion),
        "nationality": _master("administration.Nationality", identity_module().NATIONALITY),
        "blood_type": _master("administration.BloodType", identity.blood_type),
        "marital_status": _master("administration.MaritalStatus", identity.marital_status),
        "birth_place": identity.birth_place,
        "birth_date": identity.birth_date,
        "address": identity.street,
        "province": _master("administration.Province", identity.province),
        "city": _master("administration.City", identity.city),
        "district": _master("administration.District", identity.district),
        "village": _master("administration.Village", identity.village),
        "personal_email": identity.personal_email(row.first_name, row.last_name),
        "work_email": mapping.user_email(row),
        "phone": identity.phone,
        "mobile": identity.mobile,
        "emergency_contact_name": identity.emergency_contact.full_name,
        "emergency_contact_phone": identity.emergency_phone,
    }


def identity_module():
    from . import identity

    return identity


def _identity(ctx: _Context) -> dict:
    """
    Tabel `identity.IDENTITIES` → EmployeeService.update (hanya kolom yang
    berbeda), keluarga/rekening/pendidikan lewat service-nya masing-masing,
    nomor BPJS/NPWP payroll lewat PayrollAssignmentService.update (koreksi
    record, bukan versi baru). Status pajak **tidak** disentuh.
    """
    from apps.hr.api.employee.services.employee_service import EmployeeService
    from apps.hr.api.employee_bank.services import EmployeeBankService
    from apps.hr.api.employee_education.services import EmployeeEducationService
    from apps.hr.api.employee_family.services import EmployeeFamilyService
    from apps.hr.api.payroll_assignment.services import PayrollAssignmentService
    from apps.hr.models import EmployeeBankAccount, EmployeeEducation, EmployeeFamily, PayrollAssignment

    identities = identity_module().BY_EMPLOYEE
    counts = {
        "employees_updated": 0, "fields_written": 0,
        "family_created": 0, "family_updated": 0,
        "bank_created": 0, "bank_updated": 0,
        "education_created": 0, "education_updated": 0,
        "payroll_statutory_updated": 0, "stale_removed": 0,
    }

    missing = sorted(set(ctx.people) - set(identities))

    if missing:
        raise ApplyError(f"Tabel identitas tidak memuat {missing}.")

    for employee_id in sorted(ctx.people):
        identity = identities[employee_id]
        row = ctx.people[employee_id].row
        employee = ctx.employees[employee_id]
        marker = f"{identity_module().PERSONAL_NOTE_PREFIX}{employee_id}] identitas sintetis DEMO-1E"

        # --- Employee -------------------------------------------------
        wanted = identity_fields(identity, row)
        diff = {k: v for k, v in wanted.items() if getattr(employee, k) != v}

        if diff:
            employee = EmployeeService.update(employee, diff, user=None)
            ctx.employees[employee_id] = employee
            counts["employees_updated"] += 1
            counts["fields_written"] += len(diff)

        # --- Data pribadi: create/update per kunci bisnis ---------------
        emergency = identity.emergency_contact
        family = [
            ((r.relationship, r.full_name), {
                "employee": employee,
                "relationship": _master("administration.FamilyRelationship", r.relationship),
                "full_name": r.full_name,
                "gender": _master("administration.Gender", r.gender),
                "birth_date": r.birth_date,
                "phone": identity.emergency_phone if r == emergency else "",
                # Tanggungan dalam arti data HR (BPJS): pasangan & anak.
                # Status pajak diturunkan terpisah (`derived_tax_status`).
                "is_dependent": r.relationship in ("SPOUSE", "CHILD"),
                "is_emergency_contact": r == emergency,
                "notes": marker,
            })
            for r in identity.relatives
        ]
        bank = [((identity.bank, identity.account_number), {
            "employee": employee,
            "bank": _master("administration.Bank", identity.bank),
            "account_number": identity.account_number,
            "account_name": f"{row.first_name} {row.last_name}".upper(),
            "branch_name": identity.bank_branch,
            "currency": _master("administration.Currency", "IDR"),
            "is_primary": True,
            "notes": marker,
        })]
        edu = identity.education
        education = [((edu.level, edu.institution), {
            "employee": employee,
            "education": _master("administration.Education", edu.level),
            "degree": _master("administration.Degree", edu.degree) if edu.degree else None,
            "study_field": _master("administration.StudyField", edu.study_field) if edu.study_field else None,
            "institution_name": edu.institution,
            "city": edu.city,
            "country": "Indonesia",
            "graduation_year": edu.graduation_year,
            "is_highest_education": True,
            "notes": marker,
        })]

        for name, model, service, key_of, rows in (
            ("family", EmployeeFamily, EmployeeFamilyService,
             lambda o: (o.relationship.code, o.full_name), family),
            ("bank", EmployeeBankAccount, EmployeeBankService,
             lambda o: (o.bank.code, o.account_number), bank),
            ("education", EmployeeEducation, EmployeeEducationService,
             lambda o: (o.education.code, o.institution_name), education),
        ):
            counts_key = name
            existing = {key_of(o): o for o in model.objects.filter(employee=employee, is_deleted=False)}

            for key, obj in existing.items():
                if not obj.notes.startswith(identity_module().PERSONAL_NOTE_PREFIX):
                    raise ApplyError(
                        f"{employee_id}: {model.__name__} {key} tanpa penanda dataset — baris asing."
                    )

            for key, data in rows:
                obj = existing.pop(key, None)

                if obj is None:
                    service.create(data=data, user=None)
                    counts[f"{counts_key}_created"] += 1
                    continue

                changed = {k: v for k, v in data.items() if k != "employee" and getattr(obj, k) != v}

                if changed:
                    service.update(instance=obj, data=changed, user=None)
                    counts[f"{counts_key}_updated"] += 1

            # Baris milik dataset yang tidak lagi ada di sumber.
            for obj in existing.values():
                obj.delete()
                counts["stale_removed"] += 1

        # --- Nomor statutori di PayrollAssignment (bukan status pajak) ---
        assignment = PayrollAssignment.objects.get(employee=employee, is_current=True, is_deleted=False)
        statutory = {
            "tax_number_payroll": identity.tax_number,
            "bpjs_kesehatan_number": identity.bpjs_kesehatan,
            "bpjs_ketenagakerjaan_number": identity.bpjs_ketenagakerjaan,
        }
        changed = {k: v for k, v in statutory.items() if getattr(assignment, k) != v}

        if changed:
            PayrollAssignmentService.update(instance=assignment, data=changed, user=None)
            counts["payroll_statutory_updated"] += 1

    return counts


# ======================================================================
# Roster
# ======================================================================


def _roster(ctx: _Context) -> dict:
    """
    Jalan kanonik HR-DEMO-1: RosterSetupService.create → baris →
    preview → commit langsung (tanpa alur). Policy = milik MMN dari
    `roster_policy.POLICIES` (DEMO-1F; sebelumnya policy MMR dipakai ulang).
    Kalau preview menolak, fase ini gagal dan tidak ada yang ditulis.
    """
    from apps.administration.models import Location
    from apps.hr.api.roster.setup_service import RosterSetupLineService, RosterSetupService

    from . import roster_policy as roster_policy_source
    from apps.hr.models import SiteRotation

    targets = [
        (row.employee_id, mapping.SCHEDULE[row.policy_code].roster_policy, row.effective_from)
        for row in ctx.workbook.roster_assignments
        if mapping.SCHEDULE[row.policy_code].roster_policy
    ]

    live = set(
        SiteRotation.objects.filter(
            employee__in=[ctx.employees[e] for e, _, _ in targets],
            is_deleted=False,
            effective_to__isnull=True,
        ).values_list("employee__employee_number", flat=True)
    )

    pending = [target for target in targets if target[0] not in live]

    if not pending:
        _reload_employees(ctx)

        return {"committed": 0, "existing": len(live)}

    by_site: dict[tuple, list] = {}

    for employee_id, policy_code, start in pending:
        person = ctx.people[employee_id]
        by_site.setdefault((person.company, person.location), []).append((employee_id, policy_code, start))

    committed = 0
    previews = []

    for (company, location_code), rows in sorted(by_site.items()):
        location = ctx.org(Location, company, location_code)
        as_of = min(start for _, _, start in rows)

        request = RosterSetupService.create(
            data={
                "company": location.company,
                "location": location,
                "as_of_date": as_of,
                "horizon_months": ROSTER_HORIZON_MONTHS,
                "notes": f"{DOCUMENT_NOTE_PREFIX}ROSTER-{company}-{location_code}] Meinova ERP demo",
            },
            user=None,
        )

        for employee_id, policy_code, start in rows:
            RosterSetupLineService.create(
                data={
                    "request": request,
                    "employee": ctx.employees[employee_id],
                    # Company + kode (DEMO-1F): policy MMN milik dataset.
                    "roster_policy": roster_policy_source.policy(policy_code),
                    "current_cycle_start": start,
                },
                user=None,
            )

        preview = RosterSetupService.preview(request=request)
        previews.append({
            "site": f"{company}/{location_code}",
            "can_commit": preview.get("can_commit"),
            "lines": len(rows),
        })

        if not preview.get("can_commit"):
            raise ApplyError(
                "Preview RosterSetupService menolak penugasan policy kanonik "
                f"untuk {company}/{location_code}: {preview}"
            )

        RosterSetupService.commit(request=request, user=None)
        request.refresh_from_db()

        failed = [
            (line.employee.employee_number, line.commit_error)
            for line in request.lines.select_related("employee")
            if getattr(line, "commit_error", "")
        ]

        if failed:
            raise ApplyError(f"Commit roster gagal untuk sebagian baris: {failed}")

        committed += len(rows)

    _reload_employees(ctx)

    return {"committed": committed, "existing": len(live), "previews": previews}


def _reload_employees(ctx: _Context) -> None:
    """
    Instance pegawai yang dipegang sejak fase pegawai membawa
    `employment` versi **sebelum** roster di-commit (roster_policy
    kosong). Jadwal yang dihitung dari instance basi itu = kalender
    kantor, sementara penutup hari membaca ulang dari basis data =
    roster. Dimuat ulang supaya seluruh fase sesudahnya membaca keadaan
    yang sama dengan mesin.
    """
    from apps.hr.models import Employee

    fresh = Employee.objects.filter(
        pk__in=[employee.pk for employee in ctx.employees.values()],
    ).select_related("organization", "employment")

    ctx.employees = {employee.employee_number: employee for employee in fresh}


# ======================================================================
# Presensi
# ======================================================================


def _document_days(ctx: _Context) -> dict[str, set[date]]:
    """Hari cuti/izin skenario: tidak ada tap mesin di hari itu."""
    days: dict[str, set[date]] = {}

    for row in ctx.workbook.leaves:
        if row.request_id in UNSUPPORTED_SCENARIOS:
            continue

        employee_id = mapping.scenario_employee(row)
        current, last = mapping.scenario_dates(row)

        while current <= last:
            days.setdefault(employee_id, set()).add(current)
            current += timedelta(days=1)

    return days


def overtime_plan(ctx: _Context) -> dict[tuple[str, date], tuple[int, object]]:
    """
    Jam lembur workbook → dokumen lembur 2 jam di hari kerja terjadwal,
    hanya untuk pegawai yang berhak lembur (PayrollAssignment
    overtime_eligible). Pegawai kantor tidak berhak lembur di baseline
    ini, dan payroll workbook memang mencatat lembur mereka 0.
    """
    from apps.hr.api.attendance.schedule import scheduled_work_days
    from apps.hr.models import PayrollAssignment

    if ctx.overtime is not None:
        return ctx.overtime

    eligible = set(
        PayrollAssignment.objects.filter(
            employee__in=ctx.employees.values(),
            is_current=True,
            is_deleted=False,
            overtime_eligible=True,
        ).values_list("employee__employee_number", flat=True)
    )

    blocked = _document_days(ctx)
    plan: dict[tuple[str, date], tuple[int, object]] = {}

    for row in ctx.workbook.attendance:
        if row.employee_id not in eligible or not row.ot_hours:
            continue

        year, month = (int(part) for part in row.period.split("-"))
        start = max(date(year, month, 1), ATTENDANCE_START)
        end = min(
            date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1),
            ATTENDANCE_END,
        )
        employee = ctx.employees[row.employee_id]
        work_days = scheduled_work_days(employee, ATTENDANCE_START, ATTENDANCE_END)
        days = []

        for day in sorted(d for d in work_days if start <= d <= end):
            if day in blocked.get(row.employee_id, set()):
                continue

            window = shift_window(employee, day, work_days)

            if window is not None:
                days.append((day, window[1]))

        remaining = row.ot_hours * 60

        for day, scheduled_out in days[1::2]:
            if remaining <= 0:
                break

            minutes = min(OVERTIME_BLOCK_MINUTES, remaining)
            plan[(row.employee_id, day)] = (minutes, _local_time(scheduled_out))
            remaining -= minutes

        if remaining > 0:
            ctx.result.notes.append(
                f"{row.employee_id} {row.period}: {remaining} menit lembur workbook tidak "
                "muat di hari kerja terjadwal dalam jendela presensi."
            )

    ctx.overtime = plan

    return plan


def shift_window(employee, day, work_days):
    """(masuk, pulang) terjadwal, atau None kalau resolver tidak memberi jam."""
    from apps.hr.api.attendance.schedule import resolve_shift, scheduled_window

    resolved = resolve_shift(employee, day)
    scheduled_in, scheduled_out = scheduled_window(
        employee, day, work_days=set(work_days), resolved=resolved,
    )

    if scheduled_in is None or scheduled_out is None:
        return None

    return scheduled_in, scheduled_out


def _local_time(moment):
    from django.utils import timezone

    return timezone.localtime(moment).time().replace(second=0, microsecond=0)


def _attendance(ctx: _Context) -> dict:
    from apps.hr.api.attendance.schedule import (
        is_roster,
        resolve_shift,
        scheduled_window,
        scheduled_work_days,
    )
    from apps.hr.api.attendance.services import EmployeeAttendanceService
    from apps.hr.applicability import HRFeature, is_applicable
    from apps.hr.models import EmployeeAttendance
    from apps.hr.models.attendance.choices import AttendanceApprovalStatus, AttendanceSource
    from apps.hr.seeds.hr_demo_attendance import (
        ABSENCE_RATE_OFFICE,
        ABSENCE_RATE_SITE,
        offsets_for,
        skips_tap,
    )

    blocked = _document_days(ctx)
    overtime = overtime_plan(ctx)
    intentional = intentional_absence_days(ctx, overtime)
    ctx.result.phases["intentional_absence"] = {
        employee_id: sorted(day.isoformat() for day in days)
        for employee_id, days in intentional.items()
    }
    ctx.result.phases["overtime_plan"] = {
        f"{e}@{d.isoformat()}": m for (e, d), (m, _) in sorted(overtime.items())
    }

    existing = set(
        EmployeeAttendance.objects.filter(
            employee__in=ctx.employees.values(),
            work_date__gte=ATTENDANCE_START,
            work_date__lte=ATTENDANCE_END,
            is_deleted=False,
        ).values_list("employee__employee_number", "work_date")
    )

    created = skipped = not_applicable = no_window = absent_draw = 0

    for employee_id in sorted(ctx.employees):
        employee = ctx.employees[employee_id]

        if not is_applicable(employee, HRFeature.ATTENDANCE):
            not_applicable += 1
            continue

        days = sorted(scheduled_work_days(employee, ATTENDANCE_START, ATTENDANCE_END))
        band_rate = ABSENCE_RATE_SITE if is_roster(employee) else ABSENCE_RATE_OFFICE

        for day in days:
            if (employee_id, day) in existing:
                skipped += 1
                continue

            if day in blocked.get(employee_id, set()):
                continue

            if day in intentional.get(employee_id, set()):
                continue

            # Pegawai etalase payroll tidak ikut undian mangkir (DEMO-1C §7).
            if employee_id not in mapping.SHOWCASE_EMPLOYEES and skips_tap(employee_id, day, band_rate):
                absent_draw += 1
                continue

            resolved = resolve_shift(employee, day)
            scheduled_in, scheduled_out = scheduled_window(
                employee, day, work_days=set(days), resolved=resolved,
            )

            if scheduled_in is None or scheduled_out is None:
                no_window += 1
                ctx.result.phases.setdefault("no_schedule_window_days", {}).setdefault(
                    employee_id, []
                ).append(day.isoformat())
                continue

            in_offset, out_offset = offsets_for(employee_id, day)
            check_in = scheduled_in + timedelta(minutes=in_offset)
            check_out = scheduled_out + timedelta(minutes=out_offset)

            extra = overtime.get((employee_id, day))

            if extra:
                check_out = scheduled_out + timedelta(minutes=extra[0] + 5)

            EmployeeAttendanceService.create(
                data={
                    "employee": employee,
                    "work_date": day,
                    "source": AttendanceSource.DEVICE,
                    "approval_status": AttendanceApprovalStatus.APPROVED,
                    "shift": getattr(resolved, "shift", None),
                    "scheduled_check_in": scheduled_in,
                    "scheduled_check_out": scheduled_out,
                    "check_in": check_in,
                    "check_out": check_out,
                    "first_check_in": check_in,
                    "last_check_out": check_out,
                    "device_code": DEVICE_CODE,
                    "external_id": f"{ATTENDANCE_EXTERNAL_PREFIX}{employee_id}-{day:%Y%m%d}",
                    "is_geofence_valid": True,
                },
                user=None,
            )
            created += 1

    return {
        "created": created,
        "existing": skipped,
        "not_applicable_employees": not_applicable,
        "random_absence_days": absent_draw,
        "no_schedule_window": no_window,
        "window": f"{ATTENDANCE_START}..{ATTENDANCE_END}",
    }


def intentional_absence_days(ctx: _Context, overtime) -> dict[str, set[date]]:
    """
    Mangkir yang disebut workbook untuk pegawai etalase, jatuh di hari
    kerja terjadwal yang bukan hari cuti/izin dan bukan hari lembur.
    Harinya deterministik: calon di indeks genap (hari lembur memakai
    indeks ganjil), diambil yang di tengah.
    """
    from apps.hr.api.attendance.schedule import scheduled_work_days

    blocked = _document_days(ctx)
    chosen: dict[str, set[date]] = {}

    for (employee_id, period), count in sorted(mapping.intentional_absences(ctx.workbook).items()):
        year, month = (int(part) for part in period.split("-"))
        start = max(date(year, month, 1), ATTENDANCE_START)
        end = min(date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1), ATTENDANCE_END)
        employee = ctx.employees[employee_id]
        days = [
            day for day in sorted(scheduled_work_days(employee, start, end))
            if day not in blocked.get(employee_id, set()) and (employee_id, day) not in overtime
        ]
        candidates = days[0::2]
        middle = len(candidates) // 2

        for day in candidates[middle:middle + count]:
            chosen.setdefault(employee_id, set()).add(day)

    return chosen


# ======================================================================
# Dokumen
# ======================================================================


def _hr_actor(ctx: _Context, employee_id: str):
    """Pencatat HR: pemegang HR-MANAGER yang ditempatkan di company pegawai."""
    company = ctx.people[employee_id].company

    for other_id, person in sorted(ctx.people.items()):
        if other_id != employee_id and person.company == company and "HR-MANAGER" in person.roles:
            return ctx.users[other_id]

    raise ApplyError(f"Tidak ada pemegang HR-MANAGER di {company} untuk mencatat {employee_id}.")


def _documents(ctx: _Context) -> dict:
    from django.core.exceptions import ValidationError

    from apps.administration.models import LeaveType
    from apps.hr.api.attendance_permission.services import AttendancePermissionService
    from apps.hr.api.leave.services import EmployeeLeaveService
    from apps.hr.api.overtime.services import EmployeeOvertimeService
    from apps.hr.models import AttendancePermission, EmployeeLeave, EmployeeOvertime
    from apps.hr.models.leave import LeaveStatus
    from apps.hr.seeds.hr_demo_documents_apply import _run_workflow

    counts = {"leave": 0, "permission": 0, "overtime": 0, "existing": 0, "skipped": 0}

    for row in ctx.workbook.leaves:
        marker = f"{DOCUMENT_NOTE_PREFIX}{row.request_id}]"
        actor_id = mapping.scenario_employee(row)
        employee = ctx.employees[actor_id]
        kind, code = mapping.LEAVE_KIND[row.leave_type]
        erp_status, _ = mapping.LEAVE_STATUS[row.status]
        entry = {
            "scenario": row.request_id,
            "employee": actor_id,
            "workbook_employee": row.employee_id,
            "substitution": mapping.SCENARIO_SUBSTITUTES.get(row.request_id, (None, ""))[1],
            "kind": kind,
            "workbook_status": row.status,
            "workbook_route": row.approval_route,
        }

        if row.request_id in UNSUPPORTED_SCENARIOS:
            counts["skipped"] += 1
            entry["result"] = f"DILEWATI — {UNSUPPORTED_SCENARIOS[row.request_id]}"
            ctx.result.documents.append(entry)
            ctx.result.unsupported.append(f"{row.request_id}: {UNSUPPORTED_SCENARIOS[row.request_id]}")
            continue

        model = EmployeeLeave if kind == "leave" else AttendancePermission
        note_field = "notes" if kind == "leave" else "reason"

        if model.objects.filter(
            employee=employee, is_deleted=False, **{f"{note_field}__startswith": marker}
        ).exists():
            counts["existing"] += 1
            entry["result"] = "SUDAH ADA"
            ctx.result.documents.append(entry)
            continue

        try:
            with _savepoint():
                start, end = mapping.scenario_dates(row)
                row = dataclasses.replace(row, employee_id=actor_id, start=start, end=end)

                if kind == "leave":
                    document, trail = _leave(ctx, row, employee, code, erp_status, marker,
                                             EmployeeLeaveService, LeaveType, LeaveStatus, _run_workflow)
                else:
                    document, trail = _permission(ctx, row, employee, erp_status, marker,
                                                  AttendancePermissionService, _run_workflow)
        except ValidationError as exc:
            entry["result"] = f"DITOLAK SERVICE — {_messages(exc)}"
            ctx.result.documents.append(entry)
            ctx.result.unsupported.append(f"{row.request_id}: ditolak service — {_messages(exc)}")
            continue

        document.refresh_from_db()

        if kind == "leave" and document.status != "recorded" and not getattr(document, "total_days", 0):
            raise ApplyError(
                f"{row.request_id}: cuti disetujui tapi 0 hari — tanggal skenario tidak "
                "jatuh di hari kerja terjadwal."
            )

        counts["leave" if kind == "leave" else "permission"] += 1
        entry.update({
            "document_number": getattr(document, "document_number", ""),
            "result": document.status,
            "total_days": str(getattr(document, "total_days", "")),
            "dates": f"{getattr(document, 'start_date', getattr(document, 'date', ''))}"
                     f"..{getattr(document, 'end_date', getattr(document, 'date', ''))}",
            "date_override": mapping.SCENARIO_DATES.get(row.request_id, (None, None, ""))[2],
            "actual_route": trail,
        })
        ctx.result.documents.append(entry)

    for (employee_id, day), (minutes, start) in sorted(overtime_plan(ctx).items()):
        employee = ctx.employees[employee_id]
        marker = f"{DOCUMENT_NOTE_PREFIX}OT-{employee_id}-{day:%Y%m%d}]"

        if EmployeeOvertime.objects.filter(
            employee=employee, is_deleted=False, notes__startswith=marker
        ).exists():
            counts["existing"] += 1
            continue

        end = (datetime.combine(day, start) + timedelta(minutes=minutes)).time()

        EmployeeOvertimeService.create(
            data={
                "employee": employee,
                "work_date": day,
                "start_time": start,
                "end_time": end,
                "status": "recorded",
                "is_paid": True,
                "reason": "Lembur produksi (skenario workbook 08_Attendance_2M)",
                "notes": f"{marker} Meinova ERP demo",
            },
            user=_hr_actor(ctx, employee_id),
        )
        counts["overtime"] += 1

    return counts


#: Skenario yang tidak bisa dijalankan apa adanya (B4), beserta alasannya.
UNSUPPORTED_SCENARIOS = {
    "LV-008": (
        "Pegawai GRP: HR-LEAVE-STD step 2 (HR-ADMIN@company, cadangan HR-MANAGER) "
        "tidak punya pemegang di GRP — pengajuan akan ditolak mesin. Status "
        "'pending' sudah diperagakan LV-004."
    ),
}


def _leave(ctx, row, employee, code, erp_status, marker, service, LeaveType, LeaveStatus, run_workflow):
    payload = {
        "employee": employee,
        "leave_type": LeaveType.objects.get(code=code, is_deleted=False),
        "start_date": row.start,
        "end_date": row.end,
        "is_half_day": False,
        "notes": f"{marker} {row.scenario}",
    }

    if erp_status == "recorded":
        leave = service.create(
            data={**payload, "status": LeaveStatus.RECORDED},
            user=_hr_actor(ctx, row.employee_id),
        )

        return leave, [("record", _hr_actor(ctx, row.employee_id).username, "recorded")]

    owner = ctx.users[row.employee_id]
    leave = service.create(data={**payload, "status": LeaveStatus.DRAFT}, user=owner)
    workflow = service.submit(instance=leave, user=owner, notes=f"{marker} submit")
    trail = [("submit", owner.username, "submitted")]

    if erp_status == "submitted":
        return leave, trail + _pending(workflow)

    trail += run_workflow(
        workflow=workflow,
        decision="reject" if erp_status == "rejected" else "approve",
        log=ctx.log,
        comment=f"{marker} keputusan skenario",
        reject_at_sequence=None,
        document_type="leave_request",
    )

    return leave, trail


def _permission(ctx, row, employee, erp_status, marker, service, run_workflow):
    from django.core.exceptions import ValidationError

    owner = ctx.users[row.employee_id]
    payload = {
        "employee": employee,
        "date": row.start,
        "permission_type": "full_day",
        "start_time": None,
        "end_time": None,
        "reason": f"{marker} {row.scenario}",
    }

    try:
        with _savepoint():
            permission = service.create(data=payload, user=owner)
    except ValidationError:
        # Satu-satunya jalan sah untuk tanggal di luar jadwal: kolom
        # `allow_outside_shift` + alasan (keputusan DEMO-1B §11).
        permission = service.create(
            data={
                **payload,
                "allow_outside_shift": True,
                "outside_shift_reason": f"{marker} Tugas di luar jadwal kantor (skenario peragaan)",
            },
            user=owner,
        )
        ctx.result.notes.append(f"{row.request_id}: dibuat dengan allow_outside_shift + alasan.")

    workflow = service.submit(permission=permission, user=owner, notes=f"{marker} submit")
    trail = [("submit", owner.username, "submitted")]

    if erp_status == "submitted":
        return permission, trail + _pending(workflow)

    trail += run_workflow(
        workflow=workflow,
        decision="reject" if erp_status == "rejected" else "approve",
        log=ctx.log,
        comment=f"{marker} keputusan skenario",
        reject_at_sequence=None,
        document_type="attendance_permission",
    )

    return permission, trail


def _pending(workflow) -> list:
    return [
        (approval.step.name, getattr(approval.approver, "username", None), "menunggu")
        for approval in workflow.approvals.select_related("step", "approver").order_by("step__sequence", "pk")
    ]


def _closing(ctx: _Context) -> dict:
    from apps.hr.api.attendance.closing import AttendanceClosingService

    return AttendanceClosingService.close(
        start=ATTENDANCE_START,
        end=ATTENDANCE_END,
        employees=list(ctx.employees.values()),
        user=None,
    )


# ======================================================================
# Payroll (berhenti di REVIEW)
# ======================================================================

PERIOD_NAMES = {"2026-08": "August 2026", "2026-09": "September 2026"}

#: Status run yang masih boleh di-generate & dihitung ulang lewat service.
RECALCULABLE_STATUSES = ("draft", "processing", "review", "rejected")


def _payroll(ctx: _Context) -> dict:
    from apps.payroll.models import PayrollGroup, PayrollPeriod, PayrollRun
    from apps.payroll.models.choices import PayrollRunStatus
    from apps.payroll.services.period import PayrollPeriodService
    from apps.payroll.services.run import PayrollRunService

    group = ctx.reference(PayrollGroup, "MONTHLY")
    # Setiap company tempat pegawai dataset ditempatkan punya payroll-nya
    # sendiri: `eligible_employees` memilih pegawai menurut
    # `organization.company` run. GRP ikut (DEMO-1C §6).
    companies = sorted({person.company for person in ctx.people.values()})
    periods = sorted({row.period for row in ctx.workbook.payroll})
    runs = []

    for code in companies:
        company = ctx.company(code)

        for period_code in periods:
            year, month = (int(part) for part in period_code.split("-"))
            start = date(year, month, 1)
            end = date(year + month // 12, month % 12 + 1, 1) - timedelta(days=1)

            period = PayrollPeriod.objects.filter(
                company=company, payroll_group=group, code=period_code, is_deleted=False,
            ).first() or PayrollPeriodService.create(
                data={
                    "company": company,
                    "payroll_group": group,
                    "code": period_code,
                    "name": PERIOD_NAMES[period_code],
                    "start_date": start,
                    "end_date": end,
                    "cutoff_date": end,
                },
                user=None,
            )

            run = (
                PayrollRun.objects.filter(period=period, run_type="regular", is_deleted=False)
                .exclude(status=PayrollRunStatus.CANCELLED)
                .first()
            )

            if run is None:
                run = PayrollRunService.create(
                    data={
                        "period": period,
                        "run_type": "regular",
                        "notes": f"{DOCUMENT_NOTE_PREFIX}PAY-{code}-{period_code}] Meinova ERP demo baseline",
                    },
                    user=None,
                )
                PayrollRunService.generate_employees(run=run, user=None)
                calculated = PayrollRunService.calculate(run=run, user=None)
            elif run.status in RECALCULABLE_STATUSES:
                # Generate ulang = snapshot PayrollAssignment terbaru untuk
                # baris yang ada + baris baru; lalu hitung ulang. Jalur
                # service biasa untuk run yang masih bisa disunting.
                PayrollRunService.generate_employees(run=run, user=None)
                calculated = PayrollRunService.calculate(run=run, user=None)
            else:
                calculated = {"existing": True, "status": run.status}

            run.refresh_from_db()

            if run.status == PayrollRunStatus.FINALIZED:
                raise ApplyError(f"{run.document_number} FINALIZED — baseline tidak boleh memfinalisasi.")

            runs.append({
                "company": code,
                "period": period_code,
                "document_number": run.document_number,
                "status": run.status,
                "employees": run.employee_count,
                "calculate": {k: v for k, v in calculated.items() if k != "validation"},
            })

    return {"runs": runs}


# ======================================================================
# Util
# ======================================================================


def _savepoint():
    from django.db import transaction

    return transaction.atomic()


def _messages(exc) -> str:
    if hasattr(exc, "message_dict"):
        return "; ".join(f"{k}: {' '.join(map(str, v))}" for k, v in exc.message_dict.items())

    return "; ".join(map(str, getattr(exc, "messages", [exc])))


def owned_employees():
    """Pegawai milik dataset (tiga lapis kepemilikan), urut nomor."""
    from apps.hr.models import Employee

    from . import ownership

    return [
        employee
        for employee in Employee.objects.filter(
            employee_number__regex=r"^EMP\d{3}$", is_deleted=False,
        ).select_related("organization__company").order_by("employee_number")
        if ownership.is_owned_employee(employee)
    ]
