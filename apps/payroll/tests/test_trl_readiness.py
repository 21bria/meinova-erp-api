"""
TRL-0B — kesiapan dataset trial, dibuktikan lewat jalur produksi.

Yang diuji di sini **bukan** payroll secara umum; itu sudah dipegang
berkas-berkas tetangga. Yang diuji: apakah enam skenario TRL-0
menghasilkan angka yang persis seperti yang dirancang, ketika dihitung
oleh `PayrollRunService` yang sama dengan yang akan dipakai tenant
demo — bukan oleh kalkulator terpisah yang kebetulan sependapat.

Karena itu panggungnya menyalin **konfigurasi demo apa adanya**, bukan
konfigurasi yang paling nyaman untuk lulus: lima baris Deduction
Template lengkap dengan plafon 12 juta pada BPJS Kesehatan, dua
Allowance Template, lima lapis pajak, dan `PayrollSetting` fixed_30.
Angka yang lulus di panggung yang disederhanakan tidak membuktikan apa
pun tentang demo.

Tenant demo tidak disentuh sama sekali; seluruh berkas ini hidup di
schema test.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django_tenants.test.cases import TenantTestCase

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
    OvertimeGroupTier,
    OvertimeTierBasis,
    PayrollBasis,
    PayrollDailyRateMethod,
    PayrollGroup,
    PayrollLeaveRule,
    PayrollPayBasis,
    PayrollPeriod,
    PayrollPolicy,
    PayrollProrationMethod,
    PayrollRunEmployee,
    PayrollSetting,
    PayrollTaxBracket,
    TaxStatus,
)
from apps.payroll.services import PayrollRunService


PERIOD_START = date(2026, 9, 1)
PERIOD_END = date(2026, 9, 30)

# Hari kerja September 2026 menurut kalender Senin–Jumat, tanpa libur.
WORKDAYS = (
    1, 2, 3, 4, 7, 8, 9, 10, 11, 14, 15, 16, 17, 18,
    21, 22, 23, 24, 25, 28, 29, 30,
)


def d(day: int) -> date:
    return date(2026, 9, day)


class TrlReadinessTestCase(TenantTestCase):
    """Panggung yang menyalin konfigurasi master demo company MMR."""

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "trl-readiness"
        tenant.name = "TRL Readiness"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        seed_numbering()

        cls.currency = Currency.objects.create(
            code="IDR", name="Rupiah", symbol="Rp", is_base_currency=True,
        )

        cls.company = Company.objects.create(code="MMR", name="Mineral")
        cls.branch = Branch.objects.create(
            company=cls.company, code="DEFAULT", name="Main Branch",
        )
        cls.location = Location.objects.create(
            company=cls.company, branch=cls.branch,
            code="JKT-HO", name="Jakarta Head Office",
        )
        cls.department = Department.objects.create(
            company=cls.company, code="PROC", name="Procurement",
        )
        cls.section = Section.objects.create(
            company=cls.company, department=cls.department,
            code="PROC_GENERAL", name="General",
        )

        # Kalender Senin–Jumat, persis `OFFICE-2026` di demo.
        cls.calendar = WorkCalendar.objects.create(
            code="OFFICE-2026", name="Office Calendar 2026",
            monday=True, tuesday=True, wednesday=True,
            thursday=True, friday=True, saturday=False, sunday=False,
            is_default=True,
        )

        cls.shift = Shift.objects.create(
            code="OFFICE-10", name="Office",
            start_time="10:00", end_time="18:00",
        )

        # --- Payroll master, disalin dari demo -----------------------
        cls.group_monthly = PayrollGroup.objects.create(
            code="MONTHLY", name="Monthly Payroll",
        )
        cls.group_daily = PayrollGroup.objects.create(
            code="DAILY", name="Daily Payroll",
        )

        cls.tax_status = TaxStatus.objects.create(
            code="TK/0", name="Tidak Kawin 0",
            non_taxable_income=Decimal("54000000"),
        )

        for sequence, low, high, rate in (
            (1, "0", "60000000", "5"),
            (2, "60000000", "250000000", "15"),
            (3, "250000000", "500000000", "25"),
            (4, "500000000", "5000000000", "30"),
            (5, "5000000000", None, "35"),
        ):
            PayrollTaxBracket.objects.create(
                sequence=sequence,
                income_from=Decimal(low),
                income_to=Decimal(high) if high else None,
                rate=Decimal(rate),
            )

        # Allowance template 1 — STANDARD.
        cls.allowance_standard = AllowanceTemplate.objects.create(
            code="STANDARD", name="Standard Employee",
        )
        for code, name, seq, amount in (
            ("TRANSPORT", "Tunjangan Transport", 10, "25000"),
            ("MEAL", "Tunjangan Makan", 20, "30000"),
        ):
            AllowanceTemplateLine.objects.create(
                template=cls.allowance_standard,
                code=code, name=name, sequence=seq,
                basis=PayrollBasis.PER_ATTENDANCE_DAY,
                amount=Decimal(amount),
                is_taxable=True, is_prorated=False,
            )

        # Allowance template 2 — STAFF. Satu baris per hari yang TIDAK
        # boleh diprorata, satu baris persentase yang HARUS diprorata.
        cls.allowance_staff = AllowanceTemplate.objects.create(
            code="STAFF", name="Staff",
        )
        AllowanceTemplateLine.objects.create(
            template=cls.allowance_staff,
            code="TRANSPORT", name="Tunjangan Transport", sequence=10,
            basis=PayrollBasis.PER_ATTENDANCE_DAY,
            amount=Decimal("35000"),
            is_taxable=True, is_prorated=False,
        )
        AllowanceTemplateLine.objects.create(
            template=cls.allowance_staff,
            code="POSITION", name="Tunjangan Jabatan", sequence=20,
            basis=PayrollBasis.PERCENT_OF_BASIC,
            rate=Decimal("10"),
            is_taxable=True, is_prorated=True,
        )

        # Deduction template 1 — lima baris, termasuk plafon 12 juta.
        cls.deduction_standard = DeductionTemplate.objects.create(
            code="STANDARD", name="Standard Employee",
        )
        DeductionTemplateLine.objects.create(
            template=cls.deduction_standard,
            code="BPJS-KES", name="BPJS Kesehatan (Pegawai 1%)",
            sequence=10, basis=PayrollBasis.PERCENT_OF_BASIC,
            rate=Decimal("1"), maximum_base=Decimal("12000000"),
            reduces_taxable=True, is_employer_cost=False,
        )
        DeductionTemplateLine.objects.create(
            template=cls.deduction_standard,
            code="BPJS-JHT", name="BPJS JHT (Pegawai 2%)",
            sequence=20, basis=PayrollBasis.PERCENT_OF_BASIC,
            rate=Decimal("2"),
            reduces_taxable=True, is_employer_cost=False,
        )
        DeductionTemplateLine.objects.create(
            template=cls.deduction_standard,
            code="BPJS-JHT-ER", name="BPJS JHT (Perusahaan 3,7%)",
            sequence=30, basis=PayrollBasis.PERCENT_OF_BASIC,
            rate=Decimal("3.7"),
            reduces_taxable=False, is_employer_cost=True,
        )
        DeductionTemplateLine.objects.create(
            template=cls.deduction_standard,
            code="BPJS-KES-ER", name="BPJS Kesehatan (Perusahaan 4%)",
            sequence=40, basis=PayrollBasis.PERCENT_OF_BASIC,
            rate=Decimal("4"), maximum_base=Decimal("12000000"),
            reduces_taxable=False, is_employer_cost=True,
        )
        DeductionTemplateLine.objects.create(
            template=cls.deduction_standard,
            code="PPH21", name="PPh 21",
            sequence=90, basis=PayrollBasis.PPH21_PROGRESSIVE,
            reduces_taxable=False, is_employer_cost=False,
        )

        # --- Default perusahaan, persis PayrollSetting demo ----------
        PayrollSetting.objects.create(
            company=cls.company,
            proration_method=PayrollProrationMethod.FIXED_30,
            prorate_on_join=True,
            prorate_on_termination=True,
            attendance_deduction_method=PayrollProrationMethod.FIXED_30,
            deduct_absence=True,
            deduct_unpaid_leave=True,
            is_active=True,
        )

        # --- Tiga master milik trial ---------------------------------
        cls.leave_annual = LeaveType.objects.create(
            code="ANNUAL", name="Cuti Tahunan",
        )
        cls.leave_unpaid = LeaveType.objects.create(
            code="UNPAID", name="Cuti Tanpa Upah",
        )

        # Satu baris saja. Jenis cuti tanpa baris = cuti dibayar.
        cls.leave_rule_unpaid = PayrollLeaveRule.objects.create(
            leave_type=cls.leave_unpaid, is_unpaid=True,
        )

        cls.overtime_group = OvertimeGroup.objects.create(
            code="TRL-OT-TIER", name="Trial Tiered Overtime",
            hourly_multiplier=Decimal("1.00"),
            hourly_divisor=Decimal("173"),
            tier_basis=OvertimeTierBasis.DAILY,
        )
        OvertimeGroupTier.objects.create(
            group=cls.overtime_group, sequence=1,
            hour_from=Decimal("0"), hour_to=Decimal("2"),
            multiplier=Decimal("1.5"),
        )
        OvertimeGroupTier.objects.create(
            group=cls.overtime_group, sequence=2,
            hour_from=Decimal("2"), hour_to=None,
            multiplier=Decimal("2.0"),
        )

        cls.policy_daily = PayrollPolicy.objects.create(
            company=cls.company,
            code="TRL-DAILY", name="Trial Daily",
            pay_basis=PayrollPayBasis.DAILY,
            daily_rate_method=PayrollDailyRateMethod.FROM_MONTHLY,
            daily_rate_divisor=Decimal("26"),
            pay_paid_leave="yes",
            is_active=True,
        )

        from apps.finance.seeds import (
            seed_chart_of_accounts,
            seed_payroll_policy,
        )

        seed_chart_of_accounts(company=cls.company)
        seed_payroll_policy(company=cls.company)

        cls._ensure_finance_calendar()
        cls._build_population()
        cls._run_payroll()

    # ------------------------------------------------------------------
    # Panggung
    # ------------------------------------------------------------------

    @classmethod
    def _ensure_finance_calendar(cls):
        from apps.finance.services import FiscalYearService

        fiscal_year = FiscalYearService.create(
            data={
                "company": cls.company,
                "code": "FY2026-MMR",
                "name": "Fiscal Year 2026",
                "start_date": date(2026, 1, 1),
                "end_date": date(2026, 12, 31),
                "status": "open",
            },
        )
        FiscalYearService.generate_periods(fiscal_year=fiscal_year, count=12)

    @classmethod
    def _employee(
        cls, tag, *, basic, group, join_date,
        allowance, overtime_group=None, policy=None,
    ):
        employee = Employee.objects.create(
            employee_number=tag, first_name="Trial", last_name=tag,
        )

        OrganizationAssignment.objects.create(
            employee=employee,
            company=cls.company,
            branch=cls.branch,
            location=cls.location,
            department=cls.department,
            section=cls.section,
            organization_effective_date=join_date,
        )

        EmploymentAssignment.objects.create(
            employee=employee,
            join_date=join_date,
            working_calendar=cls.calendar,
            shift=cls.shift,
        )

        PayrollAssignment.objects.create(
            employee=employee,
            payroll_group=group,
            currency=cls.currency,
            tax_status=cls.tax_status,
            overtime_eligible=overtime_group is not None,
            overtime_group=overtime_group,
            basic_salary=Decimal(basic),
            allowance_template=allowance,
            deduction_template=cls.deduction_standard,
            payroll_policy=policy,
            effective_from=join_date,
        )

        return Employee.objects.get(pk=employee.pk)

    @classmethod
    def _attend(cls, employee, days, status=AttendanceStatus.PRESENT, **extra):
        for day in days:
            EmployeeAttendance.objects.create(
                employee=employee,
                company=cls.company,
                branch=cls.branch,
                location=cls.location,
                work_date=d(day),
                shift=cls.shift,
                status=status,
                **extra,
            )

    _leave_seq = 0

    @classmethod
    def _leave(cls, employee, *, leave_type, start, end, days):
        cls._leave_seq += 1

        EmployeeLeave.objects.create(
            employee=employee,
            leave_type=leave_type,
            document_number=f"LV-TRL-{cls._leave_seq:04d}",
            start_date=d(start),
            end_date=d(end),
            total_days=Decimal(days),
            status=LeaveStatus.RECORDED,
        )

    @classmethod
    def _overtime(cls, employee, day, hours):
        EmployeeOvertime.objects.create(
            employee=employee,
            company=cls.company,
            work_date=d(day),
            # Jam mulai/selesai wajib terisi; lembur sesudah shift
            # kantor yang berakhir pukul 18:00.
            start_time="18:00",
            end_time=cls._end_time(hours),
            duration_minutes=int(Decimal(hours) * 60),
            status=OvertimeStatus.RECORDED,
            is_paid=True,
        )

    @staticmethod
    def _end_time(hours):
        minutes = 18 * 60 + int(Decimal(hours) * 60)

        return f"{(minutes // 60) % 24:02d}:{minutes % 60:02d}"

    @classmethod
    def _build_population(cls):
        full = date(2025, 1, 6)

        cls.trl01 = cls._employee(
            "TRL01", basic="10000000", group=cls.group_monthly,
            join_date=full, allowance=cls.allowance_standard,
        )
        cls.trl02 = cls._employee(
            "TRL02", basic="12000000", group=cls.group_monthly,
            join_date=d(16), allowance=cls.allowance_staff,
        )
        cls.trl03 = cls._employee(
            "TRL03", basic="9000000", group=cls.group_monthly,
            join_date=full, allowance=cls.allowance_standard,
            overtime_group=cls.overtime_group,
        )
        cls.trl04 = cls._employee(
            "TRL04", basic="8000000", group=cls.group_monthly,
            join_date=full, allowance=cls.allowance_standard,
        )
        cls.trl05 = cls._employee(
            "TRL05", basic="5200000", group=cls.group_daily,
            join_date=full, allowance=cls.allowance_standard,
            policy=cls.policy_daily,
        )
        cls.trl06 = cls._employee(
            "TRL06", basic="7500000", group=cls.group_monthly,
            join_date=full, allowance=cls.allowance_standard,
        )

        # TRL01 — 22 hadir, satu di antaranya telat 35 menit.
        cls._attend(cls.trl01, [x for x in WORKDAYS if x != 8])
        cls._attend(
            cls.trl01, [8],
            status=AttendanceStatus.LATE, late_minutes=35,
        )

        # TRL02 — hanya sejak tanggal masuk. Sebelum itu TIDAK ADA baris.
        cls._attend(cls.trl02, [x for x in WORKDAYS if x >= 16])

        # TRL03 — hadir penuh, lembur empat tanggal.
        cls._attend(cls.trl03, WORKDAYS)
        for day, hours in ((7, "2"), (9, "3"), (14, "1.5"), (21, "4")):
            cls._overtime(cls.trl03, day, hours)

        # TRL04 — cuti dibayar 8-9, cuti tidak dibayar 22-24.
        leave_days = {8, 9, 22, 23, 24}
        cls._attend(cls.trl04, [x for x in WORKDAYS if x not in leave_days])
        cls._attend(
            cls.trl04, sorted(leave_days), status=AttendanceStatus.LEAVE,
        )
        cls._leave(
            cls.trl04, leave_type=cls.leave_annual,
            start=8, end=9, days="2",
        )
        cls._leave(
            cls.trl04, leave_type=cls.leave_unpaid,
            start=22, end=24, days="3",
        )

        # TRL05 — harian, dua hari alpa.
        absent05 = {3, 4}
        cls._attend(cls.trl05, [x for x in WORKDAYS if x not in absent05])
        cls._attend(
            cls.trl05, sorted(absent05), status=AttendanceStatus.ABSENT,
        )

        # TRL06 — tiga hari alpa tanpa keterangan.
        absent06 = {10, 11, 25}
        cls._attend(cls.trl06, [x for x in WORKDAYS if x not in absent06])
        cls._attend(
            cls.trl06, sorted(absent06), status=AttendanceStatus.ABSENT,
        )

    @classmethod
    def _run_payroll(cls):
        cls.period_monthly = PayrollPeriod.objects.create(
            company=cls.company,
            payroll_group=cls.group_monthly,
            code="2026-09", name="September 2026",
            start_date=PERIOD_START, end_date=PERIOD_END,
            payment_date=date(2026, 10, 5),
        )
        cls.period_daily = PayrollPeriod.objects.create(
            company=cls.company,
            payroll_group=cls.group_daily,
            code="2026-09", name="September 2026",
            start_date=PERIOD_START, end_date=PERIOD_END,
            payment_date=date(2026, 10, 5),
        )

        cls.run_monthly = PayrollRunService.create(
            data={
                "period": cls.period_monthly,
                "run_type": "regular",
                "department": cls.department,
            },
        )
        cls.run_daily = PayrollRunService.create(
            data={
                "period": cls.period_daily,
                "run_type": "regular",
                "department": cls.department,
            },
        )

        for run in (cls.run_monthly, cls.run_daily):
            PayrollRunService.generate_employees(run=run)
            PayrollRunService.calculate(run=run)

        cls.run_monthly.refresh_from_db()
        cls.run_daily.refresh_from_db()

    # ------------------------------------------------------------------
    # Pembantu
    # ------------------------------------------------------------------

    def line(self, employee):
        return PayrollRunEmployee.objects.get(employee=employee)

    def amount(self, employee, code):
        line = self.line(employee)
        component = line.components.filter(code=code, is_deleted=False).first()

        return component.amount if component else None

    def money(self, value):
        return Decimal(value).quantize(Decimal("0.01"))


    def test_run_bulanan_memuat_lima_pegawai_dan_run_harian_satu(self):
        monthly = set(
            PayrollRunEmployee.objects
            .filter(run=self.run_monthly, is_deleted=False)
            .values_list("employee__employee_number", flat=True)
        )
        daily = set(
            PayrollRunEmployee.objects
            .filter(run=self.run_daily, is_deleted=False)
            .values_list("employee__employee_number", flat=True)
        )

        self.assertEqual(
            monthly, {"TRL01", "TRL02", "TRL03", "TRL04", "TRL06"},
        )
        self.assertEqual(daily, {"TRL05"})


    EXPECTED_NET = {
        "TRL01": "10448500.00",
        "TRL02": "6518750.00",
        "TRL03": "10386789.01",
        "TRL04": "7725250.00",
        "TRL05": "4921800.00",
        "TRL06": "7416500.00",
    }

    def test_net_pay_keenam_skenario(self):
        for tag, expected in self.EXPECTED_NET.items():
            with self.subTest(tag=tag):
                line = PayrollRunEmployee.objects.get(
                    employee__employee_number=tag,
                )

                self.assertEqual(line.net_pay, self.money(expected))


    def test_trl01_baseline(self):
        self.assertEqual(self.amount(self.trl01, "BASIC"), self.money("10000000"))
        self.assertEqual(self.amount(self.trl01, "TRANSPORT"), self.money("550000"))
        self.assertEqual(self.amount(self.trl01, "MEAL"), self.money("660000"))
        self.assertEqual(self.amount(self.trl01, "BPJS-KES"), self.money("100000"))
        self.assertEqual(self.amount(self.trl01, "BPJS-JHT"), self.money("200000"))
        self.assertEqual(self.amount(self.trl01, "PPH21"), self.money("461500"))

        line = self.line(self.trl01)
        self.assertEqual(line.gross_earning, self.money("11210000"))
        self.assertEqual(line.total_deduction, self.money("761500"))
        self.assertEqual(line.attendance_days, Decimal("22.00"))

    def test_trl01_telat_35_menit_tidak_mengubah_uang(self):
        """
        Telat tercatat, tapi tanpa `PayrollPermissionRule` ia tidak
        punya akibat uang — dan `LATE` tetap dihitung hari hadir.
        """
        line = self.line(self.trl01)

        self.assertEqual(line.attendance_days, Decimal("22.00"))
        self.assertEqual(line.absent_days, Decimal("0.00"))
        self.assertEqual(line.net_pay, self.money("10448500"))

        # Tidak ada satu pun komponen yang lahir dari keterlambatan.
        codes = set(
            line.components.filter(is_deleted=False).values_list(
                "code", flat=True,
            ),
        )
        self.assertNotIn("LATE", codes)

    def test_trl02_prorata_join(self):
        line = self.line(self.trl02)

        self.assertEqual(line.proration_factor, Decimal("0.500000"))
        self.assertEqual(line.working_days, Decimal("15.00"))
        self.assertEqual(line.proration_base_days, Decimal("30.00"))

        # Pokok diprorata.
        self.assertEqual(self.amount(self.trl02, "BASIC"), self.money("6000000"))

        # Basis per hari TIDAK diprorata: 35.000 x 11 hari.
        self.assertEqual(self.amount(self.trl02, "TRANSPORT"), self.money("385000"))

        # Basis persentase DIPRORATA: 10% x 12jt = 1,2jt, lalu x 15/30.
        self.assertEqual(self.amount(self.trl02, "POSITION"), self.money("600000"))

    def test_trl02_sebelum_bergabung_bukan_alpa(self):
        line = self.line(self.trl02)

        self.assertEqual(line.absent_days, Decimal("0.00"))
        self.assertEqual(line.attendance_days, Decimal("11.00"))
        self.assertIsNone(self.amount(self.trl02, "ABSENT"))

    def test_trl02_bpjs_memakai_gaji_konfigurasi_penuh(self):
        """
        CURRENT CONFIGURATION BEHAVIOR — baris template bertanda
        `is_prorated=False`, jadi dasarnya gaji yang tertulis di
        assignment, bukan yang sudah diprorata.
        """
        self.assertEqual(self.amount(self.trl02, "BPJS-KES"), self.money("120000"))
        self.assertEqual(self.amount(self.trl02, "BPJS-JHT"), self.money("240000"))

        line = self.line(self.trl02)
        self.assertEqual(
            line.employer_contribution, self.money("924000"),
        )

    def test_trl03_lembur_bertingkat(self):
        line = self.line(self.trl03)

        self.assertEqual(line.overtime_hours, Decimal("10.50"))

        # 9.000.000 / 173 x 17,25 jam berbobot.
        self.assertEqual(
            self.amount(self.trl03, "OT"), self.money("897398.84"),
        )

    def test_trl03_jam_berbobot_tepat_17_25(self):
        """
        Dibuktikan dari angkanya sendiri, bukan dari niat: jumlah yang
        dibayar dibagi tarif per jam harus menghasilkan 17,25.
        """
        amount = self.amount(self.trl03, "OT")
        hourly = Decimal("9000000") / Decimal("173")

        self.assertEqual(
            (amount / hourly).quantize(Decimal("0.01")), Decimal("17.25"),
        )

    def test_trl04_hanya_cuti_tidak_dibayar_yang_memotong(self):
        line = self.line(self.trl04)

        self.assertEqual(line.leave_days, Decimal("5.00"))
        self.assertEqual(line.unpaid_leave_days, Decimal("3.00"))
        self.assertEqual(line.absent_days, Decimal("0.00"))

        # 8.000.000 x 3 / 30.
        self.assertEqual(
            self.amount(self.trl04, "UNPAID-LEAVE"), self.money("800000"),
        )

        # Cuti dibayar tidak menerbitkan pengurang apa pun.
        self.assertIsNone(self.amount(self.trl04, "ABSENT"))

    def test_trl04_cuti_dibayar_tidak_menghasilkan_tunjangan_harian(self):
        """
        Dua hari cuti dibayar bukan hari hadir: tunjangan per hari
        berhenti di 17 hari, bukan 19.
        """
        line = self.line(self.trl04)

        self.assertEqual(line.attendance_days, Decimal("17.00"))
        self.assertEqual(self.amount(self.trl04, "TRANSPORT"), self.money("425000"))
        self.assertEqual(self.amount(self.trl04, "MEAL"), self.money("510000"))

    def test_trl05_harian_tanpa_pengurang_ketidakhadiran(self):
        line = self.line(self.trl05)

        self.assertEqual(line.attendance_days, Decimal("20.00"))
        self.assertEqual(line.absent_days, Decimal("2.00"))

        # 5.200.000 / 26 = 200.000 sehari x 20 hari.
        self.assertEqual(self.amount(self.trl05, "BASIC"), self.money("4000000"))

        # Tidak ada baris pengurang sama sekali — bukan baris bernilai nol.
        self.assertIsNone(self.amount(self.trl05, "ABSENT"))
        self.assertIsNone(self.amount(self.trl05, "UNPAID-LEAVE"))

        self.assertEqual(line.proration_factor, Decimal("1.000000"))

    def test_trl06_pengurang_alpa_tepat_dan_tidak_dihitung_dua_kali(self):
        line = self.line(self.trl06)

        self.assertEqual(line.absent_days, Decimal("3.00"))

        # 7.500.000 x 3 / 30.
        self.assertEqual(
            self.amount(self.trl06, "ABSENT"), self.money("750000"),
        )

        # Sudah keluar dari gross; TIDAK boleh ikut lagi di potongan.
        self.assertEqual(line.gross_earning, self.money("7795000"))
        self.assertEqual(line.total_deduction, self.money("378500"))
        self.assertEqual(
            line.net_pay,
            line.gross_earning - line.total_deduction,
        )


    def test_total_run_bulanan(self):
        lines = PayrollRunEmployee.objects.filter(
            run=self.run_monthly, is_deleted=False,
        )

        self.assertEqual(
            sum(line.net_pay for line in lines), self.money("42495789.01"),
        )
        self.assertEqual(
            sum(line.gross_earning for line in lines),
            self.money("45232398.84"),
        )
        self.assertEqual(
            sum(line.employer_contribution for line in lines),
            self.money("3580500"),
        )

    def test_total_run_harian(self):
        lines = PayrollRunEmployee.objects.filter(
            run=self.run_daily, is_deleted=False,
        )

        self.assertEqual(
            sum(line.net_pay for line in lines), self.money("4921800"),
        )
        self.assertEqual(
            sum(line.gross_earning for line in lines), self.money("5100000"),
        )


    def test_hanya_satu_baris_aturan_cuti_yang_dibutuhkan(self):
        """
        ANNUAL tidak punya baris dan tetap terbaca dibayar — "baris yang
        tidak ada = cuti dibayar", persis yang ditulis model.
        """
        self.assertFalse(
            PayrollLeaveRule.objects.filter(
                leave_type=self.leave_annual, is_deleted=False,
            ).exists(),
        )

        line = self.line(self.trl04)

        self.assertEqual(line.leave_days, Decimal("5.00"))
        self.assertEqual(line.unpaid_leave_days, Decimal("3.00"))


    def payload_for(self, run):
        from apps.payroll.services.accounting import PayrollAccountingService

        return PayrollAccountingService.build_payload(run=run)

    def drafts_for(self, run):
        from apps.finance.services.policy import AccountingPolicyService

        payload = self.payload_for(run)

        policy = AccountingPolicyService.resolve(
            event_type="PAYROLL_POSTED",
            company_id=self.company.pk,
            on_date=run.period.end_date,
        )

        return payload, AccountingPolicyService.build_lines(
            policy=policy,
            payload=payload,
            company_id=self.company.pk,
            on_date=run.period.end_date,
        )

    @staticmethod
    def sides(drafts):
        debit = sum(
            (line.amount for line in drafts if line.side == "debit"),
            Decimal("0"),
        )
        credit = sum(
            (line.amount for line in drafts if line.side == "credit"),
            Decimal("0"),
        )

        return debit, credit

    @staticmethod
    def by_account(drafts):
        from apps.finance.models import Account

        codes = dict(
            Account.objects.filter(
                pk__in={line.account_id for line in drafts},
            ).values_list("pk", "code"),
        )

        totals: dict[str, Decimal] = {}

        for line in drafts:
            code = codes[line.account_id]
            signed = line.amount if line.side == "debit" else -line.amount
            totals[code] = totals.get(code, Decimal("0")) + signed

        return totals

    def test_payload_bulanan_seimbang(self):
        payload = self.payload_for(self.run_monthly)

        self.assertEqual(
            Decimal(payload["control"]["total_debit"]), self.money("50362898.84"),
        )
        self.assertEqual(
            Decimal(payload["control"]["total_credit"]), self.money("50362898.84"),
        )

    def test_payload_harian_seimbang(self):
        payload = self.payload_for(self.run_daily)

        self.assertEqual(
            Decimal(payload["control"]["total_debit"]), self.money("5500400.00"),
        )
        self.assertEqual(
            Decimal(payload["control"]["total_credit"]), self.money("5500400.00"),
        )

    def test_jurnal_bulanan_seimbang_dan_terpetakan(self):
        _, drafts = self.drafts_for(self.run_monthly)

        debit, credit = self.sides(drafts)

        self.assertEqual(debit, self.money("50362898.84"))
        self.assertEqual(credit, self.money("50362898.84"))

        by_account = self.by_account(drafts)

        # Gaji 40.500.000 + lembur 897.398,84 - pengurang 1.550.000.
        self.assertEqual(by_account["6100"], self.money("39847398.84"))
        self.assertEqual(by_account["6110"], self.money("5385000"))
        self.assertEqual(by_account["6120"], self.money("3580500"))
        self.assertEqual(by_account["2140"], self.money("-1341609.83"))
        self.assertEqual(by_account["2130"], self.money("-42495789.01"))

        # 1.395.000 potongan pegawai + 3.580.500 utang iuran perusahaan.
        self.assertEqual(by_account["2160"], self.money("-4975500"))

        # Social Security Payable tidak tersentuh: jalur BPJS bawaan
        # tidak aktif pada konfigurasi ini.
        self.assertNotIn("2150", by_account)

    def test_jurnal_harian_seimbang_dan_terpetakan(self):
        _, drafts = self.drafts_for(self.run_daily)

        debit, credit = self.sides(drafts)

        self.assertEqual(debit, self.money("5500400.00"))
        self.assertEqual(credit, self.money("5500400.00"))

        by_account = self.by_account(drafts)

        self.assertEqual(by_account["6100"], self.money("4000000"))
        self.assertEqual(by_account["6110"], self.money("1100000"))
        self.assertEqual(by_account["6120"], self.money("400400"))
        self.assertEqual(by_account["2140"], self.money("-22200"))
        self.assertEqual(by_account["2130"], self.money("-4921800"))
        self.assertNotIn("2150", by_account)

