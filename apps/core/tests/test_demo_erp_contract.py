"""
Kontrak keselamatan dataset Meinova ERP di atas tenant sungguhan.

Yang dibuktikan di sini bukan "rencananya bagus", melainkan bahwa
perencana **tidak bisa** merusak apa yang dilindungi:

* tidak satu pun kueri tulis keluar dari perencana;
* sidik jari RBAC, alur, Finance, MNI/MMR/MLS, pemeran HR-DEMO, dan TRL
  sama persis sebelum dan sesudah;
* baris asing (kode company/nomor pegawai yang cocok sebagian) dan
  jurnal POSTED milik dataset menghentikan reset.
"""

from __future__ import annotations

import io
from datetime import date, time
from pathlib import Path

from django.conf import settings
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import Role
from apps.administration.models import (
    Company,
    Location,
    RosterPolicy,
    Shift,
    WorkCalendar,
)
from apps.core.services.demo_erp import constants, guards, mapping, ownership
from apps.core.services.demo_erp.planner import build_plan
from apps.core.services.demo_erp.workbook import load_workbook
from apps.core.testing.tenant import ReusableTenantTestCase
from apps.hr.models import Employee, OrganizationAssignment


SOURCE = str(Path(settings.BASE_DIR) / constants.DEFAULT_SOURCE)
SCHEMA = "fast_demo_erp_contract"

WRITE_SQL = ("INSERT", "UPDATE", "DELETE", "ALTER", "CREATE", "DROP", "TRUNCATE")


#: `override_settings` di tingkat kelas tidak berlaku di sini:
#: `setUpClass` django-tenants tidak memanggil kait Django yang
#: memasangnya. Dipasang per pemanggilan perintah.
ALLOWED = [SCHEMA, "ghost_tenant"]


