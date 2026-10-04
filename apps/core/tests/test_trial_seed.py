"""
Penyemai dataset trial Fase 1.

Satu kelas, satu schema tenant, satu panggung master kanonik — dan
seluruh test di bawahnya membangun keadaannya sendiri dari situ.
`TenantTestCase` tidak merollback antar test, jadi urutan tidak boleh
menentukan hasil: tiap test yang menulis membersihkan jejaknya lewat
`_purge_trial()`.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import mock

from django.test import SimpleTestCase
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
    WorkSchedule,
)
from apps.core.services.trial_seed import (
    PERIOD_END,
    PERIOD_START,
    TrialSeedAborted,
    TrialSeedService,
)
from apps.core.services.trial_seed_demo import DEMO_TRIAL_SPEC
from apps.hr.models import (
    Employee,
    EmployeeLeave,
    EmployeeOvertime,
    EmploymentAssignment,
    LeaveBalance,
    LeaveGoLive,
    LeaveOpeningBalance,
    LeaveOpeningStatus,
    OrganizationAssignment,
    PayrollAssignment,
)
from apps.hr.models.attendance import EmployeeAttendance
from apps.hr.models.shift_assignment import EmployeeShiftAssignment
from apps.payroll.models import (
    AllowanceTemplate,
    AllowanceTemplateLine,
    DeductionTemplate,
    OvertimeGroup,
    OvertimeGroupTier,
    PayrollBasis,
    PayrollGroup,
    PayrollLeaveRule,
    PayrollPeriod,
    PayrollPolicy,
    PayrollRun,
    TaxStatus,
)


class TrialSeedTestCase(TenantTestCase):
    """Panggung master kanonik, seperti yang sudah ada di tenant demo."""

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "trial-seed"
        tenant.name = "Trial Seed"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

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

        cls.calendar = WorkCalendar.objects.create(
            code="OFFICE-2026", name="Office Calendar 2026",
            monday=True, tuesday=True, wednesday=True,
            thursday=True, friday=True, saturday=False, sunday=False,
            is_default=True,
        )
        cls.schedule = WorkSchedule.objects.create(
            code="REG5", name="Regular 5 Days",
        )
        cls.shift = Shift.objects.create(
            code="OFFICE-10", name="Office",
            start_time="10:00", end_time="18:00",
        )

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

        for code, name in (("STANDARD", "Standard"), ("STAFF", "Staff")):
            template = AllowanceTemplate.objects.create(code=code, name=name)
            AllowanceTemplateLine.objects.create(
                template=template,
                code="TRANSPORT", name="Transport", sequence=10,
                basis=PayrollBasis.PER_ATTENDANCE_DAY,
                amount=Decimal("25000"),
                is_taxable=True, is_prorated=False,
            )

        DeductionTemplate.objects.create(code="STANDARD", name="Standard")

        cls.leave_annual = LeaveType.objects.create(
            code="ANNUAL", name="Cuti Tahunan",
        )
        cls.leave_unpaid = LeaveType.objects.create(
            code="UNPAID", name="Cuti Tanpa Upah",
        )

        # Tanpa baris go-live, `LeaveOpeningBalanceService` menolak
        # menurunkan `opening_date` — dan itu memang perilaku yang benar.
        cls.go_live = LeaveGoLive.objects.create(
            company=cls.company, go_live_date=date(2026, 9, 1),
        )

    # ------------------------------------------------------------------
    # Pembantu
    # ------------------------------------------------------------------

    def setUp(self):
        super().setUp()

        self._tempdir = TemporaryDirectory()
        self.addCleanup(self._tempdir.cleanup)
        self.addCleanup(self._purge_trial)

    def make_spec(self, **overrides):
        """
        Preset demo, dipakai apa adanya kecuali yang memang diuji.

        Panggungnya tenant test, jadi `schema_names` dan direktori
        manifest yang digeser — bukan angka atau kode master, karena
        justru itu yang harus tetap sama dengan demo.
        """
        from django.db import connection

        defaults = {
            "schema_names": (connection.schema_name,),
            "manifest_dir": self._tempdir.name,
            "protected_counts": (),
        }
        defaults.update(overrides)

        return replace_spec(DEMO_TRIAL_SPEC, **defaults)

    def _purge_trial(self):
        """
        Membuang jejak trial supaya test berikutnya mulai dari nol.

        Urutannya anak dulu: baris penugasan menunjuk pegawai, dan
        `LeaveBalance` menunjuk keduanya.
        """
        employees = list(
            Employee._base_manager
            .filter(employee_number__in=DEMO_TRIAL_SPEC.tags)
            .values_list("pk", flat=True),
        )

        if employees:
            for model in (
                EmployeeAttendance,
                EmployeeLeave,
                EmployeeOvertime,
                EmployeeShiftAssignment,
                PayrollAssignment,
                OrganizationAssignment,
                EmploymentAssignment,
                LeaveOpeningBalance,
                LeaveBalance,
            ):
                model._base_manager.filter(
                    employee_id__in=employees,
                ).delete()

            Employee._base_manager.filter(pk__in=employees).delete()

        OvertimeGroupTier._base_manager.filter(
            group__code=DEMO_TRIAL_SPEC.overtime_group_code,
        ).delete()
        OvertimeGroup._base_manager.filter(
            code=DEMO_TRIAL_SPEC.overtime_group_code,
        ).delete()
        PayrollPolicy._base_manager.filter(
            code=DEMO_TRIAL_SPEC.daily_policy_code,
        ).delete()
        PayrollLeaveRule._base_manager.filter(
            leave_type__code=DEMO_TRIAL_SPEC.unpaid_leave_type_code,
        ).delete()

    @staticmethod
    def counts():
        return {
            "employee": Employee._base_manager.filter(
                employee_number__in=DEMO_TRIAL_SPEC.tags,
            ).count(),
            "overtime_group": OvertimeGroup._base_manager.filter(
                code=DEMO_TRIAL_SPEC.overtime_group_code,
            ).count(),
            "policy": PayrollPolicy._base_manager.filter(
                code=DEMO_TRIAL_SPEC.daily_policy_code,
            ).count(),
            "leave_rule": PayrollLeaveRule._base_manager.count(),
            "opening": LeaveOpeningBalance._base_manager.count(),
        }

    # ------------------------------------------------------------------
    # Mode kering
    # ------------------------------------------------------------------

    def test_dry_run_tidak_menulis_apa_pun(self):
        before = self.counts()

        report = TrialSeedService.plan(spec=self.make_spec())

        self.assertFalse(report.is_blocked, report.blockers)
        self.assertFalse(report.executed)
        self.assertEqual(self.counts(), before)

    def test_rencana_persis_seperti_rancangan(self):
        report = TrialSeedService.plan(spec=self.make_spec())

        self.assertEqual(
            report.planned,
            {
                "payroll.PayrollLeaveRule": 1,
                "payroll.OvertimeGroup": 1,
                "payroll.OvertimeGroupTier": 2,
                "payroll.PayrollPolicy": 1,
                "hr.Employee": 6,
                "hr.EmploymentAssignment": 6,
                "hr.OrganizationAssignment": 6,
                "hr.PayrollAssignment": 6,
                "hr.EmployeeShiftAssignment": 6,
                "hr.LeaveOpeningBalance": 1,
            },
        )
        self.assertEqual(report.planned_total, 36)

    def test_rujukan_kanonik_terselesaikan_tepat_satu(self):
        report = TrialSeedService.plan(spec=self.make_spec())

        for label in (
            "company", "branch", "location", "department", "section",
            "work_schedule", "work_calendar", "shift", "currency",
            "tax_status", "leave_type_annual", "leave_type_unpaid",
            "deduction_template",
            "payroll_group:MONTHLY", "payroll_group:DAILY",
            "allowance_template:STANDARD", "allowance_template:STAFF",
        ):
            self.assertIn(label, report.canonical)

    # ------------------------------------------------------------------
    # Eksekusi
    # ------------------------------------------------------------------

    def test_execute_membuat_enam_rantai_lengkap(self):
        spec = self.make_spec()

        report = TrialSeedService.execute(spec=spec)

        self.assertTrue(report.executed)
        self.assertEqual(report.created, report.planned)

        employees = Employee._base_manager.filter(
            employee_number__in=spec.tags,
        )
        self.assertEqual(employees.count(), 6)

        ids = list(employees.values_list("pk", flat=True))

        for model in (
            EmploymentAssignment,
            OrganizationAssignment,
            PayrollAssignment,
            EmployeeShiftAssignment,
        ):
            self.assertEqual(
                model._base_manager.filter(employee_id__in=ids).count(),
                6,
                model.__name__,
            )

    def test_penempatan_organisasi_seragam(self):
        spec = self.make_spec()

        TrialSeedService.execute(spec=spec)

        rows = OrganizationAssignment._base_manager.filter(
            employee__employee_number__in=spec.tags,
        )

        for row in rows:
            self.assertEqual(row.company.code, "MMR")
            self.assertEqual(row.branch.code, "DEFAULT")
            self.assertEqual(row.location.code, "JKT-HO")
            self.assertEqual(row.department.code, "PROC")
            self.assertEqual(row.section.code, "PROC_GENERAL")

    def test_trl02_tanggal_masuk_pertengahan_periode(self):
        spec = self.make_spec()

        TrialSeedService.execute(spec=spec)

        employment = EmploymentAssignment._base_manager.get(
            employee__employee_number="TRL02",
        )
        self.assertEqual(employment.join_date, date(2026, 9, 16))

        others = EmploymentAssignment._base_manager.filter(
            employee__employee_number__in=spec.tags,
        ).exclude(employee__employee_number="TRL02")

        for row in others:
            self.assertEqual(row.join_date, date(2025, 1, 6))

    def test_trl03_satu_satunya_yang_dapat_kelompok_lembur(self):
        spec = self.make_spec()

        TrialSeedService.execute(spec=spec)

        rows = {
            row.employee.employee_number: row
            for row in PayrollAssignment._base_manager.filter(
                employee__employee_number__in=spec.tags,
            ).select_related("employee", "overtime_group")
        }

        trl03 = rows["TRL03"]
        self.assertTrue(trl03.overtime_eligible)
        self.assertEqual(trl03.overtime_group.code, "TRL-OT-TIER")

        for tag in ("TRL01", "TRL02", "TRL04", "TRL05", "TRL06"):
            self.assertIsNone(rows[tag].overtime_group_id, tag)
            self.assertFalse(rows[tag].overtime_eligible, tag)

    def test_kelompok_lembur_bertingkat_terbentuk_benar(self):
        TrialSeedService.execute(spec=self.make_spec())

        group = OvertimeGroup._base_manager.get(code="TRL-OT-TIER")

        self.assertEqual(group.hourly_divisor, Decimal("173.00"))
        self.assertEqual(group.tier_basis, "daily")

        tiers = list(
            OvertimeGroupTier._base_manager
            .filter(group=group)
            .order_by("sequence"),
        )

        self.assertEqual(len(tiers), 2)
        self.assertEqual(tiers[0].hour_from, Decimal("0.00"))
        self.assertEqual(tiers[0].hour_to, Decimal("2.00"))
        self.assertEqual(tiers[0].multiplier, Decimal("1.50"))
        self.assertEqual(tiers[1].hour_from, Decimal("2.00"))
        self.assertIsNone(tiers[1].hour_to)
        self.assertEqual(tiers[1].multiplier, Decimal("2.00"))

    def test_trl05_satu_satunya_yang_dapat_kebijakan_harian(self):
        spec = self.make_spec()

        TrialSeedService.execute(spec=spec)

        rows = {
            row.employee.employee_number: row
            for row in PayrollAssignment._base_manager.filter(
                employee__employee_number__in=spec.tags,
            ).select_related("employee", "payroll_policy", "payroll_group")
        }

        trl05 = rows["TRL05"]
        self.assertEqual(trl05.payroll_group.code, "DAILY")
        self.assertEqual(trl05.payroll_policy.code, "TRL-DAILY")
        self.assertEqual(trl05.payroll_policy.pay_basis, "daily")
        self.assertEqual(trl05.payroll_policy.daily_rate_method, "from_monthly")
        self.assertEqual(
            trl05.payroll_policy.daily_rate_divisor, Decimal("26.00"),
        )
        self.assertTrue(trl05.payroll_policy.pays_paid_leave)

        for tag in ("TRL01", "TRL02", "TRL03", "TRL04", "TRL06"):
            self.assertIsNone(rows[tag].payroll_policy_id, tag)
            self.assertEqual(rows[tag].payroll_group.code, "MONTHLY", tag)

    def test_saldo_awal_terbit_lewat_lifecycle_kanonik(self):
        spec = self.make_spec()

        TrialSeedService.execute(spec=spec)

        opening = LeaveOpeningBalance._base_manager.get(
            employee__employee_number="TRL04",
        )

        self.assertEqual(opening.status, LeaveOpeningStatus.POSTED)
        self.assertEqual(opening.days, Decimal("6.0"))
        self.assertEqual(opening.opening_date, date(2026, 9, 1))
        self.assertEqual(opening.year, 2026)
        self.assertIsNotNone(opening.posted_at)

        balance = LeaveBalance._base_manager.get(
            employee=opening.employee,
            leave_type=opening.leave_type,
            year=2026,
        )

        # Angkanya datang dari dokumen, bukan diketik ke kartunya.
        self.assertEqual(balance.opening_balance, Decimal("6.0"))
        self.assertGreaterEqual(balance.remaining, Decimal("2.0"))

    def test_enam_rencana_shift_baseline(self):
        spec = self.make_spec()

        TrialSeedService.execute(spec=spec)

        rows = EmployeeShiftAssignment._base_manager.filter(
            employee__employee_number__in=spec.tags,
        )

        self.assertEqual(rows.count(), 6)

        for row in rows.select_related("shift"):
            self.assertEqual(row.layer, "baseline")
            self.assertEqual(row.kind, "work")
            self.assertEqual(row.shift.code, "OFFICE-10")
            self.assertEqual(row.start_date, PERIOD_START)
            self.assertEqual(row.end_date, PERIOD_END)

        # Cadangan permanen tetap terpasang di bawah lapis baseline.
        for employment in EmploymentAssignment._base_manager.filter(
            employee__employee_number__in=spec.tags,
        ).select_related("shift"):
            self.assertEqual(employment.shift.code, "OFFICE-10")

    def test_master_kanonik_tidak_tersentuh(self):
        spec = self.make_spec()

        def snapshot():
            return {
                "company": list(
                    Company.objects.values_list("pk", "code", "name"),
                ),
                "shift": list(Shift.objects.values_list("pk", "code", "name")),
                "allowance": list(
                    AllowanceTemplate.objects.values_list("pk", "code"),
                ),
                "deduction": list(
                    DeductionTemplate.objects.values_list("pk", "code"),
                ),
                "tax": list(TaxStatus.objects.values_list("pk", "code")),
                "group": list(PayrollGroup.objects.values_list("pk", "code")),
                "calendar": list(
                    WorkCalendar.objects.values_list("pk", "code"),
                ),
                "schedule": list(
                    WorkSchedule.objects.values_list("pk", "code"),
                ),
                "leave_type": list(
                    LeaveType.objects.values_list("pk", "code"),
                ),
            }

        before = snapshot()

        TrialSeedService.execute(spec=spec)

        self.assertEqual(snapshot(), before)

    def test_fase_satu_tidak_melahirkan_transaksi(self):
        spec = self.make_spec()

        TrialSeedService.execute(spec=spec)

        ids = list(
            Employee._base_manager
            .filter(employee_number__in=spec.tags)
            .values_list("pk", flat=True),
        )

        for model in (
            EmployeeAttendance, EmployeeLeave, EmployeeOvertime,
        ):
            self.assertEqual(
                model._base_manager.filter(employee_id__in=ids).count(),
                0,
                model.__name__,
            )

        self.assertEqual(PayrollPeriod._base_manager.count(), 0)
        self.assertEqual(PayrollRun._base_manager.count(), 0)

    # ------------------------------------------------------------------
    # Penolakan
    # ------------------------------------------------------------------

    def test_tabrakan_nomor_pegawai_membatalkan(self):
        """
        Satu `TRL0x` milik orang lain sudah cukup: penyemai tidak boleh
        menumpang di atas nomor yang bukan miliknya.
        """
        Employee.objects.create(
            employee_number="TRL03",
            first_name="Bukan", last_name="Trial",
        )

        spec = self.make_spec()
        report = TrialSeedService.plan(spec=spec)

        self.assertTrue(report.is_blocked)
        self.assertTrue(
            any("SETENGAH JADI" in b for b in report.blockers),
            report.blockers,
        )

        with self.assertRaises(TrialSeedAborted):
            TrialSeedService.execute(spec=spec)

        self.assertEqual(
            Employee._base_manager.filter(
                employee_number__in=spec.tags,
            ).count(),
            1,
        )

    def test_trial_rusak_membatalkan_bukan_ditambal(self):
        """
        Keenam pegawai ada tapi rantainya bolong — keadaan yang paling
        berbahaya, karena paling mirip "hampir selesai".
        """
        spec = self.make_spec()

        TrialSeedService.execute(spec=spec)

        EmployeeShiftAssignment._base_manager.filter(
            employee__employee_number="TRL05",
        ).delete()

        report = TrialSeedService.plan(spec=spec)

        self.assertTrue(report.is_blocked)
        self.assertTrue(
            any("RUSAK" in b for b in report.blockers), report.blockers,
        )
        self.assertFalse(report.already_seeded)

        with self.assertRaises(TrialSeedAborted):
            TrialSeedService.execute(spec=spec)

        # Tidak ditambal diam-diam.
        self.assertEqual(
            EmployeeShiftAssignment._base_manager.filter(
                employee__employee_number__in=spec.tags,
            ).count(),
            5,
        )

    def test_pegawai_asing_di_department_membatalkan(self):
        intruder = Employee.objects.create(
            employee_number="OUTSIDER1",
            first_name="Bukan", last_name="Trial",
        )
        OrganizationAssignment.objects.create(
            employee=intruder,
            company=self.company,
            department=self.department,
            organization_effective_date=date(2025, 1, 1),
        )
        self.addCleanup(
            lambda: (
                OrganizationAssignment._base_manager.filter(
                    employee=intruder,
                ).delete(),
                Employee._base_manager.filter(pk=intruder.pk).delete(),
            ),
        )

        report = TrialSeedService.plan(spec=self.make_spec())

        self.assertTrue(report.is_blocked)
        self.assertTrue(
            any("CAKUPAN" in b for b in report.blockers), report.blockers,
        )

    def test_schema_di_luar_daftar_ditolak(self):
        spec = self.make_spec(schema_names=("schema-lain",))

        report = TrialSeedService.plan(spec=spec)

        self.assertTrue(report.is_blocked)
        self.assertTrue(
            any("TENANT" in b for b in report.blockers), report.blockers,
        )

        with self.assertRaises(TrialSeedAborted):
            TrialSeedService.execute(spec=spec)

        self.assertEqual(self.counts()["employee"], 0)

    def test_baseline_terlindungi_yang_meleset_membatalkan(self):
        spec = self.make_spec(
            protected_counts=(("payroll.PayrollPeriod", 99),),
        )

        report = TrialSeedService.plan(spec=spec)

        self.assertTrue(report.is_blocked)
        self.assertTrue(
            any("BASELINE" in b for b in report.blockers), report.blockers,
        )

    def test_kunci_kanonik_tanpa_hasil_membatalkan(self):
        """
        Master yang berganti kode atau di-soft-delete membuat kuncinya
        tidak menemukan apa pun — dan trial berhenti, bukan berjalan
        dengan rujukan kosong.

        Ini cabang yang benar-benar bisa terjadi. Cabang "lebih dari
        satu" dijaga terpisah di bawah, karena skema sekarang
        mencegahnya di tingkat database.
        """
        report = TrialSeedService.plan(
            spec=self.make_spec(shift_code="SHIFT-YANG-TIDAK-ADA"),
        )

        self.assertTrue(report.is_blocked)
        self.assertTrue(
            any(
                "KANONIK" in b and "shift" in b and "0 baris" in b
                for b in report.blockers
            ),
            report.blockers,
        )

    def test_kunci_kanonik_ambigu_membatalkan(self):
        """
        Kunci yang cocok dengan dua baris ditolak.

        Seluruh master yang dirujuk trial hari ini punya unique index
        aktif, jadi keadaan ini **tidak bisa** dibuat lewat data biasa —
        dan itu temuan yang baik, bukan alasan melewatkan ujinya. Yang
        diuji di sini aturannya sendiri: kardinalitas selain satu
        berarti berhenti. Skema bisa berubah; aturannya tidak boleh
        ikut longgar diam-diam.
        """
        Employee.objects.create(
            employee_number="AMBI1", first_name="A", last_name="Satu",
        )
        Employee.objects.create(
            employee_number="AMBI2", first_name="A", last_name="Dua",
        )
        self.addCleanup(
            lambda: Employee._base_manager.filter(
                employee_number__in=["AMBI1", "AMBI2"],
            ).delete(),
        )

        with mock.patch.object(
            TrialSeedService,
            "_canonical_lookups",
            return_value={"shift": (Employee, {"is_deleted": False})},
        ):
            report = TrialSeedService.plan(spec=self.make_spec())

        self.assertTrue(report.is_blocked)
        self.assertTrue(
            any(
                "KANONIK" in b and "shift" in b and "2 baris" in b
                for b in report.blockers
            ),
            report.blockers,
        )

    # ------------------------------------------------------------------
    # Rollback & idempotensi
    # ------------------------------------------------------------------

    def test_gagal_di_tengah_membatalkan_seluruhnya(self):
        spec = self.make_spec()

        before = self.counts()

        def boom(**kwargs):
            raise RuntimeError("gagal disengaja sesudah pegawai dibuat")

        with mock.patch.object(
            TrialSeedService, "_create_opening_balance", side_effect=boom,
        ):
            with self.assertRaises(RuntimeError):
                TrialSeedService.execute(spec=spec)

        # Pegawai, master, dan rantai penugasannya harus ikut hilang.
        self.assertEqual(self.counts(), before)
        self.assertEqual(
            EmployeeShiftAssignment._base_manager.filter(
                employee__employee_number__in=spec.tags,
            ).count(),
            0,
        )

    def test_idempoten_setelah_eksekusi_berhasil(self):
        spec = self.make_spec()

        TrialSeedService.execute(spec=spec)

        after_first = self.counts()

        report = TrialSeedService.plan(spec=spec)

        self.assertFalse(report.is_blocked, report.blockers)
        self.assertTrue(report.already_seeded)
        self.assertEqual(report.planned_total, 0)

        # Eksekusi kedua pun tidak menambah apa pun.
        second = TrialSeedService.execute(spec=spec)

        self.assertTrue(second.already_seeded)
        self.assertFalse(second.executed)
        self.assertEqual(self.counts(), after_first)

    def test_baseline_tidak_menuduh_keadaan_yang_sudah_tersemai(self):
        """
        Sesudah penyemaian berhasil, `hr.Employee` memang bertambah enam.

        Kalau pagar baseline tetap membandingkannya dengan angka
        sebelum tanam, operator disuruh memakai bypass untuk keadaan
        idempoten yang justru sah — persis jebakan yang sama seperti
        pada pembersihan Finance.
        """
        before = Employee._base_manager.count()

        spec = self.make_spec(
            protected_counts=(("hr.Employee", before),),
        )

        TrialSeedService.execute(spec=spec)

        self.assertEqual(Employee._base_manager.count(), before + 6)

        report = TrialSeedService.plan(spec=spec)

        self.assertFalse(report.is_blocked, report.blockers)
        self.assertTrue(report.already_seeded)
        self.assertEqual(report.planned_total, 0)
        self.assertTrue(
            any("dilewati" in note for note in report.notes),
            report.notes,
        )

        # Eksekusi ulang pun tidak dihentikan pagar itu.
        second = TrialSeedService.execute(spec=spec)

        self.assertTrue(second.already_seeded)
        self.assertFalse(second.executed)

    def test_master_trial_tanpa_pegawai_membatalkan(self):
        """
        Kode `TRL-OT-TIER` yang sudah ada padahal pegawainya belum
        adalah sisa trial lain — bukan bahan yang boleh dipakai ulang.
        """
        OvertimeGroup.objects.create(
            code=DEMO_TRIAL_SPEC.overtime_group_code,
            name="Punya orang lain",
            hourly_multiplier=Decimal("1.00"),
            hourly_divisor=Decimal("173"),
            tier_basis="daily",
        )

        spec = self.make_spec()
        report = TrialSeedService.plan(spec=spec)

        self.assertTrue(report.is_blocked)
        self.assertTrue(
            any("MASTER TRIAL TANPA PEGAWAI" in b for b in report.blockers),
            report.blockers,
        )

        with self.assertRaises(TrialSeedAborted):
            TrialSeedService.execute(spec=spec)

        self.assertEqual(
            Employee._base_manager.filter(
                employee_number__in=spec.tags,
            ).count(),
            0,
        )

    def test_master_trial_yang_hilang_bukan_keadaan_lengkap(self):
        """Enam pegawai utuh tapi kebijakan hariannya lenyap = rusak."""
        spec = self.make_spec()

        TrialSeedService.execute(spec=spec)

        PayrollPolicy._base_manager.filter(
            code=spec.daily_policy_code,
        ).update(is_deleted=True)

        report = TrialSeedService.plan(spec=spec)

        self.assertFalse(report.already_seeded)
        self.assertTrue(
            any("TRIAL RUSAK" in b for b in report.blockers),
            report.blockers,
        )
        self.assertTrue(
            any("PayrollPolicy" in b for b in report.blockers),
            report.blockers,
        )

    def test_periode_run_workflow_notifikasi_finance_tidak_bergerak(self):
        """
        Pagar yang kedua: model yang barisnya belum tentu menunjuk
        pegawai diperiksa sebagai selisih global, di dalam transaksi.
        """
        before = TrialSeedService._forbidden_snapshot()

        for label in (
            "payroll.PayrollPeriod",
            "payroll.PayrollRun",
            "workflow.WorkflowInstance",
            "notifications.NotificationLog",
            "administration.Notification",
            "finance.AccountingEvent",
            "finance.Journal",
        ):
            self.assertIn(label, before)

        TrialSeedService.execute(spec=self.make_spec())

        self.assertEqual(TrialSeedService._forbidden_snapshot(), before)

    def test_aturan_cuti_yang_sudah_ada_dipakai_ulang(self):
        """
        `PayrollLeaveRule` berlaku se-tenant. Kalau sudah ada, penyemai
        memakainya — bukan membuat baris kedua yang akan menabrak
        `uniq_active_payroll_leave_rule`.
        """
        existing = PayrollLeaveRule.objects.create(
            leave_type=self.leave_unpaid, is_unpaid=True,
        )

        spec = self.make_spec()
        report = TrialSeedService.plan(spec=spec)

        self.assertEqual(report.planned["payroll.PayrollLeaveRule"], 0)

        executed = TrialSeedService.execute(spec=spec)

        self.assertEqual(executed.created["payroll.PayrollLeaveRule"], 0)
        self.assertEqual(PayrollLeaveRule._base_manager.count(), 1)
        self.assertEqual(
            PayrollLeaveRule._base_manager.get().pk, existing.pk,
        )

    # ------------------------------------------------------------------
    # Manifest
    # ------------------------------------------------------------------

    def test_manifest_ditulis_dan_memisahkan_dua_golongan(self):
        import json

        spec = self.make_spec()

        report = TrialSeedService.execute(spec=spec)

        path = Path(report.manifest_path)

        self.assertTrue(path.exists())
        self.assertEqual(path.name, f"{spec.trial_id}.json")

        manifest = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(manifest["trial_id"], spec.trial_id)
        self.assertEqual(manifest["phase"], "1-foundation")

        exclusive = manifest["created_exclusive_trial_objects"]
        shared = manifest["tenant_shared_created_for_trial"]

        self.assertEqual(len(exclusive["hr.Employee"]), 6)
        self.assertEqual(len(exclusive["payroll.OvertimeGroupTier"]), 2)
        self.assertIsNotNone(exclusive["hr.LeaveOpeningBalance"])
        self.assertIsNotNone(exclusive["hr.LeaveBalance"])

        # Aturan cuti se-tenant TIDAK boleh berada di golongan eksklusif.
        self.assertNotIn("payroll.PayrollLeaveRule", exclusive)
        self.assertIsNotNone(shared["payroll.PayrollLeaveRule"])
        self.assertTrue(
            shared["payroll.PayrollLeaveRule"]["created_by_trial"],
        )

        self.assertIn(
            "canonical_references", manifest,
        )
        self.assertEqual(
            manifest["canonical_references"]["keys"]["company"], "MMR",
        )

    def test_manifest_tidak_memuat_rahasia(self):
        import json

        report = TrialSeedService.execute(spec=self.make_spec())

        raw = Path(report.manifest_path).read_text(encoding="utf-8").lower()

        for needle in ("password", "secret", "token", "api_key", "db_pass"):
            self.assertNotIn(needle, raw, needle)

        json.loads(raw)


def replace_spec(spec, **overrides):
    """`dataclasses.replace` untuk spec beku."""
    from dataclasses import replace

    return replace(spec, **overrides)


class SpecShapeTestCase(SimpleTestCase):
    """Bentuk preset demo — diperiksa tanpa database."""

    def test_enam_pegawai_dengan_tag_yang_tepat(self):
        self.assertEqual(
            DEMO_TRIAL_SPEC.tags,
            ("TRL01", "TRL02", "TRL03", "TRL04", "TRL05", "TRL06"),
        )

    def test_trial_id_sesuai_kesepakatan(self):
        self.assertEqual(DEMO_TRIAL_SPEC.trial_id, "TRL-2026-09-E2E")

    def test_hanya_demo_yang_diizinkan(self):
        self.assertEqual(DEMO_TRIAL_SPEC.schema_names, ("demo",))

    def test_manifest_tidak_di_direktori_sementara(self):
        directory = DEMO_TRIAL_SPEC.manifest_dir

        self.assertFalse(directory.startswith("/tmp"))
        self.assertFalse(directory.startswith("/var/folders"))
        self.assertFalse(Path(directory).is_absolute())

    def test_manifest_diikat_ke_akar_repo_bukan_direktori_kerja(self):
        """
        `manifest_dir` relatif harus mendarat di akar repo. Kalau ia
        mengikuti direktori kerja proses, manifest tersebar ke tempat
        berbeda tiap kali perintah dipanggil dari direktori lain.
        """
        from django.conf import settings

        from apps.core.services.trial_seed_demo import MANIFEST_DIR

        expected = Path(settings.BASE_DIR) / MANIFEST_DIR

        self.assertTrue(expected.is_absolute())
        self.assertEqual(expected.name, "trial")

    def test_tepat_satu_pegawai_harian_dan_satu_berlembur(self):
        daily = [
            plan for plan in DEMO_TRIAL_SPEC.employees
            if plan.payroll_policy_code
        ]
        overtime = [
            plan for plan in DEMO_TRIAL_SPEC.employees
            if plan.overtime_group_code
        ]

        self.assertEqual([plan.tag for plan in daily], ["TRL05"])
        self.assertEqual([plan.tag for plan in overtime], ["TRL03"])
