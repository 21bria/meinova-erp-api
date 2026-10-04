"""
Payroll ujung ke ujung, di atas Payroll Master yang sudah ada.

Skenario bertahap seperti yang diminta: satu company, satu periode,
empat pegawai, gaji pokok dari master existing, satu tunjangan, satu
potongan, satu input lembur — lalu Calculate → Review → Finalize →
Payslip.

`TenantTestCase` django-tenants **tidak** memanggil
`super().setUpClass()`, jadi tidak ada rollback per-test dan
`setUpTestData` tidak pernah jalan. Konsekuensinya tiap test memakai
run-nya sendiri dan hanya membaca miliknya.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django_tenants.test.cases import TenantTestCase

from apps.administration.models import (
    Company,
    Currency,
    Department,
    LeaveType,
    Location,
)
from apps.administration.seeds.numbering import seed_numbering
from apps.hr.models import (
    Employee,
    EmployeeLeave,
    EmployeeOvertime,
    EmploymentAssignment,
    OrganizationAssignment,
    PayrollAssignment,
)
from apps.hr.models.attendance import AttendanceStatus, EmployeeAttendance
from apps.hr.models.leave import LeaveStatus
from apps.hr.models.overtime import OvertimeStatus
from apps.payroll.models import (
    AllowanceTemplate,
    AllowanceTemplateLine,
    DeductionTemplate,
    DeductionTemplateLine,
    OvertimeGroup,
    PayrollBasis,
    PayrollGroup,
    PayrollInput,
    PayrollInputStatus,
    PayrollInputType,
    PayrollLeaveRule,
    PayrollPeriod,
    PayrollPeriodStatus,
    PayrollRun,
    PayrollRunEmployee,
    PayrollRunEmployeeStatus,
    PayrollRunStatus,
    PayrollTaxBracket,
    Payslip,
    TaxStatus,
)
from apps.payroll.services import (
    PayrollInputService,
    PayrollRunService,
)


PERIOD_START = date(2026, 9, 1)
PERIOD_END = date(2026, 9, 30)


class PayrollFlowTestCase(TenantTestCase):
    """Satu company, master payroll existing, empat pegawai."""

    _counter = 0

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "payroll-flow"
        tenant.name = "Payroll Flow"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # Tenant test lahir kosong; tanpa deret ini `document_number`
        # terbit kosong — perilaku yang memang benar, tapi membuat test
        # nomor dokumen tidak menguji apa pun.
        seed_numbering()

        cls.company = Company.objects.create(code="PAY", name="Payroll Test")

        cls.location = Location.objects.create(
            company=cls.company, code="HO", name="Head Office",
        )

        cls.department = Department.objects.create(
            company=cls.company, code="OPS", name="Operations",
        )

        # `is_base_currency` bukan hiasan: sejak PF-0D, Finalize
        # membandingkan mata uang payroll dengan mata uang buku besar
        # yang dinyatakan master ini. Tenant sungguhan menandainya lewat
        # seed referensi; fixture harus menyatakannya juga, kalau tidak
        # setiap Finalize di sini gagal karena panggungnya, bukan karena
        # yang sedang diuji.
        cls.currency = Currency.objects.create(
            code="IDR", name="Rupiah", symbol="Rp", is_base_currency=True,
        )

        # --- Payroll Master existing, dipakai apa adanya --------------
        cls.payroll_group = PayrollGroup.objects.create(
            code="MONTHLY", name="Monthly Payroll",
        )

        cls.tax_status = TaxStatus.objects.create(
            code="TK/0",
            name="Tidak Kawin 0",
            non_taxable_income=Decimal("54000000"),
        )

        cls.overtime_group = OvertimeGroup.objects.create(
            code="STANDARD",
            name="Standard",
            hourly_multiplier=Decimal("1.5"),
            hourly_divisor=Decimal("173"),
        )

        cls.allowance_template = AllowanceTemplate.objects.create(
            code="STANDARD", name="Standard Employee",
        )

        cls.deduction_template = DeductionTemplate.objects.create(
            code="STANDARD", name="Standard Employee",
        )

        # --- Konfigurasi yang menempel di master existing -------------
        AllowanceTemplateLine.objects.create(
            template=cls.allowance_template,
            code="TRANSPORT",
            name="Tunjangan Transport",
            sequence=10,
            basis=PayrollBasis.PER_ATTENDANCE_DAY,
            amount=Decimal("25000"),
            is_taxable=True,
            is_prorated=False,
        )

        DeductionTemplateLine.objects.create(
            template=cls.deduction_template,
            code="BPJS-KES",
            name="BPJS Kesehatan",
            sequence=10,
            basis=PayrollBasis.PERCENT_OF_BASIC,
            rate=Decimal("1"),
            maximum_base=Decimal("12000000"),
            reduces_taxable=True,
        )

        for sequence, low, high, rate in (
            (1, "0", "60000000", "5"),
            (2, "60000000", "250000000", "15"),
        ):
            PayrollTaxBracket.objects.create(
                sequence=sequence,
                income_from=Decimal(low),
                income_to=Decimal(high),
                rate=Decimal(rate),
            )

        # --- Finance — sejak PF-0F, Finalize menerbitkan jurnal draf ---
        #
        # Alasannya sama dengan `is_base_currency` di atas: Finalize kini
        # menyerahkan payload-nya ke Finance dan **gagal** kalau jurnalnya
        # tidak bisa terbit. Tanpa bagan akun, kebijakan gaji, dan tahun
        # buku, setiap Finalize di sini gagal karena panggungnya, bukan
        # karena yang sedang diuji. Tahun bukunya dibuat per periode oleh
        # `ensure_finance_calendar()` — test payroll sengaja memakai tahun
        # yang berbeda-beda karena periode tidak boleh tumpang tindih.
        from apps.finance.seeds import (
            seed_chart_of_accounts,
            seed_payroll_policy,
        )

        seed_chart_of_accounts(company=cls.company)
        seed_payroll_policy(company=cls.company)

    @classmethod
    def ensure_finance_calendar(cls, on_date, *, company=None):
        """
        Tahun buku Januari–Desember yang memuat `on_date`, kalau belum ada.

        Dua belas periode bulanan, berstatus terbuka — kalender paling
        biasa. Test yang justru menguji kalender yang hilang atau tertutup
        membuat periode payroll-nya tanpa lewat sini.
        """
        from apps.finance.models import FiscalYear
        from apps.finance.services import FiscalYearService

        company = company or cls.company

        if FiscalYear.objects.filter(
            company=company,
            is_deleted=False,
            start_date__lte=on_date,
            end_date__gte=on_date,
        ).exists():
            return

        fiscal_year = FiscalYearService.create(
            data={
                "company": company,
                "code": f"FY{on_date.year}-{company.code}",
                "name": f"Fiscal Year {on_date.year}",
                "start_date": date(on_date.year, 1, 1),
                "end_date": date(on_date.year, 12, 31),
                "status": "open",
            },
        )

        FiscalYearService.generate_periods(fiscal_year=fiscal_year, count=12)

    # ------------------------------------------------------------------
    # Pabrik data
    # ------------------------------------------------------------------

    @classmethod
    def make_employee(
        cls,
        *,
        basic_salary="10000000",
        join_date=date(2025, 1, 1),
        termination_date=None,
        with_assignment=True,
        overtime_eligible=False,
    ):
        cls._counter += 1

        employee = Employee.objects.create(
            employee_number=f"PAY{cls._counter:04d}",
            first_name="Payroll",
            last_name=f"Employee {cls._counter}",
        )

        OrganizationAssignment.objects.create(
            employee=employee,
            company=cls.company,
            location=cls.location,
            department=cls.department,
            organization_effective_date=date(2025, 1, 1),
        )

        EmploymentAssignment.objects.create(
            employee=employee,
            join_date=join_date,
            termination_date=termination_date,
        )

        if with_assignment:
            PayrollAssignment.objects.create(
                employee=employee,
                payroll_group=cls.payroll_group,
                currency=cls.currency,
                tax_status=cls.tax_status,
                overtime_eligible=overtime_eligible,
                overtime_group=(
                    cls.overtime_group if overtime_eligible else None
                ),
                basic_salary=Decimal(basic_salary),
                allowance_template=cls.allowance_template,
                deduction_template=cls.deduction_template,
                effective_from=date(2025, 1, 1),
            )

        return Employee.objects.get(pk=employee.pk)

    @classmethod
    def make_period(cls, code=None):
        cls._counter += 1

        cls.ensure_finance_calendar(PERIOD_END)

        return PayrollPeriod.objects.create(
            company=cls.company,
            payroll_group=cls.payroll_group,
            code=code or f"2026-09-{cls._counter}",
            name="September 2026",
            start_date=PERIOD_START,
            end_date=PERIOD_END,
            payment_date=date(2026, 10, 5),
            working_days=30,
        )

    @classmethod
    def make_run(cls, period):
        return PayrollRunService.create(
            data={
                "period": period,
                "run_type": "regular",
            },
        )

    @staticmethod
    def make_attendance(employee, *, days, status=AttendanceStatus.PRESENT):
        for offset in range(days):
            EmployeeAttendance.objects.create(
                employee=employee,
                company=employee.organization.company,
                work_date=date(2026, 9, offset + 1),
                status=status,
            )

    @staticmethod
    def line_for(run, employee):
        return PayrollRunEmployee.objects.get(run=run, employee=employee)

    @staticmethod
    def component(line, code):
        return line.components.get(code=code)


class GenerateEmployeesTest(PayrollFlowTestCase):
    def test_pegawai_aktif_ditarik_ke_run(self):
        employee = self.make_employee()
        period = self.make_period()
        run = self.make_run(period)

        result = PayrollRunService.generate_employees(run=run)

        self.assertGreaterEqual(result["total"], 1)
        self.assertTrue(
            PayrollRunEmployee.objects
            .filter(run=run, employee=employee)
            .exists(),
        )

    def test_snapshot_organisasi_dan_gaji_ikut_tersalin(self):
        employee = self.make_employee(basic_salary="7500000")
        period = self.make_period()
        run = self.make_run(period)

        PayrollRunService.generate_employees(run=run)

        line = self.line_for(run, employee)

        self.assertEqual(line.basic_salary, Decimal("7500000.00"))
        self.assertEqual(line.department_id, self.department.pk)
        self.assertEqual(line.company_id, self.company.pk)
        self.assertEqual(line.tax_status_id, self.tax_status.pk)

    def test_pegawai_yang_berhenti_sebelum_periode_tidak_ikut(self):
        employee = self.make_employee(
            termination_date=date(2026, 8, 15),
        )
        period = self.make_period()
        run = self.make_run(period)

        PayrollRunService.generate_employees(run=run)

        self.assertFalse(
            PayrollRunEmployee.objects
            .filter(run=run, employee=employee)
            .exists(),
        )

    def test_pegawai_yang_baru_masuk_bulan_depan_tidak_ikut(self):
        employee = self.make_employee(join_date=date(2026, 10, 1))
        period = self.make_period()
        run = self.make_run(period)

        PayrollRunService.generate_employees(run=run)

        self.assertFalse(
            PayrollRunEmployee.objects
            .filter(run=run, employee=employee)
            .exists(),
        )

    def test_generate_ulang_tidak_menggandakan(self):
        self.make_employee()
        period = self.make_period()
        run = self.make_run(period)

        PayrollRunService.generate_employees(run=run)
        first = PayrollRunEmployee.objects.filter(run=run).count()

        PayrollRunService.generate_employees(run=run)
        second = PayrollRunEmployee.objects.filter(run=run).count()

        self.assertEqual(first, second)

    def test_run_membawa_nomor_dokumen(self):
        period = self.make_period()
        run = self.make_run(period)

        self.assertTrue(run.document_number.startswith("PAY-"))

    def test_periode_pindah_ke_processing_setelah_generate(self):
        self.make_employee()
        period = self.make_period()
        run = self.make_run(period)

        PayrollRunService.generate_employees(run=run)

        period.refresh_from_db()

        self.assertEqual(period.status, PayrollPeriodStatus.PROCESSING)


class CalculationFlowTest(PayrollFlowTestCase):
    def test_gaji_pokok_tunjangan_dan_potongan(self):
        employee = self.make_employee(basic_salary="10000000")
        self.make_attendance(employee, days=20)

        period = self.make_period()
        run = self.make_run(period)

        PayrollRunService.generate_employees(run=run)
        PayrollRunService.calculate(run=run)

        line = self.line_for(run, employee)

        self.assertEqual(line.status, PayrollRunEmployeeStatus.CALCULATED)
        self.assertEqual(
            self.component(line, "BASIC").amount, Decimal("10000000.00"),
        )
        # 20 hari hadir x Rp 25.000
        self.assertEqual(
            self.component(line, "TRANSPORT").amount, Decimal("500000.00"),
        )
        self.assertEqual(
            self.component(line, "BPJS-KES").amount, Decimal("100000.00"),
        )
        self.assertEqual(line.gross_earning, Decimal("10500000.00"))
        self.assertEqual(line.net_pay, Decimal("10400000.00"))

    def test_lembur_dari_modul_hr_masuk_sendiri(self):
        employee = self.make_employee(overtime_eligible=True)
        self.make_attendance(employee, days=20)

        EmployeeOvertime.objects.create(
            employee=employee,
            company=self.company,
            work_date=date(2026, 9, 10),
            start_time="18:00",
            end_time="20:00",
            duration_minutes=120,
            status=OvertimeStatus.APPROVED,
            is_paid=True,
        )

        period = self.make_period()
        run = self.make_run(period)

        PayrollRunService.generate_employees(run=run)
        PayrollRunService.calculate(run=run)

        line = self.line_for(run, employee)

        self.assertEqual(line.overtime_hours, Decimal("2.00"))
        self.assertEqual(
            self.component(line, "OT").amount, Decimal("173410.40"),
        )

    def test_cuti_tidak_dibayar_memotong_gaji(self):
        leave_type = LeaveType.objects.create(
            code=f"UNPAID{self._counter}", name="Cuti Tanpa Gaji",
        )

        PayrollLeaveRule.objects.create(
            leave_type=leave_type, is_unpaid=True,
        )

        employee = self.make_employee()

        EmployeeLeave.objects.create(
            employee=employee,
            company=self.company,
            leave_type=leave_type,
            start_date=date(2026, 9, 10),
            end_date=date(2026, 9, 12),
            total_days=Decimal("3"),
            status=LeaveStatus.APPROVED,
        )

        period = self.make_period()
        run = self.make_run(period)

        PayrollRunService.generate_employees(run=run)
        PayrollRunService.calculate(run=run)

        line = self.line_for(run, employee)

        self.assertEqual(line.unpaid_leave_days, Decimal("3.00"))
        self.assertEqual(
            self.component(line, "UNPAID-LEAVE").amount,
            Decimal("1000000.00"),
        )
        self.assertEqual(
            line.unpaid_leave_deduction, Decimal("1000000.00"),
        )

    def test_payroll_input_confirmed_ikut_dihitung(self):
        employee = self.make_employee()
        period = self.make_period()

        PayrollInputService.create(
            data={
                "period": period,
                "employee": employee,
                "input_type": PayrollInputType.INCENTIVE,
                "code": "BONUS",
                "name": "Bonus Kinerja",
                "amount": Decimal("2000000"),
                "status": PayrollInputStatus.CONFIRMED,
            },
        )

        run = self.make_run(period)

        PayrollRunService.generate_employees(run=run)
        PayrollRunService.calculate(run=run)

        line = self.line_for(run, employee)

        self.assertEqual(
            self.component(line, "BONUS").amount, Decimal("2000000.00"),
        )

    def test_payroll_input_draft_tidak_ikut(self):
        employee = self.make_employee()
        period = self.make_period()

        PayrollInputService.create(
            data={
                "period": period,
                "employee": employee,
                "input_type": PayrollInputType.INCENTIVE,
                "code": "BONUS-DRAFT",
                "name": "Bonus Belum Final",
                "amount": Decimal("2000000"),
                "status": PayrollInputStatus.DRAFT,
            },
        )

        run = self.make_run(period)

        PayrollRunService.generate_employees(run=run)
        PayrollRunService.calculate(run=run)

        line = self.line_for(run, employee)

        self.assertFalse(
            line.components.filter(code="BONUS-DRAFT").exists(),
        )

    def test_prorata_pegawai_masuk_pertengahan_bulan(self):
        employee = self.make_employee(join_date=date(2026, 9, 16))

        period = self.make_period()
        run = self.make_run(period)

        PayrollRunService.generate_employees(run=run)
        PayrollRunService.calculate(run=run)

        line = self.line_for(run, employee)

        # 15 dari 30 hari.
        self.assertEqual(line.proration_factor, Decimal("0.500000"))
        self.assertEqual(
            self.component(line, "BASIC").amount, Decimal("5000000.00"),
        )

    def test_total_run_sama_dengan_jumlah_barisnya(self):
        for _ in range(3):
            self.make_employee()

        period = self.make_period()
        run = self.make_run(period)

        PayrollRunService.generate_employees(run=run)
        PayrollRunService.calculate(run=run)

        run.refresh_from_db()

        total = sum(
            line.net_pay
            for line in PayrollRunEmployee.objects.filter(
                run=run, is_excluded=False,
            )
        )

        self.assertEqual(run.total_net, total)
        self.assertEqual(run.status, PayrollRunStatus.REVIEW)


class ValidationTest(PayrollFlowTestCase):
    def test_pegawai_tanpa_payroll_assignment_jadi_error(self):
        self.make_employee(with_assignment=False)

        period = self.make_period()
        run = self.make_run(period)

        PayrollRunService.generate_employees(run=run)
        result = PayrollRunService.calculate(run=run)

        codes = {
            item["code"] for item in result["validation"]["errors"]
        }

        self.assertIn("assignment_missing", codes)

    def test_finalize_ditolak_selama_ada_error(self):
        self.make_employee(with_assignment=False)

        period = self.make_period()
        run = self.make_run(period)

        PayrollRunService.generate_employees(run=run)
        PayrollRunService.calculate(run=run)

        run.status = PayrollRunStatus.APPROVED
        run.save(update_fields=["status"])

        with self.assertRaises(ValidationError):
            PayrollRunService.finalize(run=run)

    def test_peringatan_harus_diakui_sebelum_finalize(self):
        # Tanpa satu pun baris absensi → peringatan, bukan error.
        self.make_employee()

        period = self.make_period()
        run = self.make_run(period)

        PayrollRunService.generate_employees(run=run)
        summary = PayrollRunService.calculate(run=run)["validation"]

        self.assertFalse(summary["errors"])
        self.assertTrue(summary["warnings"])

        run.status = PayrollRunStatus.APPROVED
        run.save(update_fields=["status"])

        with self.assertRaises(ValidationError):
            PayrollRunService.finalize(run=run)

        PayrollRunService.acknowledge(run=run)

        run.refresh_from_db()
        run.status = PayrollRunStatus.APPROVED
        run.save(update_fields=["status"])

        result = PayrollRunService.finalize(run=run)

        self.assertGreaterEqual(result["payslips"], 1)


class FinalizeAndPayslipTest(PayrollFlowTestCase):
    def finalized_run(self, employee=None):
        employee = employee or self.make_employee()
        self.make_attendance(employee, days=20)

        period = self.make_period()
        run = self.make_run(period)

        PayrollRunService.generate_employees(run=run)
        PayrollRunService.calculate(run=run)
        PayrollRunService.acknowledge(run=run)

        run.refresh_from_db()
        run.status = PayrollRunStatus.APPROVED
        run.save(update_fields=["status"])

        PayrollRunService.finalize(run=run)

        run.refresh_from_db()

        return employee, period, run

    def test_finalize_mengunci_run_dan_periode(self):
        _, period, run = self.finalized_run()

        period.refresh_from_db()

        self.assertEqual(run.status, PayrollRunStatus.FINALIZED)
        self.assertTrue(run.is_locked)
        self.assertEqual(period.status, PayrollPeriodStatus.FINALIZED)
        self.assertTrue(period.is_locked)
        self.assertIsNotNone(period.locked_at)

    def test_payslip_terbit_dengan_nomor_dan_snapshot(self):
        employee, _, run = self.finalized_run()

        slip = Payslip.objects.get(run=run, employee=employee)

        self.assertTrue(slip.document_number.startswith("SLP-"))
        self.assertEqual(slip.net_pay, Decimal("10400000.00"))
        self.assertEqual(
            slip.snapshot["employee"]["employee_number"],
            employee.employee_number,
        )
        self.assertTrue(slip.snapshot["earnings"])
        self.assertTrue(slip.snapshot["deductions"])

    def test_perubahan_master_setelah_finalize_tidak_mengubah_payroll(self):
        """
        Inti Tahap 9: payroll periode lama tetap konsisten walau Salary
        Master berubah di periode berikutnya.
        """
        employee, _, run = self.finalized_run()

        slip = Payslip.objects.get(run=run, employee=employee)
        net_before = slip.net_pay

        line = AllowanceTemplateLine.objects.get(
            template=self.allowance_template, code="TRANSPORT",
        )
        line.amount = Decimal("999000")
        line.save(update_fields=["amount"])

        assignment = PayrollAssignment.objects.get(
            employee=employee, is_current=True,
        )
        assignment.basic_salary = Decimal("99000000")
        assignment.save(update_fields=["basic_salary"])

        slip.refresh_from_db()
        run_line = self.line_for(run, employee)

        self.assertEqual(slip.net_pay, net_before)
        self.assertEqual(run_line.basic_salary, Decimal("10000000.00"))
        self.assertEqual(
            slip.snapshot["totals"]["net_pay"], str(net_before),
        )

    def test_run_terkunci_tidak_bisa_dihitung_ulang(self):
        _, _, run = self.finalized_run()

        with self.assertRaises(ValidationError):
            PayrollRunService.calculate(run=run)

    def test_periode_terkunci_menolak_input_baru(self):
        employee, period, _ = self.finalized_run()

        period.refresh_from_db()

        with self.assertRaises(ValidationError):
            PayrollInputService.create(
                data={
                    "period": period,
                    "employee": employee,
                    "input_type": PayrollInputType.ADJUSTMENT,
                    "code": "LATE",
                    "name": "Koreksi Terlambat",
                    "amount": Decimal("100000"),
                },
            )

    def test_pegawai_yang_sudah_final_ditolak_di_run_lain(self):
        employee, period, _ = self.finalized_run()

        second = PayrollRun.objects.create(
            period=period,
            company=self.company,
            run_type="off_cycle",
            document_number="PAY-2026-99999",
        )

        PayrollRunEmployee.objects.create(
            run=second,
            employee=employee,
            basic_salary=Decimal("1000000"),
            status=PayrollRunEmployeeStatus.CALCULATED,
        )

        summary = PayrollRunService.validate(run=second)

        codes = {item["code"] for item in summary["errors"]}

        self.assertIn("duplicate_finalized", codes)
