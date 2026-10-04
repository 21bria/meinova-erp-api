"""
Penyemai dataset trial (TRL) — Fase 1, fondasi.

Yang dibangun di sini **hanya** yang tidak bergantung pada tanggal
berjalan: master milik trial, enam pegawai beserta rantai penugasannya,
saldo awal cuti, dan rencana shift. Absensi, cuti, lembur, periode,
run, workflow, dan Finance sengaja **tidak** disentuh — semuanya lahir
di fase berikutnya, sesudah bulannya benar-benar lewat.

Tiga aturan yang membentuk seluruh berkas ini:

1. **Tidak ada PK yang ditulis di kode.** Seluruh rujukan kanonik
   dicari lewat kunci bisnis yang stabil (kode company, kode shift,
   kode template). PK hasil `create` memang dicatat — tapi ke manifest,
   sesudahnya, bukan sebagai masukan.
2. **Keadaan setengah jadi membatalkan, bukan dilengkapi diam-diam.**
   Penyemai yang "melanjutkan" dataset yang rusak menghasilkan trial
   yang tidak ada yang tahu isinya. Tiga keadaan yang dikenali: belum
   ada sama sekali, sudah lengkap, dan selain itu — yang ketiga selalu
   berhenti.
3. **Master kanonik tidak pernah disunting.** Penyemai ini hanya
   membaca Company, Shift, Template, TaxStatus, dan kawan-kawannya.
   Yang ditulisnya cuma baris baru miliknya sendiri.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.db import transaction


TRIAL_PREFIX = "TRL"

EMPLOYEE_NUMBERS = ("TRL01", "TRL02", "TRL03", "TRL04", "TRL05", "TRL06")

PERIOD_START = date(2026, 9, 1)
PERIOD_END = date(2026, 9, 30)

#: Model transaksional yang tidak boleh bertambah satu baris pun di
#: Fase 1. Diperiksa sebagai **selisih**, bukan nol mutlak: tenant
#: nyata memang sudah berisi (demo punya satu PayrollPeriod dan satu
#: PayrollRun bersejarah), dan yang dilarang adalah penyemai ini
#: menambahinya.
FORBIDDEN_PHASE_1_MODELS = (
    "payroll.PayrollPeriod",
    "payroll.PayrollRun",
    "payroll.PayrollRunEmployee",
    "workflow.WorkflowInstance",
    "workflow.WorkflowApproval",
    "notifications.NotificationLog",
    "administration.Notification",
    "finance.AccountingEvent",
    "finance.Journal",
    "finance.JournalLine",
)


class TrialSeedAborted(RuntimeError):
    """Preflight menolak. Tidak ada baris yang ditulis."""

    def __init__(self, blockers):
        self.blockers = list(blockers)

        super().__init__(
            f"{len(self.blockers)} penghalang: " + " | ".join(self.blockers),
        )


@dataclass(frozen=True)
class EmployeePlan:
    """Satu pegawai trial, seluruh keputusannya sudah jadi nilai."""

    tag: str
    first_name: str
    last_name: str
    basic_salary: str
    join_date: date
    payroll_group_code: str
    allowance_template_code: str
    #: Kosong = tidak eligible lembur dan tidak menunjuk kelompok mana pun.
    overtime_group_code: str = ""
    #: Kosong = `payroll_policy` NULL, jadi ikut PayrollSetting company.
    payroll_policy_code: str = ""


@dataclass(frozen=True)
class TrialSeedSpec:
    trial_id: str
    schema_names: tuple[str, ...]

    # --- kunci bisnis rujukan kanonik ---------------------------------
    company_code: str
    branch_code: str
    location_code: str
    department_code: str
    section_code: str
    work_schedule_code: str
    work_calendar_code: str
    shift_code: str
    currency_code: str
    tax_status_code: str
    annual_leave_type_code: str
    unpaid_leave_type_code: str

    # --- master milik trial -------------------------------------------
    overtime_group_code: str
    overtime_tiers: tuple[tuple[int, str, str | None, str], ...]
    daily_policy_code: str
    daily_policy_divisor: str

    employees: tuple[EmployeePlan, ...]

    #: Saldo awal cuti tahunan TRL04 — pegawai yang tahun 2026-nya
    #: dipegang sistem lama, jadi jatahnya tidak pernah terbit sendiri.
    opening_balance_tag: str
    opening_balance_days: str

    manifest_dir: str

    protected_counts: tuple[tuple[str, int], ...] = ()

    @property
    def tags(self) -> tuple[str, ...]:
        return tuple(plan.tag for plan in self.employees)


@dataclass
class TrialSeedReport:
    trial_id: str = ""
    executed: bool = False
    already_seeded: bool = False

    notes: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)

    #: {label: jumlah} yang AKAN atau SUDAH dibuat.
    planned: dict = field(default_factory=dict)
    created: dict = field(default_factory=dict)

    #: Rujukan kanonik yang dipakai, {kunci bisnis: pk}.
    canonical: dict = field(default_factory=dict)

    manifest: dict = field(default_factory=dict)
    manifest_path: str = ""

    @property
    def is_blocked(self) -> bool:
        return bool(self.blockers)

    @property
    def planned_total(self) -> int:
        return sum(self.planned.values())


class TrialSeedService:
    """Fase 1 dataset trial. Mode kering bawaan, eksekusi eksplisit."""

    # ------------------------------------------------------------------
    # Pintu masuk
    # ------------------------------------------------------------------

    @classmethod
    def plan(cls, *, spec: TrialSeedSpec) -> TrialSeedReport:
        report = TrialSeedReport(trial_id=spec.trial_id)

        cls._preflight(spec=spec, report=report)

        if report.is_blocked:
            return report

        cls._build_plan(spec=spec, report=report)

        return report

    @classmethod
    def execute(cls, *, spec: TrialSeedSpec, user=None) -> TrialSeedReport:
        """
        Semua atau tidak sama sekali.

        Manifest ditulis **sesudah** transaksi berhasil: berkas yang
        menyebut id hasil transaksi yang di-rollback adalah berkas yang
        berdusta, dan dustanya baru ketahuan saat orang memakai id itu
        untuk purge.
        """
        with transaction.atomic():
            report = cls.plan(spec=spec)

            if report.is_blocked:
                raise TrialSeedAborted(report.blockers)

            if report.already_seeded:
                # Tidak ada yang perlu dikerjakan, dan itu bukan
                # kegagalan. Manifest yang sudah ada tetap berlaku.
                return report

            before = cls._forbidden_snapshot()

            cls._create(spec=spec, report=report, user=user)
            cls._assert_forbidden_absent(spec=spec, before=before)

            report.executed = True

        cls._write_manifest(spec=spec, report=report)

        return report

    # ------------------------------------------------------------------
    # Preflight
    # ------------------------------------------------------------------

    @classmethod
    def _preflight(cls, *, spec, report) -> None:
        cls._check_tenant(spec=spec, report=report)

        if report.is_blocked:
            return

        from django.db import DatabaseError

        checks = (
            cls._check_canonical_keys,
            cls._check_trial_state,
            cls._check_department_clean,
            cls._check_protected_baseline,
        )

        for check in checks:
            try:
                with transaction.atomic():
                    check(spec=spec, report=report)
            except DatabaseError as exc:
                report.blockers.append(
                    f"PEMERIKSAAN GAGAL: {check.__name__} ({exc}).",
                )

    @classmethod
    def _check_tenant(cls, *, spec, report) -> None:
        from django.db import connection
        from django_tenants.utils import get_public_schema_name

        schema = connection.schema_name

        if schema == get_public_schema_name():
            report.blockers.append(
                "TENANT: penyemai dijalankan di schema public. "
                "Gunakan tenant_command --schema=<tenant>.",
            )
            return

        if schema not in spec.schema_names:
            report.blockers.append(
                f"TENANT: schema '{schema}' tidak ada di daftar yang "
                f"diizinkan {list(spec.schema_names)}.",
            )
            return

        report.notes.append(f"Tenant: {schema}")
        report.notes.append(f"Trial ID: {spec.trial_id}")

    # --- rujukan kanonik ----------------------------------------------

    @classmethod
    def _canonical_lookups(cls, spec):
        """
        `{label: (model, filter)}` — setiap satu harus menghasilkan
        **tepat satu** baris. Bukan `.first()`: kunci yang cocok dengan
        dua baris berarti master yang ambigu, dan memilih yang pertama
        berarti trial menempel pada baris yang tidak pernah dipilih
        siapa pun.
        """
        from apps.administration.models import (
            Branch,
            Company,
            Currency,
            Department,
            LeaveType,
            Location,
            Section,
            Shift,
            WorkCalendar,
            WorkSchedule,
        )
        from apps.payroll.models import (
            AllowanceTemplate,
            DeductionTemplate,
            PayrollGroup,
            TaxStatus,
        )

        company = {"code": spec.company_code, "is_deleted": False}

        lookups = {
            "company": (Company, company),
            "branch": (
                Branch,
                {
                    "code": spec.branch_code,
                    "company__code": spec.company_code,
                    "is_deleted": False,
                },
            ),
            "location": (
                Location,
                {
                    "code": spec.location_code,
                    "company__code": spec.company_code,
                    "is_deleted": False,
                },
            ),
            "department": (
                Department,
                {
                    "code": spec.department_code,
                    "company__code": spec.company_code,
                    "is_deleted": False,
                },
            ),
            "section": (
                Section,
                {
                    "code": spec.section_code,
                    "department__code": spec.department_code,
                    "department__company__code": spec.company_code,
                    "is_deleted": False,
                },
            ),
            "work_schedule": (
                WorkSchedule,
                {"code": spec.work_schedule_code, "is_deleted": False},
            ),
            "work_calendar": (
                WorkCalendar,
                {
                    "code": spec.work_calendar_code,
                    "company__isnull": True,
                    "is_deleted": False,
                },
            ),
            "shift": (Shift, {"code": spec.shift_code, "is_deleted": False}),
            "currency": (
                Currency, {"code": spec.currency_code, "is_deleted": False},
            ),
            "tax_status": (
                TaxStatus, {"code": spec.tax_status_code, "is_deleted": False},
            ),
            "leave_type_annual": (
                LeaveType,
                {"code": spec.annual_leave_type_code, "is_deleted": False},
            ),
            "leave_type_unpaid": (
                LeaveType,
                {"code": spec.unpaid_leave_type_code, "is_deleted": False},
            ),
            "deduction_template": (
                DeductionTemplate, {"code": "STANDARD", "is_deleted": False},
            ),
        }

        for code in sorted({p.payroll_group_code for p in spec.employees}):
            lookups[f"payroll_group:{code}"] = (
                PayrollGroup, {"code": code, "is_deleted": False},
            )

        for code in sorted({p.allowance_template_code for p in spec.employees}):
            lookups[f"allowance_template:{code}"] = (
                AllowanceTemplate, {"code": code, "is_deleted": False},
            )

        return lookups

    @classmethod
    def _check_canonical_keys(cls, *, spec, report) -> None:
        for label, (model, filters) in cls._canonical_lookups(spec).items():
            rows = list(
                model._base_manager.filter(**filters).values_list(
                    "pk", flat=True,
                )[:3],
            )

            if len(rows) == 1:
                report.canonical[label] = rows[0]
                continue

            report.blockers.append(
                f"KANONIK: kunci '{label}' menghasilkan {len(rows)} baris, "
                "seharusnya tepat satu.",
            )

    # --- keadaan trial -------------------------------------------------

    @classmethod
    def _trial_employees(cls, spec):
        from apps.hr.models import Employee

        return Employee._base_manager.filter(
            employee_number__in=spec.tags,
        )

    @classmethod
    def _check_trial_state(cls, *, spec, report) -> None:
        """
        Tiga keadaan, dan yang ketiga selalu berhenti.

        Yang paling berbahaya bukan "sudah ada" melainkan "ada
        sebagian": penyemai yang melengkapinya akan mencampur baris
        lama yang entah dari mana dengan baris baru, dan manifest-nya
        jadi tidak menggambarkan apa pun.
        """
        from apps.hr.models import (
            EmploymentAssignment,
            OrganizationAssignment,
            PayrollAssignment,
        )
        from apps.hr.models.shift_assignment import EmployeeShiftAssignment

        existing = {
            row.employee_number: row
            for row in cls._trial_employees(spec)
        }

        if not existing:
            stray = [
                f"{name}={count}"
                for name, count in cls._trial_master_state(spec).items()
                if count
            ]

            if stray:
                report.blockers.append(
                    "MASTER TRIAL TANPA PEGAWAI: "
                    f"{', '.join(stray)} sudah ada padahal tidak satu pun "
                    "pegawai trial ada. Baris itu bukan milik penyemaian "
                    "ini; memakainya berarti trial menempel pada master "
                    "yang tidak pernah diperiksa. Purge dulu.",
                )
                return

            report.notes.append(
                "Keadaan trial: BELUM ADA — seluruh baris akan dibuat.",
            )
            return

        missing = [tag for tag in spec.tags if tag not in existing]

        if missing:
            report.blockers.append(
                f"TRIAL SETENGAH JADI: {len(existing)} dari "
                f"{len(spec.tags)} pegawai trial sudah ada; yang belum: "
                f"{', '.join(missing)}. Penyemai tidak melengkapi "
                "keadaan setengah jadi.",
            )
            return

        # Enam-enamnya ada. Rantai penugasannya harus utuh juga.
        ids = [row.pk for row in existing.values()]

        incomplete = []

        for label, model, filters in (
            ("EmploymentAssignment", EmploymentAssignment, {}),
            ("OrganizationAssignment", OrganizationAssignment, {}),
            (
                "PayrollAssignment", PayrollAssignment,
                {"is_current": True},
            ),
            (
                "EmployeeShiftAssignment", EmployeeShiftAssignment,
                {"start_date": PERIOD_START, "end_date": PERIOD_END},
            ),
        ):
            count = model._base_manager.filter(
                employee_id__in=ids, is_deleted=False, **filters,
            ).count()

            if count != len(spec.tags):
                incomplete.append(f"{label}={count}")

        for name, count in cls._trial_master_state(spec).items():
            if count != 1:
                incomplete.append(f"{name}={count}")

        opening = cls._opening_state(spec=spec, employees=existing)

        if opening is None:
            incomplete.append("LeaveOpeningBalance(posted)=0")

        if incomplete:
            report.blockers.append(
                "TRIAL RUSAK: keenam pegawai trial ada, tapi rantainya "
                f"tidak utuh ({', '.join(incomplete)}). Perbaiki atau "
                "purge dulu; penyemai tidak menambal.",
            )
            return

        report.already_seeded = True
        report.notes.append(
            "Keadaan trial: SUDAH LENGKAP — tidak ada yang perlu dibuat.",
        )

    @classmethod
    def _trial_master_state(cls, spec) -> dict:
        """
        Master yang **hanya** milik trial, dengan kodenya sendiri.

        `PayrollLeaveRule` sengaja tidak ada di sini: ia berlaku
        se-tenant, satu baris per jenis cuti, dan memang boleh sudah
        ada sebelum trial lahir — memakai ulang yang ada adalah
        kontraknya, bukan tabrakan.
        """
        from apps.payroll.models import OvertimeGroup, PayrollPolicy

        return {
            f"OvertimeGroup({spec.overtime_group_code})": (
                OvertimeGroup._base_manager.filter(
                    code=spec.overtime_group_code, is_deleted=False,
                ).count()
            ),
            f"PayrollPolicy({spec.daily_policy_code})": (
                PayrollPolicy._base_manager.filter(
                    code=spec.daily_policy_code,
                    company__code=spec.company_code,
                    is_deleted=False,
                ).count()
            ),
        }

    @classmethod
    def _opening_state(cls, *, spec, employees):
        from apps.hr.models import LeaveOpeningBalance, LeaveOpeningStatus

        employee = employees.get(spec.opening_balance_tag)

        if employee is None:
            return None

        return (
            LeaveOpeningBalance._base_manager.filter(
                employee=employee,
                leave_type__code=spec.annual_leave_type_code,
                status=LeaveOpeningStatus.POSTED,
                is_deleted=False,
            )
            .first()
        )

    @classmethod
    def _check_department_clean(cls, *, spec, report) -> None:
        """
        Department sasaran tidak boleh berisi pegawai non-trial.

        Bukan soal kerapian: cakupan run fase berikutnya adalah
        department ini, jadi satu pegawai asing di dalamnya akan ikut
        terbayar oleh payroll trial.
        """
        from apps.hr.models import OrganizationAssignment

        intruders = list(
            OrganizationAssignment._base_manager
            .filter(
                department__code=spec.department_code,
                department__company__code=spec.company_code,
                is_deleted=False,
            )
            .exclude(employee__employee_number__in=spec.tags)
            .values_list("employee__employee_number", flat=True)[:5],
        )

        if intruders:
            report.blockers.append(
                f"CAKUPAN: department {spec.department_code} berisi "
                f"pegawai non-trial ({', '.join(intruders)}). Run trial "
                "akan ikut membayarnya.",
            )
            return

        report.notes.append(
            f"Department {spec.department_code}: bersih dari pegawai "
            "non-trial.",
        )

    @classmethod
    def _check_protected_baseline(cls, *, spec, report) -> None:
        """
        Pagar **sebelum menulis**, jadi tidak berlaku kalau tidak ada
        yang akan ditulis.

        Sesudah penyemaian berhasil, angka tenant memang sudah termasuk
        baris trial itu sendiri (hr.Employee bertambah enam). Menyebut
        itu selisih berarti menyuruh operator memakai bypass untuk
        keadaan idempoten yang justru sah.
        """
        from django.apps import apps

        if report.already_seeded:
            report.notes.append(
                "Baseline terlindungi: dilewati — trial sudah tersemai "
                "dan tidak ada baris yang akan ditulis.",
            )
            return

        for label, expected in spec.protected_counts:
            model = apps.get_model(label)
            actual = model._base_manager.count()

            if actual != expected:
                report.blockers.append(
                    f"BASELINE: {label} berisi {actual} baris, "
                    f"seharusnya {expected}.",
                )

    # ------------------------------------------------------------------
    # Rencana
    # ------------------------------------------------------------------

    @classmethod
    def _build_plan(cls, *, spec, report) -> None:
        if report.already_seeded:
            report.planned = {label: 0 for label in cls._labels(spec)}
            return

        from apps.payroll.models import (
            OvertimeGroup,
            PayrollLeaveRule,
            PayrollPolicy,
        )

        count = len(spec.employees)

        rule_exists = PayrollLeaveRule._base_manager.filter(
            leave_type__code=spec.unpaid_leave_type_code,
            is_deleted=False,
        ).exists()

        group_exists = OvertimeGroup._base_manager.filter(
            code=spec.overtime_group_code, is_deleted=False,
        ).exists()

        policy_exists = PayrollPolicy._base_manager.filter(
            code=spec.daily_policy_code,
            company__code=spec.company_code,
            is_deleted=False,
        ).exists()

        if rule_exists:
            report.notes.append(
                "PayrollLeaveRule untuk cuti tanpa upah sudah ada — "
                "dipakai apa adanya, tidak dibuat ulang.",
            )

        report.planned = {
            "payroll.PayrollLeaveRule": 0 if rule_exists else 1,
            "payroll.OvertimeGroup": 0 if group_exists else 1,
            "payroll.OvertimeGroupTier": (
                0 if group_exists else len(spec.overtime_tiers)
            ),
            "payroll.PayrollPolicy": 0 if policy_exists else 1,
            "hr.Employee": count,
            "hr.EmploymentAssignment": count,
            "hr.OrganizationAssignment": count,
            "hr.PayrollAssignment": count,
            "hr.EmployeeShiftAssignment": count,
            "hr.LeaveOpeningBalance": 1,
        }

    @staticmethod
    def _labels(spec):
        return (
            "payroll.PayrollLeaveRule",
            "payroll.OvertimeGroup",
            "payroll.OvertimeGroupTier",
            "payroll.PayrollPolicy",
            "hr.Employee",
            "hr.EmploymentAssignment",
            "hr.OrganizationAssignment",
            "hr.PayrollAssignment",
            "hr.EmployeeShiftAssignment",
            "hr.LeaveOpeningBalance",
        )

    # ------------------------------------------------------------------
    # Penulisan
    # ------------------------------------------------------------------

    @classmethod
    def _create(cls, *, spec, report, user=None) -> None:
        canonical = report.canonical
        created = {label: 0 for label in cls._labels(spec)}

        masters = cls._create_masters(
            spec=spec, report=report, created=created,
        )

        employees = cls._create_employees(
            spec=spec,
            report=report,
            created=created,
            canonical=canonical,
            masters=masters,
        )

        cls._create_opening_balance(
            spec=spec,
            report=report,
            created=created,
            employees=employees,
            user=user,
        )

        report.created = created

        if created != report.planned:
            # Rencana dan hasil harus cocok baris per baris. Selisih
            # berarti ada yang lahir atau gagal lahir di luar rencana,
            # dan manifest yang menyusul tidak akan menggambarkannya.
            raise TrialSeedAborted(
                [
                    "HASIL TIDAK COCOK RENCANA: "
                    f"rencana={report.planned} hasil={created}.",
                ],
            )

    @classmethod
    def _create_masters(cls, *, spec, report, created) -> dict:
        from apps.payroll.models import (
            OvertimeGroup,
            OvertimeGroupTier,
            OvertimeTierBasis,
            PayrollDailyRateMethod,
            PayrollLeaveRule,
            PayrollPayBasis,
            PayrollPolicy,
        )

        masters: dict = {}

        rule = PayrollLeaveRule._base_manager.filter(
            leave_type_id=report.canonical["leave_type_unpaid"],
            is_deleted=False,
        ).first()

        if rule is None:
            rule = PayrollLeaveRule.objects.create(
                leave_type_id=report.canonical["leave_type_unpaid"],
                is_unpaid=True,
                notes=f"{spec.trial_id} — cuti tanpa upah tidak dibayar.",
            )
            created["payroll.PayrollLeaveRule"] += 1

        masters["leave_rule"] = rule

        group = OvertimeGroup._base_manager.filter(
            code=spec.overtime_group_code, is_deleted=False,
        ).first()

        if group is None:
            group = OvertimeGroup.objects.create(
                code=spec.overtime_group_code,
                name="Trial Tiered Overtime",
                description=f"{spec.trial_id}",
                hourly_multiplier=Decimal("1.00"),
                hourly_divisor=Decimal("173"),
                tier_basis=OvertimeTierBasis.DAILY,
                is_active=True,
            )
            created["payroll.OvertimeGroup"] += 1

            for sequence, low, high, multiplier in spec.overtime_tiers:
                OvertimeGroupTier.objects.create(
                    group=group,
                    sequence=sequence,
                    hour_from=Decimal(low),
                    hour_to=Decimal(high) if high is not None else None,
                    multiplier=Decimal(multiplier),
                    is_active=True,
                )
                created["payroll.OvertimeGroupTier"] += 1

        masters["overtime_group"] = group

        policy = PayrollPolicy._base_manager.filter(
            code=spec.daily_policy_code,
            company_id=report.canonical["company"],
            is_deleted=False,
        ).first()

        if policy is None:
            policy = PayrollPolicy.objects.create(
                company_id=report.canonical["company"],
                code=spec.daily_policy_code,
                name="Trial Daily",
                description=f"{spec.trial_id}",
                pay_basis=PayrollPayBasis.DAILY,
                daily_rate_method=PayrollDailyRateMethod.FROM_MONTHLY,
                daily_rate_divisor=Decimal(spec.daily_policy_divisor),
                # Tidak ada bawaan di model, dan validasi run menolak
                # kebijakan harian yang belum menyatakannya.
                pay_paid_leave="yes",
                is_active=True,
            )
            created["payroll.PayrollPolicy"] += 1

        masters["daily_policy"] = policy

        return masters

    @classmethod
    def _create_employees(
        cls, *, spec, report, created, canonical, masters,
    ) -> dict:
        from apps.hr.models import (
            Employee,
            EmploymentAssignment,
            OrganizationAssignment,
            PayrollAssignment,
        )
        from apps.hr.models.shift_assignment import (
            EmployeeShiftAssignment,
            ShiftAssignmentKind,
            ShiftAssignmentLayer,
        )
        from apps.payroll.models import AllowanceTemplate, PayrollGroup

        employees: dict = {}

        for plan in spec.employees:
            employee = Employee.objects.create(
                employee_number=plan.tag,
                first_name=plan.first_name,
                last_name=plan.last_name,
            )
            created["hr.Employee"] += 1

            OrganizationAssignment.objects.create(
                employee=employee,
                company_id=canonical["company"],
                branch_id=canonical["branch"],
                location_id=canonical["location"],
                department_id=canonical["department"],
                section_id=canonical["section"],
                organization_effective_date=plan.join_date,
                organization_notes=spec.trial_id,
            )
            created["hr.OrganizationAssignment"] += 1

            EmploymentAssignment.objects.create(
                employee=employee,
                join_date=plan.join_date,
                work_schedule_id=canonical["work_schedule"],
                working_calendar_id=canonical["work_calendar"],
                # Cadangan permanen, di bawah lapis BASELINE. Dua lapis
                # yang saling menguatkan: tanggal di luar rencana shift
                # tetap punya jam kerja.
                shift_id=canonical["shift"],
                employment_notes=spec.trial_id,
            )
            created["hr.EmploymentAssignment"] += 1

            group = PayrollGroup._base_manager.get(
                code=plan.payroll_group_code, is_deleted=False,
            )
            allowance = AllowanceTemplate._base_manager.get(
                code=plan.allowance_template_code, is_deleted=False,
            )

            overtime_group = (
                masters["overtime_group"]
                if plan.overtime_group_code
                else None
            )
            policy = (
                masters["daily_policy"]
                if plan.payroll_policy_code
                else None
            )

            PayrollAssignment.objects.create(
                employee=employee,
                payroll_group=group,
                currency_id=canonical["currency"],
                tax_status_id=canonical["tax_status"],
                overtime_eligible=overtime_group is not None,
                overtime_group=overtime_group,
                basic_salary=Decimal(plan.basic_salary),
                allowance_template=allowance,
                deduction_template_id=canonical["deduction_template"],
                payroll_policy=policy,
                effective_from=plan.join_date,
                is_current=True,
                payroll_notes=spec.trial_id,
            )
            created["hr.PayrollAssignment"] += 1

            EmployeeShiftAssignment.objects.create(
                employee=employee,
                shift_id=canonical["shift"],
                kind=ShiftAssignmentKind.WORK,
                layer=ShiftAssignmentLayer.BASELINE,
                start_date=PERIOD_START,
                end_date=PERIOD_END,
                reason=spec.trial_id,
            )
            created["hr.EmployeeShiftAssignment"] += 1

            employees[plan.tag] = employee

        return employees

    @classmethod
    def _create_opening_balance(
        cls, *, spec, report, created, employees, user=None,
    ) -> None:
        """
        Saldo awal cuti tahunan, lewat lifecycle kanonik.

        Kartu saldonya **tidak** dibuat langsung: `post()` yang
        menerbitkannya, sama seperti 26 baris saldo awal yang sudah ada
        di tenant. Membuat `LeaveBalance` dengan tangan berarti angka
        yang tidak pernah lahir dari dokumen mana pun.
        """
        from apps.hr.api.leave_opening.services import (
            LeaveOpeningBalanceService,
        )
        from apps.hr.models import LeaveOpeningSource

        employee = employees[spec.opening_balance_tag]

        instance = LeaveOpeningBalanceService.create(
            data={
                "employee": employee,
                "leave_type_id": report.canonical["leave_type_annual"],
                "days": Decimal(spec.opening_balance_days),
                "source": LeaveOpeningSource.MANUAL,
                "remark": (
                    f"{spec.trial_id} — sisa cuti tahunan yang "
                    "diserahkan sistem lama per go-live."
                ),
            },
            user=user,
        )
        created["hr.LeaveOpeningBalance"] += 1

        LeaveOpeningBalanceService.post(instance=instance, user=user)

        report.manifest["_opening_instance"] = instance

    @staticmethod
    def _forbidden_snapshot() -> dict:
        from django.apps import apps

        return {
            label: apps.get_model(label)._base_manager.count()
            for label in FORBIDDEN_PHASE_1_MODELS
        }

    @classmethod
    def _assert_forbidden_absent(cls, *, spec, before) -> None:
        """
        Fase 1 tidak boleh melahirkan satu pun baris transaksional.

        Dua sudut pandang, karena satu saja tidak cukup. Absensi, cuti,
        dan lembur diperiksa **per pegawai trial** — baris milik orang
        lain bukan urusan penyemai ini. Periode, run, workflow,
        notifikasi, dan Finance diperiksa sebagai **selisih global**,
        karena baris di sana tidak selalu menunjuk pegawai dan tenant
        nyata sudah punya isi sebelumnya.

        Diperiksa **di dalam** transaksi: kalau toh ada yang lolos,
        seluruh penyemaian batal, bukan dilaporkan sesudah fakta.
        """
        from apps.hr.models import EmployeeLeave, EmployeeOvertime
        from apps.hr.models.attendance import EmployeeAttendance

        ids = list(cls._trial_employees(spec).values_list("pk", flat=True))

        forbidden = (
            ("hr.EmployeeAttendance", EmployeeAttendance),
            ("hr.EmployeeLeave", EmployeeLeave),
            ("hr.EmployeeOvertime", EmployeeOvertime),
        )

        found = []

        for label, model in forbidden:
            count = model._base_manager.filter(employee_id__in=ids).count()

            if count:
                found.append(f"{label}={count}")

        after = cls._forbidden_snapshot()

        found.extend(
            f"{label} {before[label]} -> {after[label]}"
            for label in FORBIDDEN_PHASE_1_MODELS
            if after[label] != before[label]
        )

        if found:
            raise TrialSeedAborted(
                [
                    "FASE 1 MELAHIRKAN TRANSAKSI: " + ", ".join(found),
                ],
            )

    # ------------------------------------------------------------------
    # Manifest
    # ------------------------------------------------------------------

    @classmethod
    def build_manifest(cls, *, spec, report) -> dict:
        from django.db import connection
        from django.utils import timezone

        from apps.hr.models import (
            EmploymentAssignment,
            LeaveBalance,
            OrganizationAssignment,
            PayrollAssignment,
        )
        from apps.hr.models.shift_assignment import EmployeeShiftAssignment
        from apps.payroll.models import (
            OvertimeGroup,
            OvertimeGroupTier,
            PayrollLeaveRule,
            PayrollPolicy,
        )

        employees = {
            row.employee_number: row
            for row in cls._trial_employees(spec)
        }
        ids = [row.pk for row in employees.values()]

        def chain(model, **filters):
            return dict(
                model._base_manager
                .filter(employee_id__in=ids, is_deleted=False, **filters)
                .values_list("employee__employee_number", "pk")
            )

        opening = cls._opening_state(spec=spec, employees=employees)

        balance = None

        if opening is not None:
            balance = (
                LeaveBalance._base_manager
                .filter(
                    employee=opening.employee,
                    leave_type=opening.leave_type,
                    year=opening.year,
                    is_deleted=False,
                )
                .first()
            )

        group = OvertimeGroup._base_manager.filter(
            code=spec.overtime_group_code, is_deleted=False,
        ).first()

        policy = PayrollPolicy._base_manager.filter(
            code=spec.daily_policy_code,
            company__code=spec.company_code,
            is_deleted=False,
        ).first()

        rule = PayrollLeaveRule._base_manager.filter(
            leave_type__code=spec.unpaid_leave_type_code, is_deleted=False,
        ).first()

        return {
            "_note": (
                "Manifest dataset trial. Dibangkitkan perintah "
                "seed_trial_dataset; jangan disunting tangan. Dipakai "
                "untuk audit dan purge trial."
            ),
            "trial_id": spec.trial_id,
            "tenant": connection.schema_name,
            "repo_head": cls._repo_head(),
            "generated_at": timezone.now().isoformat(),
            "phase": "1-foundation",
            "canonical_references": {
                "note": (
                    "Master kanonik yang DIRUJUK trial. Tidak pernah "
                    "disunting, tidak pernah ikut purge."
                ),
                "keys": cls._canonical_keys_for_manifest(spec),
                "resolved_ids": dict(sorted(report.canonical.items())),
            },
            "created_exclusive_trial_objects": {
                "note": (
                    "Lahir untuk trial ini dan tidak dipakai apa pun di "
                    "luarnya. Aman dibuang saat purge trial."
                ),
                "payroll.OvertimeGroup": (
                    [group.pk] if group else []
                ),
                "payroll.OvertimeGroupTier": sorted(
                    OvertimeGroupTier._base_manager
                    .filter(group=group, is_deleted=False)
                    .values_list("pk", flat=True)
                ) if group else [],
                "payroll.PayrollPolicy": [policy.pk] if policy else [],
                "hr.Employee": dict(
                    sorted((tag, row.pk) for tag, row in employees.items()),
                ),
                "hr.EmploymentAssignment": chain(EmploymentAssignment),
                "hr.OrganizationAssignment": chain(OrganizationAssignment),
                "hr.PayrollAssignment": chain(PayrollAssignment),
                "hr.EmployeeShiftAssignment": chain(
                    EmployeeShiftAssignment,
                    start_date=PERIOD_START,
                    end_date=PERIOD_END,
                ),
                "hr.LeaveOpeningBalance": (
                    {
                        "id": opening.pk,
                        "employee": spec.opening_balance_tag,
                        "leave_type": spec.annual_leave_type_code,
                        "opening_date": opening.opening_date.isoformat(),
                        "year": opening.year,
                        "days": str(opening.days),
                        "source": opening.source,
                        "status": opening.status,
                        "posted_at": (
                            opening.posted_at.isoformat()
                            if opening.posted_at else None
                        ),
                    }
                    if opening else None
                ),
                "hr.LeaveBalance": (
                    {
                        "id": balance.pk,
                        "year": balance.year,
                        "entitlement": str(balance.entitlement),
                        "opening_balance": str(balance.opening_balance),
                        "used": str(balance.used),
                        "remaining": str(balance.remaining),
                        "provenance": (
                            "diterbitkan LeaveOpeningBalanceService.post(), "
                            "bukan dibuat langsung"
                        ),
                    }
                    if balance else None
                ),
            },
            "tenant_shared_created_for_trial": {
                "note": (
                    "Dibuat untuk trial TAPI berlaku se-tenant — model "
                    "ini tidak punya kolom company. JANGAN dibuang "
                    "otomatis saat purge; pembuangannya keputusan sadar."
                ),
                "payroll.PayrollLeaveRule": (
                    {
                        "id": rule.pk,
                        "leave_type": spec.unpaid_leave_type_code,
                        "is_unpaid": rule.is_unpaid,
                        "scope": "tenant-wide (model tanpa kolom company)",
                        "created_by_trial": bool(
                            report.created.get(
                                "payroll.PayrollLeaveRule", 0,
                            ),
                        ),
                    }
                    if rule else None
                ),
            },
            "forbidden_in_phase_1": {
                "note": "Harus nol sampai Fase 2.",
                "models": [
                    "hr.EmployeeAttendance",
                    "hr.EmployeeLeave",
                    "hr.EmployeeOvertime",
                    "payroll.PayrollPeriod (trial)",
                    "payroll.PayrollRun (trial)",
                    "workflow.WorkflowInstance (trial)",
                    "finance.AccountingEvent",
                    "finance.Journal",
                ],
            },
            "protected_baseline": cls._protected_snapshot(spec),
        }

    @staticmethod
    def _canonical_keys_for_manifest(spec) -> dict:
        return {
            "company": spec.company_code,
            "branch": spec.branch_code,
            "location": spec.location_code,
            "department": spec.department_code,
            "section": spec.section_code,
            "work_schedule": spec.work_schedule_code,
            "work_calendar": f"{spec.work_calendar_code} (company IS NULL)",
            "shift": spec.shift_code,
            "currency": spec.currency_code,
            "tax_status": spec.tax_status_code,
            "leave_type_annual": spec.annual_leave_type_code,
            "leave_type_unpaid": spec.unpaid_leave_type_code,
            "deduction_template": "STANDARD",
            "allowance_templates": sorted(
                {p.allowance_template_code for p in spec.employees},
            ),
            "payroll_groups": sorted(
                {p.payroll_group_code for p in spec.employees},
            ),
        }

    @classmethod
    def _protected_snapshot(cls, spec) -> dict:
        from django.apps import apps

        snapshot = {}

        for label, _ in spec.protected_counts:
            snapshot[label] = apps.get_model(label)._base_manager.count()

        return snapshot

    @staticmethod
    def _repo_head() -> str:
        import subprocess

        try:
            return subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True, text=True, timeout=10, check=True,
            ).stdout.strip()
        except Exception:  # noqa: BLE001 — manifest tidak boleh gagal di sini
            return "unknown"

    @classmethod
    def _write_manifest(cls, *, spec, report) -> None:
        report.manifest.pop("_opening_instance", None)

        manifest = cls.build_manifest(spec=spec, report=report)

        directory = Path(spec.manifest_dir)

        if not directory.is_absolute():
            # Relatif terhadap akar repo, bukan terhadap direktori kerja
            # proses. Manifest yang mendarat di tempat berbeda tiap kali
            # perintah dipanggil dari direktori lain bukan manifest yang
            # durable.
            from django.conf import settings

            directory = Path(settings.BASE_DIR) / directory

        directory.mkdir(parents=True, exist_ok=True)

        path = directory / f"{spec.trial_id}.json"
        path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        report.manifest = manifest
        report.manifest_path = str(path)