class DemoErpContractTests(ReusableTenantTestCase):
    reusable_schema_name = SCHEMA

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "demo-erp-contract"
        tenant.name = "Demo ERP Contract"

    @classmethod
    def build_baseline(cls):
        cls.workbook = load_workbook(SOURCE)

        # --- Dunia yang sudah ada: MNI/MMR/MLS + pemeran + TRL ----------
        cls.protected = {}

        for code in constants.PROTECTED_COMPANY_CODES:
            cls.protected[code], _ = Company.objects.get_or_create(
                code=code, is_deleted=False, defaults={"name": f"Protected {code}"},
            )

        cls.mmr_site, _ = Location.objects.get_or_create(
            company=cls.protected["MMR"], code="SAGEA-MINE", is_deleted=False,
            defaults={"name": "Sagea Mine"},
        )

        cls.cast = {}

        for number in ("HO001", "SGA005", "LOK002", "BOD001", "TRL01"):
            employee, _ = Employee.objects.get_or_create(
                employee_number=number, is_deleted=False,
                defaults={"first_name": f"Cast {number}"},
            )
            OrganizationAssignment.objects.get_or_create(
                employee=employee,
                defaults={
                    "company": cls.protected["MMR"],
                    "location": cls.mmr_site,
                    "organization_effective_date": date(2026, 1, 1),
                },
            )
            cls.cast[number] = employee

        # --- Master kanonik yang dipetakan (bukan dibuat) dataset ini ---
        for code in ("EMPLOYEE", "HR-MANAGER", "HR-ADMIN", "FINANCE-MANAGER", "EXECUTIVE"):
            Role.objects.get_or_create(code=code, is_deleted=False, defaults={"name": code})

        for code, work, off in (
            ("ROSTER-SAGEA-MINE-6-2-2-SHIFT", 42, 14),
            ("ROSTER-SAGEA MINE-8-2", 56, 14),
        ):
            RosterPolicy.objects.get_or_create(
                code=code, is_deleted=False,
                defaults={
                    "name": code,
                    "company": cls.protected["MMR"],
                    "location": cls.mmr_site,
                    "cycle_work_days": work,
                    "cycle_off_days": off,
                },
            )

        WorkCalendar.objects.get_or_create(
            code="OFFICE-2026", is_deleted=False, company=None,
            defaults={"name": "Office Calendar 2026"},
        )
        Shift.objects.get_or_create(
            code="OFFICE-10", is_deleted=False,
            defaults={"name": "Office", "start_time": time(10), "end_time": time(18)},
        )

    # ------------------------------------------------------------------

    def plan(self, *, reset=False):
        return build_plan(self.workbook, tenant=SCHEMA, reset=reset)

    def run_command(self, *args):
        out = io.StringIO()

        try:
            with self.settings(DEMO_ERP_ALLOWED_TENANTS=ALLOWED):
                call_command("seed_demo_erp", *args, stdout=out)
        except CommandError as exc:
            return out.getvalue(), exc

        return out.getvalue(), None

    # ------------------------------------------------------------------
    # Pagar tenant
    # ------------------------------------------------------------------

    def test_unknown_tenant_is_refused(self):
        _, error = self.run_command("--tenant=ghost_tenant", f"--source={SOURCE}", "--dry-run")

        self.assertIsNotNone(error)
        self.assertIn("tidak ditemukan", str(error))

    def test_missing_source_is_refused(self):
        _, error = self.run_command(f"--tenant={SCHEMA}", "--dry-run")

        self.assertIn("--source wajib", str(error))

    def test_dry_run_reports_and_leaves_everything_intact(self):
        before = guards.protected_snapshot()
        output, error = self.run_command(f"--tenant={SCHEMA}", f"--source={SOURCE}", "--dry-run")
        after = guards.protected_snapshot()

        self.assertIn("Rencana sha256", output)
        self.assertEqual(guards.diff_snapshots(before, after), [])
        # Tenant uji ini sengaja tidak punya seluruh master → blocker,
        # dan blocker berarti perintah keluar dengan galat.
        if error is not None:
            self.assertIn("blocker", str(error))

    # ------------------------------------------------------------------
    # Nol tulisan
    # ------------------------------------------------------------------

    def test_planner_issues_no_write_statement(self):
        with CaptureQueriesContext(connection) as queries:
            self.plan(reset=True)

        writes = [
            q["sql"] for q in queries.captured_queries
            if q["sql"].lstrip().upper().startswith(WRITE_SQL)
        ]
        self.assertEqual(writes, [])

    def test_protected_fingerprints_unchanged(self):
        before = guards.protected_snapshot()
        self.plan(reset=True)
        after = guards.protected_snapshot()

        for key in (
            "rbac.role", "rbac.role_permission", "rbac.permission",
            "workflow.definition", "workflow.step", "workflow.step_fallback",
            "finance.account", "finance.account_mapping", "finance.policy",
            "finance.policy_rule", "finance.policy_line", "finance.fiscal_year",
            "finance.accounting_period", "finance.dimension",
            "org.company.protected", "org.location.protected",
            "cast.employee", "cast.organization",
            "schedule.roster_policy", "ref.employee_group",
        ):
            with self.subTest(key):
                self.assertEqual(before[key], after[key])

    def test_repeated_dry_run_is_deterministic(self):
        self.assertEqual(self.plan().digest(), self.plan().digest())
        self.assertEqual(self.plan(reset=True).digest(), self.plan(reset=True).digest())

    # ------------------------------------------------------------------
    # MNI/MMR/MLS, pemeran HR-DEMO, TRL
    # ------------------------------------------------------------------

    def test_protected_company_cannot_be_targeted(self):
        import dataclasses

        hijacked = dataclasses.replace(
            self.workbook,
            companies=[
                dataclasses.replace(row, code="MMR") if row.code == "MMN" else row
                for row in self.workbook.companies
            ],
        )
        plan = build_plan(hijacked, tenant=SCHEMA, reset=True)

        self.assertTrue(any("company terlindung MMR" in b for b in plan.blockers))

    def test_protected_companies_are_never_owned(self):
        for code, company in self.protected.items():
            with self.subTest(code):
                self.assertFalse(ownership.is_owned_company(company))

        # Bahkan dengan surel penanda yang dipalsukan, kodenya tidak ikut.
        company = self.protected["MMR"]
        company.email = mapping.company_email("MMR")
        self.assertFalse(ownership.is_owned_company(company))

    def test_hr_demo_cast_and_trl_cannot_be_reset(self):
        report = ownership.inspect()
        scope = ownership.owned_querysets(
            company_ids=[], employee_ids=report.owned_employee_ids,
        )

        for number, employee in self.cast.items():
            with self.subTest(number):
                self.assertFalse(ownership.is_owned_employee(employee))
                self.assertNotIn(employee.pk, report.owned_employee_ids)
                self.assertFalse(scope["hr.employee"].filter(pk=employee.pk).exists())

    def test_marker_alone_does_not_make_a_cast_member_owned(self):
        employee = self.cast["HO001"]
        employee.notes = "[DEMO-ERP:HO001] disalin"

        self.assertFalse(ownership.is_owned_employee(employee))

    # ------------------------------------------------------------------
    # Baris asing & riwayat Finance
    # ------------------------------------------------------------------

    def test_foreign_company_with_dataset_code_blocks(self):
        Company.objects.create(code="MMN", name="Someone else's MMN")

        plan = self.plan(reset=True)

        self.assertTrue(
            any("Company MMN sudah ada tanpa penanda" in b for b in plan.blockers)
        )

    def test_foreign_employee_with_dataset_number_blocks(self):
        employee = Employee.objects.create(employee_number="EMP005", first_name="Stranger")
        OrganizationAssignment.objects.create(
            employee=employee,
            company=self.protected["MMR"],
            organization_effective_date=date(2026, 1, 1),
        )

        plan = self.plan(reset=True)

        self.assertTrue(any("Pegawai EMP005" in b for b in plan.blockers))

    def test_owned_rows_are_recognised(self):
        company = Company.objects.create(
            code="MMN", name="Meinova Mining", email=mapping.company_email("MMN"),
        )
        employee = Employee.objects.create(
            employee_number="EMP009",
            first_name="Markus",
            notes=mapping.employee_note(self.workbook.employee("EMP009")),
        )
        OrganizationAssignment.objects.create(
            employee=employee, company=company,
            organization_effective_date=date(2026, 8, 1),
        )

        report = ownership.inspect()

        self.assertEqual(report.owned_companies, ["MMN"])
        self.assertEqual(report.owned_employee_ids, [employee.pk])
        self.assertEqual(report.foreign, [])
        self.assertEqual(report.owned_counts["hr.employee"], 1)

    def test_posted_demo_journal_blocks_reset(self):
        from apps.administration.models import Currency
        from apps.finance.models import Journal
        from apps.finance.models.choices import JournalStatus
        from apps.finance.services import FiscalYearService, JournalService

        # Finance menolak jurnal tanpa mata uang dasar.
        if not Currency.objects.filter(is_base_currency=True, is_deleted=False).exists():
            Currency.objects.create(
                code="IDR", name="Rupiah", symbol="Rp", decimal_places=2,
                is_base_currency=True,
            )

        company = Company.objects.create(
            code="GRP", name="Meinova Group", email=mapping.company_email("GRP"),
        )
        fiscal_year = FiscalYearService.create(
            data={
                "company": company, "code": "FY-DEMO-ERP", "name": "FY 2026",
                "start_date": date(2026, 1, 1), "end_date": date(2026, 12, 31),
                "status": "open",
            },
        )
        FiscalYearService.generate_periods(fiscal_year=fiscal_year, count=12)
        journal = JournalService.create(
            data={
                "company": company,
                "posting_date": date(2026, 8, 31),
                "description": "payroll projection",
            },
        )

        self.assertEqual(ownership.posted_history(), [])
        self.assertFalse(any("Reset ditolak" in b for b in self.plan(reset=True).blockers))

        # Keadaan uji: jurnal milik dataset yang sudah POSTED.
        Journal.objects.filter(pk=journal.pk).update(status=JournalStatus.POSTED)

        with_reset = self.plan(reset=True)
        without_reset = self.plan(reset=False)

        self.assertTrue(any("Reset ditolak" in b for b in with_reset.blockers))
        self.assertFalse(any("Reset ditolak" in b for b in without_reset.blockers))
        self.assertTrue(any("--reset akan menolak" in w for w in without_reset.warnings))

    def test_posted_journal_of_other_company_is_not_ours(self):
        """Jurnal POSTED MMR tidak menghalangi reset dataset ini — bukan miliknya."""
        self.assertEqual(ownership.posted_history(company_codes=constants.OWNED_COMPANY_CODES), [])

    # ------------------------------------------------------------------
    # Pembongkar baseline (DEMO-1C)
    # ------------------------------------------------------------------

    def owned_world(self):
        """Company MMN + EMP009 milik dataset, dengan satu presensi baseline."""
        from apps.hr.models import EmployeeAttendance

        company = Company.objects.create(
            code="MMN", name="Meinova Mining", email=mapping.company_email("MMN"),
        )
        employee = Employee.objects.create(
            employee_number="EMP009", first_name="Markus",
            notes=mapping.employee_note(self.workbook.employee("EMP009")),
        )
        OrganizationAssignment.objects.create(
            employee=employee, company=company, organization_effective_date=date(2026, 8, 1),
        )
        owned = EmployeeAttendance.objects.create(
            employee=employee, company=company, work_date=date(2026, 8, 3),
            external_id=f"{constants.ATTENDANCE_EXTERNAL_PREFIX}EMP009-20260803",
        )
        cast = EmployeeAttendance.objects.create(
            employee=self.cast["HO001"], company=self.protected["MMR"], work_date=date(2026, 8, 3),
            external_id="SEED-ATT-HO001-20260803",
        )

        return company, employee, owned, cast

    def test_reset_removes_only_owned_baseline_rows(self):
        from apps.core.services.demo_erp import reset
        from apps.hr.models import EmployeeAttendance

        _, employee, owned, cast = self.owned_world()
        before = guards.protected_snapshot()

        self.assertEqual(reset.preflight(), [])
        counts = reset.execute(log=lambda *_: None)

        self.assertEqual(counts["hr.attendance"], 1)
        self.assertFalse(EmployeeAttendance.objects.filter(pk=owned.pk).exists())
        self.assertTrue(EmployeeAttendance.objects.filter(pk=cast.pk).exists())
        # Master baseline tidak ikut dibongkar.
        self.assertTrue(Employee.objects.filter(pk=employee.pk).exists())
        self.assertEqual(guards.diff_snapshots(before, guards.protected_snapshot()), [])

    def make_rejected_punch_evidence(self, employee, company):
        """Log tap Self Service yang ditolak + bukti verifikasinya (final)."""
        from apps.hr.models import AttendanceLog, AttendanceLogVerification

        log = AttendanceLog.objects.create(
            employee=employee,
            company=company,
            occurred_at="2026-08-03T01:00:00Z",
            log_type="in",
            source="mobile",
            external_id=f"self-punch:{employee.employee_number}",
        )
        return AttendanceLogVerification.objects.create(
            log=log,
            decision="rejected",
            reason_code="face_mismatch",
            face_result="fail",
        )

    def test_reset_purges_rejected_punch_evidence(self):
        """ATT-BIO-1B: bukti ber-PROTECT tidak lagi menjatuhkan reset."""
        from apps.core.services.demo_erp import reset
        from apps.hr.models import AttendanceLog, AttendanceLogVerification

        company, employee, _, _ = self.owned_world()
        self.make_rejected_punch_evidence(employee, company)
        kept = self.make_rejected_punch_evidence(self.cast["HO001"], self.protected["MMR"])

        self.assertEqual(reset.preflight(), [])
        counts = reset.execute(log=lambda *_: None)

        self.assertEqual(counts["hr.attendance_log_verification"], 1)
        self.assertEqual(counts["hr.attendance_log"], 1)
        self.assertFalse(AttendanceLog.objects.filter(employee=employee).exists())
        self.assertTrue(AttendanceLogVerification.objects.filter(pk=kept.pk).exists())

    def test_reset_refuses_foreign_row_of_owned_employee(self):
        from apps.core.services.demo_erp import reset
        from apps.hr.models import EmployeeAttendance

        company, employee, owned, _ = self.owned_world()
        EmployeeAttendance.objects.create(
            employee=employee, company=company, work_date=date(2026, 8, 4), external_id="MANUAL-1",
        )

        with self.assertRaises(reset.ResetRefused):
            reset.execute(log=lambda *_: None)

        self.assertTrue(EmployeeAttendance.objects.filter(pk=owned.pk).exists())

    def test_reset_refuses_any_finance_history_of_the_dataset(self):
        from apps.administration.models import Currency
        from apps.core.services.demo_erp import reset
        from apps.finance.services import FiscalYearService, JournalService
        from apps.hr.models import EmployeeAttendance

        company, _, owned, _ = self.owned_world()

        if not Currency.objects.filter(is_base_currency=True, is_deleted=False).exists():
            Currency.objects.create(
                code="IDR", name="Rupiah", symbol="Rp", decimal_places=2, is_base_currency=True,
            )

        fiscal_year = FiscalYearService.create(data={
            "company": company, "code": "FY-RESET", "name": "FY 2026",
            "start_date": date(2026, 1, 1), "end_date": date(2026, 12, 31), "status": "open",
        })
        FiscalYearService.generate_periods(fiscal_year=fiscal_year, count=12)
        JournalService.create(data={
            "company": company, "posting_date": date(2026, 8, 31), "description": "draft",
        })

        problems = reset.preflight()

        self.assertTrue(any("Journal" in p for p in problems))

        with self.assertRaises(reset.ResetRefused):
            reset.execute(log=lambda *_: None)

        self.assertTrue(EmployeeAttendance.objects.filter(pk=owned.pk).exists())

    def test_reset_never_scopes_cast_or_protected_companies(self):
        from apps.core.services.demo_erp import reset

        employees, companies = reset._scope()

        self.assertFalse({e.employee_number for e in employees} & set(self.cast))
        self.assertFalse({c.code for c in companies} & set(constants.PROTECTED_COMPANY_CODES))

    # ------------------------------------------------------------------
    # Role, locality, roster, payroll
    # ------------------------------------------------------------------

    def test_positions_do_not_create_roles(self):
        roles_before = guards.fingerprint(Role.objects.all())
        plan = self.plan()

        self.assertEqual(guards.fingerprint(Role.objects.all()), roles_before)

        existing = set(Role.objects.values_list("code", flat=True))

        for row in plan.sections["access"]:
            for grant in row["grants"]:
                with self.subTest(row["employee_number"], role=grant["role"]):
                    self.assertIn(grant["role"], existing)

        self.assertFalse(any("Role " in b and "tidak ada" in b for b in plan.blockers))

    def test_locality_is_reference_only(self):
        from apps.administration.models import EmployeeGroup

        groups_before = guards.fingerprint(EmployeeGroup.objects.all())
        plan = self.plan()

        self.assertEqual(guards.fingerprint(EmployeeGroup.objects.all()), groups_before)

        for row in plan.sections["employees"]:
            with self.subTest(row["employee_number"]):
                self.assertIn("rujukan saja", row["locality"])
                self.assertNotIn(row["employee_group"], {"EXPAT", "LOCAL"})

    def test_roster_mapping_reads_canonical_semantics_from_the_seed_source(self):
        """DEMO-1F: policy roster milik MMN dari sumber, bukan policy MMR di tenant."""
        plan = self.plan()
        rows = {row["workbook_code"]: row for row in plan.sections["schedule.mapping"]}

        self.assertEqual(rows["RST-6-2"]["cycle"], "42/14")
        self.assertEqual(rows["RST-8-2"]["cycle"], "56/14")
        self.assertTrue(rows["RST-6-2"]["policy_owner"].startswith("MMN/SAGEA-MINE"))
        self.assertFalse(any("tidak ada di sumber" in b for b in plan.blockers))

    def test_payroll_plan_copies_no_workbook_result(self):
        plan = self.plan()
        result_words = ("gross", "net", "overtime_amount", "allowance_amount", "deduction_amount")

        for row in plan.sections["payroll.assignment"]:
            with self.subTest(row["employee_number"]):
                self.assertFalse(any(word in key for key in row for word in result_words))

        for row in plan.sections["payroll.reference"]:
            self.assertEqual(row["use"], "pembanding saja")

        salaries = {
            row["employee_number"]: row["basic_salary"]
            for row in plan.sections["payroll.assignment"]
        }
        self.assertEqual(int(salaries["EMP009"]), 6500000)

    def test_contract_alert_is_derived_not_stored(self):
        plan = self.plan()
        rows = {row["employee_number"]: row for row in plan.sections["contracts"]}

        self.assertEqual(rows["EMP008"]["erp_report_bucket"], "expired")
        self.assertEqual(rows["EMP014"]["days_at_reference"], 0)
        self.assertEqual(rows["EMP037"]["erp_report_bucket"], "expiring_60")
        self.assertNotIn("alert", {k for row in plan.sections["employees"] for k in row})

    def test_logical_digest_covers_every_seed_write(self):
        """DEMO-1D/1E: akun + surel, saldo cuti, periode payroll, identitas & data pribadi ikut disidik."""
        from apps.core.services.demo_erp.verify import logical_digest

        first = logical_digest()

        self.assertEqual(
            set(first) - {"overall"},
            {
                "org.company", "org.location", "org.department", "org.position", "org.cost_center",
                "finance.account", "finance.mapping", "finance.policy", "finance.period",
                "access", "account.user", "employee", "leave.balance",
                "employee.identity", "employee.family", "employee.bank", "employee.education",
                "payroll.period", "payroll.assignment", "payroll.statutory",
                "roster.policy_config", "roster.rotation", "roster.period", "roster.shift",
                "attendance", "leave", "permission", "overtime", "workflow",
                "payroll.run", "payroll.line", "payroll.component",
            },
        )
        self.assertEqual(first, logical_digest())

    # ------------------------------------------------------------------
    # DEMO-1E: identitas lewat service kanonik
    # ------------------------------------------------------------------

    def identity_masters(self, employee_id):
        """Master rujukan satu baris tabel identitas — tenant test kosong."""
        from apps.administration.models import (
            Bank,
            BloodType,
            City,
            Country,
            Currency,
            District,
            Education,
            FamilyRelationship,
            Gender,
            MaritalStatus,
            Nationality,
            Province,
            Religion,
            Village,
        )
        from apps.core.services.demo_erp import identity

        i = identity.BY_EMPLOYEE[employee_id]

        def simple(model, code, **extra):
            model.objects.get_or_create(code=code, is_deleted=False, defaults={"name": code, **extra})

        for code in {i.gender} | {r.gender for r in i.relatives}:
            simple(Gender, code)
        simple(Religion, i.religion)
        simple(Nationality, identity.NATIONALITY)
        simple(BloodType, i.blood_type)
        simple(MaritalStatus, i.marital_status)
        for code in {r.relationship for r in i.relatives}:
            simple(FamilyRelationship, code)
        simple(Education, i.education.level)
        simple(Bank, i.bank, short_name=i.bank, swift_code=f"{i.bank}IDJA")
        if not Currency.objects.filter(code="IDR", is_deleted=False).exists():
            Currency.objects.create(code="IDR", name="Rupiah", symbol="Rp", decimal_places=2, is_base_currency=True)

        country, _ = Country.objects.get_or_create(
            code="ID", is_deleted=False,
            defaults={"name": "Indonesia", "phone_code": "+62", "currency_code": "IDR"},
        )
        province, _ = Province.objects.get_or_create(
            code=i.province, is_deleted=False, defaults={"name": i.province, "country": country},
        )
        city, _ = City.objects.get_or_create(
            code=i.city, is_deleted=False, defaults={"name": i.city, "province": province},
        )
        district, _ = District.objects.get_or_create(
            code=i.district, is_deleted=False, defaults={"name": i.district, "city": city},
        )
        Village.objects.get_or_create(
            code=i.village, is_deleted=False, defaults={"name": i.village, "district": district},
        )

    def identity_world(self):
        """EMP009 milik dataset + master rujukannya + PayrollAssignment berjalan."""
        from types import SimpleNamespace

        from apps.administration.models import Currency
        from apps.core.services.demo_erp.planner import planned_people
        from apps.hr.models import PayrollAssignment
        from apps.payroll.models import PayrollGroup

        company, employee, _, _ = self.owned_world()
        self.identity_masters("EMP009")
        group, _ = PayrollGroup.objects.get_or_create(code="MONTHLY", is_deleted=False, defaults={"name": "Monthly"})
        PayrollAssignment.objects.create(
            employee=employee, payroll_group=group, effective_from=date(2026, 6, 1),
            currency=Currency.objects.get(code="IDR", is_deleted=False),
            payment_method="bank_transfer", is_current=True,
        )
        ctx = SimpleNamespace(
            people={"EMP009": planned_people(self.workbook)["EMP009"]},
            employees={"EMP009": employee},
        )

        return ctx, employee

    def identity_state(self, employee):
        from apps.hr.models import EmployeeBankAccount, EmployeeEducation, EmployeeFamily, PayrollAssignment

        employee.refresh_from_db()
        a = PayrollAssignment.objects.get(employee=employee, is_current=True)

        return (
            employee.nik, employee.tax_number, employee.gender.code, employee.religion.code,
            employee.nationality.code, employee.marital_status.code, employee.blood_type.code,
            employee.birth_place, employee.birth_date, employee.address, employee.village.code,
            employee.district.code, employee.city.code, employee.province.code,
            employee.personal_email, employee.work_email, employee.mobile, employee.phone,
            employee.emergency_contact_name, employee.emergency_contact_phone,
            sorted(EmployeeFamily.objects.filter(employee=employee).values_list(
                "relationship__code", "full_name", "is_emergency_contact")),
            sorted(EmployeeBankAccount.objects.filter(employee=employee).values_list("bank__code", "account_number")),
            sorted(EmployeeEducation.objects.filter(employee=employee).values_list("education__code", "institution_name")),
            (a.tax_number_payroll, a.bpjs_kesehatan_number, a.bpjs_ketenagakerjaan_number),
            a.tax_status_id,
        )

    def test_identity_phase_resolves_masters_and_is_idempotent(self):
        from apps.core.services.demo_erp import apply, identity

        ctx, employee = self.identity_world()
        first = apply._identity(ctx)

        self.assertEqual(first["employees_updated"], 1)
        self.assertEqual((first["family_created"], first["bank_created"], first["education_created"]), (1, 1, 1))

        state = self.identity_state(employee)
        expected = identity.BY_EMPLOYEE["EMP009"]
        self.assertEqual(state[0], expected.nik)
        self.assertEqual(state[2:7], ("M", "PROTESTANT", "ID", "S", "A"))
        self.assertEqual(state[10], "82.02.07.2004")
        self.assertIsNone(state[-1])  # status pajak tidak disentuh

        second = apply._identity(ctx)
        self.assertEqual(set(second.values()), {0})
        self.assertEqual(self.identity_state(employee), state)

    def test_identity_is_rebuilt_from_source_after_wipe(self):
        from apps.core.services.demo_erp import apply
        from apps.hr.models import EmployeeBankAccount, EmployeeEducation, EmployeeFamily

        ctx, employee = self.identity_world()
        apply._identity(ctx)
        state = self.identity_state(employee)

        for model in (EmployeeFamily, EmployeeBankAccount, EmployeeEducation):
            model.objects.filter(employee=employee).delete()
        type(employee).objects.filter(pk=employee.pk).update(
            nik="", tax_number="", gender=None, religion=None, village=None, district=None,
            city=None, province=None, mobile="", personal_email="",
        )
        ctx.employees["EMP009"] = type(employee).objects.get(pk=employee.pk)

        apply._identity(ctx)
        self.assertEqual(self.identity_state(employee), state)

    def test_foreign_personal_row_blocks_identity_phase(self):
        from apps.administration.models import Bank
        from apps.core.services.demo_erp import apply
        from apps.hr.models import EmployeeBankAccount

        ctx, employee = self.identity_world()
        EmployeeBankAccount.objects.create(
            employee=employee, bank=Bank.objects.get(code="BRI", is_deleted=False),
            account_name="MANUAL", account_number="123", notes="dimasukkan tangan",
        )

        with self.assertRaises(apply.ApplyError):
            apply._identity(ctx)

    def test_missing_identity_master_is_reported_not_invented(self):
        plan = self.plan()

        self.assertTrue(any(b.startswith("Identitas: master Village") for b in plan.blockers))
        self.assertFalse(any("tidak ada di tabel identitas" in b for b in plan.blockers))

    # ------------------------------------------------------------------
    # DEMO-1D: mesin pembuangan (legacy_cleanup / reset penuh)
    # ------------------------------------------------------------------

    def test_legacy_target_refuses_unlisted_numbers(self):
        from apps.core.services.demo_erp import legacy_cleanup

        Employee.objects.create(employee_number="HO999", first_name="Stray")
        scope = legacy_cleanup.build_scope(legacy_cleanup.LEGACY_HR_DEMO)

        self.assertTrue(any(p.startswith("CAKUPAN: HO999") for p in legacy_cleanup.preflight(scope)))
        with self.assertRaises(legacy_cleanup.LegacyCleanupRefused):
            legacy_cleanup.execute(log=lambda *_: None, target=legacy_cleanup.LEGACY_HR_DEMO)
        self.assertTrue(Employee.objects.filter(employee_number="HO001").exists())

    def test_legacy_target_purges_rejected_punch_evidence(self):
        """ATT-BIO-1B: pegawai cast yang punya bukti tap tetap bisa dibuang."""
        from apps.core.services.demo_erp import legacy_cleanup
        from apps.hr.models import AttendanceLog, AttendanceLogVerification

        _, employee, _, _ = self.owned_world()
        self.make_rejected_punch_evidence(self.cast["HO001"], self.protected["MMR"])
        kept = self.make_rejected_punch_evidence(employee, self.protected["MMR"])

        counts = legacy_cleanup.execute(log=lambda *_: None, target=legacy_cleanup.LEGACY_HR_DEMO)

        self.assertEqual(counts["hr.attendance_log_verification"], 1)
        self.assertFalse(Employee.objects.filter(employee_number="HO001").exists())
        self.assertFalse(
            AttendanceLog.objects.filter(external_id="self-punch:HO001").exists()
        )
        self.assertTrue(AttendanceLogVerification.objects.filter(pk=kept.pk).exists())

    def test_legacy_target_removes_only_listed_cast(self):
        from apps.core.services.demo_erp import legacy_cleanup

        _, employee, _, _ = self.owned_world()
        counts = legacy_cleanup.execute(log=lambda *_: None, target=legacy_cleanup.LEGACY_HR_DEMO)

        self.assertEqual(counts["hr.employee (+cascade)"] >= 4, True)
        for number in ("HO001", "SGA005", "LOK002", "BOD001"):
            self.assertFalse(Employee.objects.filter(employee_number=number).exists(), number)
        self.assertTrue(Employee.objects.filter(employee_number="TRL01").exists())
        self.assertTrue(Employee.objects.filter(pk=employee.pk).exists())

    def test_legacy_target_refuses_employee_in_dataset_company(self):
        from apps.core.services.demo_erp import legacy_cleanup

        company, _, _, _ = self.owned_world()
        OrganizationAssignment.objects.filter(employee=self.cast["HO001"]).update(company=company)
        scope = legacy_cleanup.build_scope(legacy_cleanup.LEGACY_HR_DEMO)

        self.assertTrue(any(p.startswith("PROVENANCE: HO001") for p in legacy_cleanup.preflight(scope)))

    def test_trial_target_is_listed_but_dataset_target_is_not(self):
        from apps.core.services.demo_erp import legacy_cleanup, reset

        self.assertEqual(set(legacy_cleanup.TARGETS), {"legacy-hr-demo", "trl"})
        self.assertNotIn(reset.dataset_target().key, legacy_cleanup.TARGETS)
        self.assertEqual(legacy_cleanup.TRIAL.numbers, tuple(f"TRL{n:02d}" for n in range(1, 7)))

    def test_full_reset_requires_dataset_ownership(self):
        from apps.core.services.demo_erp import legacy_cleanup, reset

        self.owned_world()
        foreign = Employee.objects.create(employee_number="EMP010", first_name="Foreign")
        OrganizationAssignment.objects.create(
            employee=foreign, company=self.protected["MMR"], organization_effective_date=date(2026, 1, 1),
        )
        scope = legacy_cleanup.build_scope(reset.dataset_target())

        self.assertTrue(any(p.startswith("PROVENANCE: EMP010") for p in legacy_cleanup.preflight(scope)))
        with self.assertRaises(legacy_cleanup.LegacyCleanupRefused):
            reset.execute_full(log=lambda *_: None)
        self.assertTrue(Employee.objects.filter(pk=foreign.pk).exists())

    def test_full_reset_removes_dataset_employee_and_keeps_protected(self):
        from apps.core.services.demo_erp import reset

        _, employee, _, cast = self.owned_world()
        before = guards.protected_snapshot()

        reset.execute_full(log=lambda *_: None)

        self.assertFalse(Employee.objects.filter(pk=employee.pk).exists())
        for number in self.cast:
            self.assertTrue(Employee.objects.filter(employee_number=number).exists(), number)
        self.assertEqual(guards.diff_snapshots(before, guards.protected_snapshot()), [])

    def test_purge_command_refuses_unknown_tenant(self):
        out = io.StringIO()

        with self.settings(DEMO_ERP_ALLOWED_TENANTS=ALLOWED):
            with self.assertRaises(CommandError):
                call_command("purge_legacy_hr_demo", "--tenant=public", "--dry-run", stdout=out)
            with self.assertRaises(CommandError):
                call_command("purge_legacy_hr_demo", f"--tenant={SCHEMA}", stdout=out)

    def test_login_email_held_by_another_account_blocks(self):
        from apps.accounts.models import User

        address = mapping.user_email(self.workbook.employee("EMP001"))
        User.objects.create_user(username="someone.else", email=address, password="x")

        plan = self.plan()

        self.assertIn(
            f"Alamat {address} sudah dipakai akun someone.else (bukan dataset).", plan.blockers,
        )

    # ------------------------------------------------------------------
    # DEMO-1F: himpunan company kanonik, roster MMN, pembuangan company lama
    # ------------------------------------------------------------------

    def test_non_canonical_company_blocks_the_seed(self):
        plan = self.plan()

        for code in constants.PROTECTED_COMPANY_CODES:
            self.assertTrue(any(b.startswith(f"Company non-kanonik {code} ") for b in plan.blockers), code)

    def test_canonical_employee_resolving_a_legacy_object_is_reported(self):
        from apps.core.services.demo_erp import verify
        from apps.hr.models import EmploymentAssignment

        _, employee, _, _ = self.owned_world()
        self.assertEqual(verify.legacy_references(), {})

        EmploymentAssignment.objects.create(
            employee=employee,
            roster_policy=RosterPolicy.objects.get(code="ROSTER-SAGEA MINE-8-2", company=self.protected["MMR"]),
        )

        self.assertEqual(verify.legacy_references(), {"employment.roster_policy": 1})

    def roster_masters(self):
        from apps.administration.models import City, Country, Province, RotationPurpose
        from apps.core.services.demo_erp import roster_policy as source

        for sequence, code, _ in source.ROTATION:
            Shift.objects.get_or_create(
                code=code, is_deleted=False,
                defaults={"name": code, "start_time": time(6 + 8 * (sequence - 1) % 24), "end_time": time(14)},
            )
        for code in source.URGENT_PURPOSES:
            RotationPurpose.objects.get_or_create(code=code, is_deleted=False, defaults={"name": code})
        country, _ = Country.objects.get_or_create(
            code="ID", is_deleted=False, defaults={"name": "Indonesia", "phone_code": "+62", "currency_code": "IDR"},
        )
        for city, province in source.reference_codes()["City"]:
            prov, _ = Province.objects.get_or_create(
                code=province, is_deleted=False, defaults={"name": province, "country": country},
            )
            City.objects.get_or_create(code=city, province=prov, is_deleted=False, defaults={"name": city})

        company = Company.objects.create(code="MMN", name="Meinova Mining", email=mapping.company_email("MMN"))
        Location.objects.create(company=company, code=source.LOCATION, name="Sagea Mine Site")

        return company

    def test_mmn_roster_policies_are_created_from_source_and_idempotent(self):
        from types import SimpleNamespace

        from apps.core.services.demo_erp import apply
        from apps.core.services.demo_erp import roster_policy as source

        company = self.roster_masters()
        ctx = SimpleNamespace(
            company=lambda code: Company.objects.get(code=code, is_deleted=False),
            org=lambda model, co, code: model.objects.get(company__code=co, code=code, is_deleted=False),
        )

        first = apply._roster_policies(ctx)
        self.assertEqual((first["policies_created"], first["rotations_written"], first["travel_days_written"]),
                         (2, 6, 8))
        second = apply._roster_policies(ctx)
        self.assertEqual(set(second.values()), {0})

        for spec in source.POLICIES:
            with self.subTest(spec.code):
                policy = source.policy(spec.code)
                self.assertEqual(policy.company, company)
                self.assertEqual(policy.location.code, "SAGEA-MINE")
                for key, value in spec.fields().items():
                    self.assertEqual(getattr(policy, key), value, key)
                self.assertEqual(
                    list(policy.shift_rotations.order_by("sequence").values_list("sequence", "shift__code", "block_days")),
                    [(a, b, c) for a, b, c in source.ROTATION],
                )
                self.assertEqual(set(policy.urgent_purposes.values_list("code", flat=True)), set(source.URGENT_PURPOSES))
                self.assertEqual(
                    sorted(policy.travel_days.values_list(
                        "point_of_hire__code", "point_of_hire__province__code", "travel_out_days", "travel_in_days")),
                    sorted((c, p, o, i) for (c, p), o, i in spec.travel_days),
                )

        # Policy MMR yang namanya sama tidak tersentuh.
        self.assertTrue(RosterPolicy.objects.filter(company=self.protected["MMR"], code="ROSTER-SAGEA MINE-8-2").exists())

    def legacy_cleanup_world(self):
        """Keadaan yang boleh dibuang: pemeran dibuang, GRP/MMN/MIN ada, 3 alur lama."""
        from apps.workflow.models import WorkflowDefinition

        Employee.objects.filter(pk__in=[e.pk for e in self.cast.values()]).delete()
        canonical = {
            code: Company.objects.create(code=code, name=f"Canonical {code}", email=mapping.company_email(code))
            for code in constants.OWNED_COMPANY_CODES
        }
        for code in ("HR-TR-SITE", "HR-LEAVE-SITE", "HR-HO-LEAVE"):
            WorkflowDefinition.objects.create(
                code=code, name=code, module="hr", document_type=code.lower(), location=self.mmr_site,
            )

        return canonical

    def test_legacy_company_cleanup_refuses_while_legacy_employees_exist(self):
        from apps.core.services.demo_erp import legacy_company_cleanup as cleanup

        problems = cleanup.preflight(cleanup.build_scope())

        self.assertTrue(any("pegawai di company lama" in p for p in problems))
        self.assertTrue(any(p.startswith("COMPANY: himpunan") for p in problems))
        with self.assertRaises(cleanup.LegacyCompanyCleanupRefused):
            cleanup.execute(log=lambda *_: None)
        self.assertEqual(Company.objects.filter(code__in=cleanup.LEGACY_COMPANY_CODES).count(), 3)

    def test_legacy_company_cleanup_refuses_canonical_dependency(self):
        from apps.core.services.demo_erp import legacy_company_cleanup as cleanup
        from apps.hr.models import EmploymentAssignment

        self.legacy_cleanup_world()
        employee = Employee.objects.create(employee_number="EMP009", first_name="Markus")
        EmploymentAssignment.objects.create(
            employee=employee,
            roster_policy=RosterPolicy.objects.get(code="ROSTER-SAGEA MINE-8-2", company=self.protected["MMR"]),
        )

        problems = cleanup.preflight(cleanup.build_scope())
        self.assertTrue(any(p.startswith("KANONIK: 1 kepegawaian EMP") for p in problems))

    def test_legacy_company_cleanup_refuses_unaudited_reference(self):
        from apps.administration.models import Department
        from apps.core.services.demo_erp import legacy_company_cleanup as cleanup

        canonical = self.legacy_cleanup_world()
        Department.objects.create(company=canonical["MMN"], code="X", name="X", location=self.mmr_site)

        problems = cleanup.preflight(cleanup.build_scope())
        self.assertTrue(any(p.startswith("DEPENDENSI: administration.Department.location") for p in problems))

    def test_legacy_company_cleanup_refuses_finance_transactions(self):
        from apps.administration.models import Currency
        from apps.core.services.demo_erp import legacy_company_cleanup as cleanup
        from apps.finance.services import FiscalYearService, JournalService

        self.legacy_cleanup_world()
        if not Currency.objects.filter(is_base_currency=True, is_deleted=False).exists():
            Currency.objects.create(code="IDR", name="Rupiah", symbol="Rp", decimal_places=2, is_base_currency=True)
        year = FiscalYearService.create(data={
            "company": self.protected["MMR"], "code": "FY-MMR", "name": "FY 2026",
            "start_date": date(2026, 1, 1), "end_date": date(2026, 12, 31), "status": "open",
        })
        FiscalYearService.generate_periods(fiscal_year=year, count=12)
        JournalService.create(data={
            "company": self.protected["MMR"], "posting_date": date(2026, 8, 31), "description": "legacy",
        })

        problems = cleanup.preflight(cleanup.build_scope())
        self.assertIn("TRANSAKSI/DEPENDENSI: Journal tenant = 1.", problems)
        with self.assertRaises(cleanup.LegacyCompanyCleanupRefused):
            cleanup.execute(log=lambda *_: None)

    def test_legacy_company_cleanup_keeps_shared_and_canonical_configuration(self):
        from apps.administration.models import Holiday
        from apps.core.services.demo_erp import legacy_company_cleanup as cleanup
        from apps.finance.models import Account

        canonical = self.legacy_cleanup_world()
        global_holiday = Holiday.objects.create(date=date(2026, 8, 17), code="HUT-RI", name="HUT RI", scope="GLOBAL")
        legacy_holiday = Holiday.objects.create(
            date=date(2026, 9, 4), code="SAGEA", name="Sagea", scope="LOCATION",
            company=self.protected["MMR"], location=self.mmr_site,
        )
        legacy_calendar = WorkCalendar.objects.create(
            code="LOCATION-3-2026", name="Sagea", scope="LOCATION",
            company=self.protected["MMR"], location=self.mmr_site,
        )
        canonical_account = Account.objects.create(
            company=canonical["GRP"], code="1000", name="Kas", account_type="asset",
        )
        legacy_account = Account.objects.create(
            company=self.protected["MNI"], code="1000", name="Kas", account_type="asset",
        )

        deleted = cleanup.execute(log=lambda *_: None)

        self.assertEqual(deleted["administration.Company"], 3)
        self.assertEqual(cleanup.remaining_legacy(), {"administration.Company": 0})
        self.assertEqual(sorted(Company.objects.values_list("code", flat=True)), ["GRP", "MIN", "MMN"])
        # Bersama & kanonik tetap.
        self.assertTrue(Holiday.objects.filter(pk=global_holiday.pk).exists())
        self.assertTrue(WorkCalendar.objects.filter(code="OFFICE-2026", company__isnull=True).exists())
        self.assertTrue(Shift.objects.filter(code="OFFICE-10").exists())
        self.assertTrue(Account.objects.filter(pk=canonical_account.pk).exists())
        # Milik company lama hilang.
        self.assertFalse(Holiday.objects.filter(pk=legacy_holiday.pk).exists())
        self.assertFalse(WorkCalendar.objects.filter(pk=legacy_calendar.pk).exists())
        self.assertFalse(Account.objects.filter(pk=legacy_account.pk).exists())
        self.assertFalse(RosterPolicy.objects.filter(code__startswith="ROSTER-SAGEA").exists())

    def test_purge_legacy_companies_command_refuses_bad_mode_and_tenant(self):
        out = io.StringIO()

        with self.settings(DEMO_ERP_ALLOWED_TENANTS=ALLOWED):
            with self.assertRaises(CommandError):
                call_command("purge_legacy_companies", "--tenant=public", "--dry-run", stdout=out)
            with self.assertRaises(CommandError):
                call_command("purge_legacy_companies", f"--tenant={SCHEMA}", stdout=out)
