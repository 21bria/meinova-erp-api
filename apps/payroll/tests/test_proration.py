"""
Business Decision #1 — kebijakan prorata gaji pokok.

Yang diuji di sini cuma satu pertanyaan: **berapa gaji pokok yang
berhak diterima pegawai yang tidak bekerja sepanjang periode.** Absensi,
cuti tidak dibayar, dan keterlambatan sengaja tidak ikut — itu Business
Decision #2 dan belum diputuskan.

Fixture-nya dipakai ulang dari `test_payroll_flow` supaya keadaan
awalnya persis sama dengan seluruh test payroll lainnya.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import date
from decimal import Decimal

from apps.administration.models import Holiday, WorkCalendar
from apps.hr.models import EmploymentAssignment
from apps.payroll.models import (
    AllowanceTemplate,
    AllowanceTemplateLine,
    PayrollBasis,
    PayrollPeriod,
    PayrollProrationMethod,
    PayrollRunEmployee,
    PayrollRunStatus,
    PayrollSetting,
    Payslip,
)
from apps.payroll.services import PayrollRunService, PayrollSettingService

from .test_payroll_flow import PayrollFlowTestCase


class ProrationTestCase(PayrollFlowTestCase):
    """Satu pegawai, satu periode, satu angka yang harus cocok."""

    def set_policy(self, method, *, on_join=True, on_termination=True):
        PayrollSetting.objects.update_or_create(
            company=self.company,
            defaults={
                "proration_method": method,
                "prorate_on_join": on_join,
                "prorate_on_termination": on_termination,
                "is_active": True,
            },
        )

    def make_month(self, year, month, last_day):
        """
        Satu periode sepanjang satu bulan penuh.

        Tahunnya digeser maju kalau rentang yang sama sudah dipakai test
        lain: `PayrollPeriod` unik per (company, payroll group, tanggal
        mulai, tanggal selesai), dan `TenantTestCase` tidak me-rollback
        antar test — periode test sebelumnya masih ada di database.
        Panjang bulannya ikut dijaga, jadi Februari kabisat tidak pernah
        diam-diam berganti jadi Februari biasa.
        """
        while (
            monthrange(year, month)[1] != last_day
            or PayrollPeriod.objects.filter(
                company=self.company,
                payroll_group=self.payroll_group,
                start_date=date(year, month, 1),
                end_date=date(year, month, last_day),
            ).exists()
        ):
            year += 1

        type(self)._counter += 1

        self.ensure_finance_calendar(date(year, month, last_day))

        return PayrollPeriod.objects.create(
            company=self.company,
            payroll_group=self.payroll_group,
            code=f"{year}-{month:02d}-{type(self)._counter}",
            name=f"{month:02d}/{year}",
            start_date=date(year, month, 1),
            end_date=date(year, month, last_day),
            payment_date=date(year, month, last_day),
        )

    @staticmethod
    def day_in(period, day):
        """Tanggal ke-`day` pada bulan periode itu — tahunnya ikut periode."""
        return period.start_date.replace(day=day)

    def basic_of(self, *, period, employee):
        """Gaji pokok hasil perhitungan, plus barisnya untuk diperiksa."""
        run = self.make_run(period)

        PayrollRunService.generate_employees(run=run)
        PayrollRunService.calculate(run=run)

        line = self.line_for(run, employee)

        return self.component(line, "BASIC").amount, line


class FullMonthTest(ProrationTestCase):
    """
    A. Pegawai yang aktif sepanjang periode dibayar penuh — apa pun
    metodenya, dan tanpa selisih pembulatan.
    """

    def test_sebulan_penuh_dibayar_penuh_untuk_seluruh_metode(self):
        for method in PayrollProrationMethod:
            with self.subTest(method=method.value):
                self.set_policy(method.value)

                period = self.make_month(2026, 9, 30)
                employee = self.make_employee(basic_salary="9000000")

                amount, line = self.basic_of(
                    period=period, employee=employee,
                )

                self.assertEqual(amount, Decimal("9000000.00"))
                self.assertEqual(line.proration_factor, Decimal("1.000000"))

    def test_bulan_31_hari_tidak_menyisakan_selisih_rupiah(self):
        """
        Pembagian yang hasilnya tidak bulat adalah cara paling mudah
        menghasilkan 9.999.999,99 dari gaji 10.000.000.
        """
        for method in PayrollProrationMethod:
            with self.subTest(method=method.value):
                self.set_policy(method.value)

                period = self.make_month(2026, 10, 31)
                employee = self.make_employee(basic_salary="10000000")

                amount, _ = self.basic_of(period=period, employee=employee)

                self.assertEqual(amount, Decimal("10000000.00"))

    def test_fixed_30_pada_bulan_31_hari_tidak_membayar_lebih(self):
        """
        31 / 30 = 1,033… Tanpa pembatas, pegawai yang bekerja penuh di
        bulan Oktober dibayar 3% lebih banyak daripada di September —
        untuk pekerjaan yang sama.
        """
        self.set_policy(PayrollProrationMethod.FIXED_30)

        period = self.make_month(2026, 10, 31)
        employee = self.make_employee(basic_salary="9000000")

        amount, line = self.basic_of(period=period, employee=employee)

        self.assertEqual(amount, Decimal("9000000.00"))
        self.assertEqual(line.proration_factor, Decimal("1.000000"))


class JoinMidMonthTest(ProrationTestCase):
    """B & C. Masuk di tengah periode."""

    def test_fixed_30_masuk_tanggal_16_dibayar_setengah(self):
        self.set_policy(PayrollProrationMethod.FIXED_30)

        period = self.make_month(2026, 9, 30)
        employee = self.make_employee(
            basic_salary="9000000",
            join_date=self.day_in(period, 16),
        )

        amount, line = self.basic_of(period=period, employee=employee)

        # 9.000.000 / 30 = 300.000 sehari; tanggal 16-30 = 15 hari.
        self.assertEqual(amount, Decimal("4500000.00"))
        self.assertEqual(line.working_days, Decimal("15.00"))
        self.assertEqual(line.proration_base_days, Decimal("30.00"))
        self.assertEqual(
            line.proration_method,
            PayrollProrationMethod.FIXED_30,
        )

    def test_tanggal_masuk_ikut_dihitung_sebagai_hari_berhak(self):
        """
        Off-by-one yang paling mudah lolos: tanggal 16-30 itu 15 hari,
        bukan 14. Semantiknya mengikuti `eligible_employees`, yang sudah
        membayar pegawai berhenti tanggal 20 untuk tanggal 1-20.
        """
        self.set_policy(PayrollProrationMethod.CALENDAR_DAYS)

        period = self.make_month(2026, 9, 30)
        employee = self.make_employee(
            basic_salary="9000000",
            join_date=self.day_in(period, 30),
        )

        _, line = self.basic_of(period=period, employee=employee)

        self.assertEqual(line.working_days, Decimal("1.00"))

    def test_calendar_days_bulan_30_hari(self):
        self.set_policy(PayrollProrationMethod.CALENDAR_DAYS)

        period = self.make_month(2026, 9, 30)
        employee = self.make_employee(
            basic_salary="9000000",
            join_date=self.day_in(period, 16),
        )

        amount, line = self.basic_of(period=period, employee=employee)

        self.assertEqual(amount, Decimal("4500000.00"))
        self.assertEqual(line.proration_base_days, Decimal("30.00"))

    def test_calendar_days_bulan_31_hari(self):
        self.set_policy(PayrollProrationMethod.CALENDAR_DAYS)

        period = self.make_month(2026, 10, 31)
        employee = self.make_employee(
            basic_salary="9300000",
            join_date=self.day_in(period, 17),
        )

        amount, line = self.basic_of(period=period, employee=employee)

        # Tanggal 17-31 = 15 hari dari 31.
        self.assertEqual(line.proration_base_days, Decimal("31.00"))
        self.assertEqual(line.working_days, Decimal("15.00"))
        self.assertEqual(amount, Decimal("4500000.00"))

    def test_calendar_days_februari_28_hari(self):
        self.set_policy(PayrollProrationMethod.CALENDAR_DAYS)

        period = self.make_month(2027, 2, 28)
        employee = self.make_employee(
            basic_salary="8400000",
            join_date=self.day_in(period, 15),
        )

        amount, line = self.basic_of(period=period, employee=employee)

        # Tanggal 15-28 = 14 hari dari 28, tepat setengah.
        self.assertEqual(line.proration_base_days, Decimal("28.00"))
        self.assertEqual(line.working_days, Decimal("14.00"))
        self.assertEqual(amount, Decimal("4200000.00"))

    def test_calendar_days_februari_kabisat_29_hari(self):
        self.set_policy(PayrollProrationMethod.CALENDAR_DAYS)

        period = self.make_month(2028, 2, 29)
        employee = self.make_employee(
            basic_salary="8700000",
            join_date=self.day_in(period, 16),
        )

        amount, line = self.basic_of(period=period, employee=employee)

        # Tanggal 16-29 = 14 hari dari 29.
        self.assertEqual(line.proration_base_days, Decimal("29.00"))
        self.assertEqual(line.working_days, Decimal("14.00"))
        self.assertEqual(amount, Decimal("4200000.00"))

    def test_februari_kabisat_pembaginya_beda_dari_februari_biasa(self):
        """
        Dua Februari dengan gaji dan tanggal masuk yang sama harus
        menghasilkan angka yang **berbeda** pada metode kalender. Kalau
        sama, pembaginya tidak benar-benar dibaca dari periodenya.
        """
        self.set_policy(PayrollProrationMethod.CALENDAR_DAYS)

        period_biasa = self.make_month(2027, 2, 28)
        period_kabisat = self.make_month(2028, 2, 29)

        biasa = self.make_employee(
            basic_salary="8400000",
            join_date=self.day_in(period_biasa, 15),
        )
        kabisat = self.make_employee(
            basic_salary="8400000",
            join_date=self.day_in(period_kabisat, 15),
        )

        amount_biasa, _ = self.basic_of(period=period_biasa, employee=biasa)
        amount_kabisat, _ = self.basic_of(
            period=period_kabisat, employee=kabisat,
        )

        # 14/28 lawan 15/29.
        self.assertEqual(amount_biasa, Decimal("4200000.00"))
        self.assertEqual(amount_kabisat, Decimal("4344827.59"))


class TerminationMidMonthTest(ProrationTestCase):
    """D. Berhenti di tengah periode."""

    def test_berhenti_tanggal_15_dibayar_setengah(self):
        self.set_policy(PayrollProrationMethod.FIXED_30)

        period = self.make_month(2026, 9, 30)
        employee = self.make_employee(
            basic_salary="9000000",
            termination_date=self.day_in(period, 15),
        )

        amount, line = self.basic_of(period=period, employee=employee)

        # Tanggal 1-15 = 15 hari; tanggal berhentinya ikut dibayar.
        self.assertEqual(line.working_days, Decimal("15.00"))
        self.assertEqual(amount, Decimal("4500000.00"))

    def test_hari_terakhir_kerja_ikut_dibayar(self):
        """
        Batasnya **inclusive**, mengikuti semantik `Employment` yang
        sudah dipakai `eligible_employees`. Kalau exclusive, setiap
        pegawai yang berhenti kehilangan satu hari upah diam-diam.
        """
        self.set_policy(PayrollProrationMethod.CALENDAR_DAYS)

        period = self.make_month(2026, 9, 30)
        employee = self.make_employee(
            basic_salary="9000000",
            termination_date=self.day_in(period, 1),
        )

        _, line = self.basic_of(period=period, employee=employee)

        self.assertEqual(line.working_days, Decimal("1.00"))

    def test_berhenti_di_hari_terakhir_periode_tetap_penuh(self):
        self.set_policy(PayrollProrationMethod.CALENDAR_DAYS)

        period = self.make_month(2026, 9, 30)
        employee = self.make_employee(
            basic_salary="9000000",
            termination_date=self.day_in(period, 30),
        )

        amount, line = self.basic_of(period=period, employee=employee)

        self.assertEqual(amount, Decimal("9000000.00"))
        self.assertEqual(line.proration_factor, Decimal("1.000000"))


class JoinAndTerminationSamePeriodTest(ProrationTestCase):
    """E. Masuk dan berhenti di periode yang sama."""

    def test_irisan_dihitung_dari_kedua_batas(self):
        self.set_policy(PayrollProrationMethod.FIXED_30)

        period = self.make_month(2026, 9, 30)
        employee = self.make_employee(
            basic_salary="9000000",
            join_date=self.day_in(period, 11),
            termination_date=self.day_in(period, 20),
        )

        amount, line = self.basic_of(period=period, employee=employee)

        # Tanggal 11-20 = 10 hari.
        self.assertEqual(line.working_days, Decimal("10.00"))
        self.assertEqual(amount, Decimal("3000000.00"))

    def test_masuk_dan_berhenti_di_hari_yang_sama_dibayar_sehari(self):
        self.set_policy(PayrollProrationMethod.CALENDAR_DAYS)

        period = self.make_month(2026, 9, 30)
        employee = self.make_employee(
            basic_salary="9000000",
            join_date=self.day_in(period, 10),
            termination_date=self.day_in(period, 10),
        )

        _, line = self.basic_of(period=period, employee=employee)

        self.assertEqual(line.working_days, Decimal("1.00"))
        self.assertGreater(line.proration_factor, Decimal("0"))

    def test_tidak_pernah_menghasilkan_hari_negatif(self):
        """
        Tanggal berhenti sebelum tanggal masuk adalah data yang salah,
        tapi payroll tidak boleh membalasnya dengan angka negatif.
        """
        self.set_policy(PayrollProrationMethod.CALENDAR_DAYS)

        period = self.make_month(2026, 9, 30)
        employee = self.make_employee(basic_salary="9000000")

        EmploymentAssignment.objects.filter(employee=employee).update(
            join_date=self.day_in(period, 20),
            termination_date=self.day_in(period, 10),
        )

        amount, line = self.basic_of(period=period, employee=employee)

        self.assertEqual(line.working_days, Decimal("0.00"))
        self.assertEqual(line.proration_factor, Decimal("0.000000"))
        self.assertEqual(amount, Decimal("0.00"))

    def test_faktor_tidak_pernah_melebihi_satu(self):
        self.set_policy(PayrollProrationMethod.FIXED_30)

        period = self.make_month(2026, 10, 31)
        employee = self.make_employee(
            basic_salary="9000000",
            join_date=self.day_in(period, 1),
        )

        amount, line = self.basic_of(period=period, employee=employee)

        self.assertLessEqual(line.proration_factor, Decimal("1.000000"))
        self.assertEqual(amount, Decimal("9000000.00"))


class ProrationDisabledTest(ProrationTestCase):
    """F. Prorata dimatikan."""

    def test_prorate_on_join_mati_membayar_sebulan_penuh(self):
        self.set_policy(PayrollProrationMethod.FIXED_30, on_join=False)

        period = self.make_month(2026, 9, 30)
        employee = self.make_employee(
            basic_salary="9000000",
            join_date=self.day_in(period, 16),
        )

        amount, line = self.basic_of(period=period, employee=employee)

        self.assertEqual(amount, Decimal("9000000.00"))
        self.assertEqual(line.proration_factor, Decimal("1.000000"))

    def test_prorate_on_termination_mati_membayar_sebulan_penuh(self):
        self.set_policy(
            PayrollProrationMethod.CALENDAR_DAYS,
            on_termination=False,
        )

        period = self.make_month(2026, 9, 30)
        employee = self.make_employee(
            basic_salary="9000000",
            termination_date=self.day_in(period, 15),
        )

        amount, _ = self.basic_of(period=period, employee=employee)

        self.assertEqual(amount, Decimal("9000000.00"))

    def test_mematikan_satu_saklar_tidak_mematikan_yang_lain(self):
        """
        Masuk **dan** berhenti di periode yang sama, dengan prorata
        masuk dimatikan: batas bawahnya ikut awal periode, batas atasnya
        tetap tanggal berhenti.
        """
        self.set_policy(PayrollProrationMethod.FIXED_30, on_join=False)

        period = self.make_month(2026, 9, 30)
        employee = self.make_employee(
            basic_salary="9000000",
            join_date=self.day_in(period, 11),
            termination_date=self.day_in(period, 20),
        )

        amount, line = self.basic_of(period=period, employee=employee)

        # Tanggal 1-20 = 20 hari, bukan 10. 9.000.000 x 20 / 30 tepat
        # 6.000.000 — bukan 6.000.003 seperti kalau dikalikan faktor
        # 0,666667 yang sudah dibulatkan.
        self.assertEqual(line.working_days, Decimal("20.00"))
        self.assertEqual(amount, Decimal("6000000.00"))


class AllowanceProrationTest(ProrationTestCase):
    """G. `is_prorated` per komponen tetap yang menentukan."""

    def setUp(self):
        super().setUp()

        type(self)._counter += 1

        self.template = AllowanceTemplate.objects.create(
            code=f"PRO-{type(self)._counter}",
            name="Proration Test",
        )

        AllowanceTemplateLine.objects.create(
            template=self.template,
            code="POSISI",
            name="Tunjangan Jabatan",
            sequence=10,
            basis=PayrollBasis.FIXED,
            amount=Decimal("1000000"),
            is_prorated=True,
        )

        AllowanceTemplateLine.objects.create(
            template=self.template,
            code="PULSA",
            name="Tunjangan Pulsa",
            sequence=20,
            basis=PayrollBasis.FIXED,
            amount=Decimal("200000"),
            is_prorated=False,
        )

    def test_hanya_komponen_ber_is_prorated_yang_ikut_faktor(self):
        self.set_policy(PayrollProrationMethod.FIXED_30)

        period = self.make_month(2026, 9, 30)
        employee = self.make_employee(
            basic_salary="9000000",
            join_date=self.day_in(period, 16),
        )

        employee.payroll_assignments.update(allowance_template=self.template)

        _, line = self.basic_of(period=period, employee=employee)

        self.assertEqual(
            self.component(line, "POSISI").amount,
            Decimal("500000.00"),
        )
        self.assertEqual(
            self.component(line, "PULSA").amount,
            Decimal("200000.00"),
        )


class WorkingDaysMethodTest(ProrationTestCase):
    """
    I. WORKING_DAYS diuji terhadap kalender kerja yang sungguhan.

    Sumbernya `WorkCalendar` + `Holiday` lewat
    `LeaveDayCalculator.count_working_days` — kalender yang sama yang
    sudah dipakai memotong saldo cuti. Tidak ada Senin-Jumat yang
    ditanam di Payroll.

    Tahunnya dipatok jauh ke depan supaya tidak bertabrakan dengan
    periode test lain: susunan hari dalam bulannya yang diuji di sini,
    jadi tahunnya tidak boleh bergeser diam-diam.
    """

    def setUp(self):
        super().setUp()

        type(self)._counter += 1

        self.calendar = WorkCalendar.objects.create(
            company=self.company,
            code=f"WD-{type(self)._counter}",
            name="Senin-Jumat",
            monday=True,
            tuesday=True,
            wednesday=True,
            thursday=True,
            friday=True,
            saturday=False,
            sunday=False,
            is_default=True,
        )

    def attach(self, employee):
        employment = employee.employment
        employment.working_calendar = self.calendar
        employment.save(update_fields=["working_calendar"])

    def test_pembilang_dan_pembagi_sama_sama_hari_kerja(self):
        self.set_policy(PayrollProrationMethod.WORKING_DAYS)

        period = self.make_month(2060, 9, 30)

        self.assertEqual(period.start_date.year, 2060)

        employee = self.make_employee(
            basic_salary="8800000",
            join_date=self.day_in(period, 16),
        )
        self.attach(employee)

        amount, line = self.basic_of(period=period, employee=employee)

        # September 2060: 22 hari kerja Senin-Jumat, 11 di antaranya
        # jatuh pada tanggal 16-30.
        self.assertEqual(line.proration_base_days, Decimal("22.00"))
        self.assertEqual(line.working_days, Decimal("11.00"))
        self.assertEqual(amount, Decimal("4400000.00"))

    def test_sebulan_penuh_tetap_gaji_sebulan(self):
        self.set_policy(PayrollProrationMethod.WORKING_DAYS)

        period = self.make_month(2061, 9, 30)
        employee = self.make_employee(basic_salary="8800000")
        self.attach(employee)

        amount, line = self.basic_of(period=period, employee=employee)

        self.assertEqual(amount, Decimal("8800000.00"))
        self.assertEqual(line.proration_factor, Decimal("1.000000"))

    def test_hari_libur_mengurangi_pembagi(self):
        """
        Hari libur nasional bukan hari kerja. Kalau `Holiday` tidak
        dibaca, pembaginya terlalu besar dan setiap pegawai yang masuk
        di tengah bulan dibayar kurang.
        """
        self.set_policy(PayrollProrationMethod.WORKING_DAYS)

        period = self.make_month(2062, 9, 30)

        self.assertEqual(period.start_date.year, 2062)

        # 18 September 2062 jatuh hari Senin.
        Holiday.objects.create(
            company=self.company,
            date=date(2062, 9, 18),
            code=f"HOL-{type(self)._counter}",
            name="Libur Uji",
            is_national=True,
        )

        employee = self.make_employee(
            basic_salary="8800000",
            join_date=self.day_in(period, 16),
        )
        self.attach(employee)

        _, line = self.basic_of(period=period, employee=employee)

        # September 2062 punya 21 hari kerja, 10 di antaranya pada
        # tanggal 16-30; liburnya memotong satu dari masing-masing.
        self.assertEqual(line.proration_base_days, Decimal("20.00"))
        self.assertEqual(line.working_days, Decimal("9.00"))


class PolicyResolutionTest(ProrationTestCase):
    """Kebijakan dibaca dari perusahaan, bukan dari pegawai."""

    def test_tanpa_baris_setting_memakai_bawaan_dan_menandainya(self):
        PayrollSetting.objects.filter(company=self.company).delete()

        policy = PayrollSettingService.resolve_policy(company=self.company)

        self.assertTrue(policy.is_default)
        self.assertEqual(
            policy.method,
            PayrollProrationMethod.CALENDAR_DAYS,
        )

    def test_perusahaan_tanpa_kebijakan_menerbitkan_warning(self):
        """
        Angkanya tetap terbit — yang tidak boleh adalah diamnya.
        "Belum dipilih" dan "sudah dipilih, kebetulan Kalender"
        menghasilkan angka yang sama persis.
        """
        PayrollSetting.objects.filter(company=self.company).delete()

        period = self.make_month(2026, 9, 30)
        employee = self.make_employee(basic_salary="9000000")

        run = self.make_run(period)

        PayrollRunService.generate_employees(run=run)
        result = PayrollRunService.calculate(run=run)

        codes = [item["code"] for item in result["validation"]["warnings"]]

        self.assertIn("proration_policy_missing", codes)
        self.assertEqual(
            self.component(self.line_for(run, employee), "BASIC").amount,
            Decimal("9000000.00"),
        )

    def test_kebijakan_yang_sudah_dipilih_tidak_menerbitkan_warning(self):
        self.set_policy(PayrollProrationMethod.FIXED_30)

        period = self.make_month(2026, 9, 30)
        self.make_employee(basic_salary="9000000")

        run = self.make_run(period)

        PayrollRunService.generate_employees(run=run)
        result = PayrollRunService.calculate(run=run)

        codes = [item["code"] for item in result["validation"]["warnings"]]

        self.assertNotIn("proration_policy_missing", codes)

    def test_metode_dan_pembagi_tercatat_di_barisnya(self):
        """
        "Kenapa gaji pokoknya 4.500.000" harus terjawab dari barisnya
        sendiri, tanpa menghitung ulang.
        """
        self.set_policy(PayrollProrationMethod.FIXED_30)

        period = self.make_month(2026, 9, 30)
        employee = self.make_employee(
            basic_salary="9000000",
            join_date=self.day_in(period, 16),
        )

        _, line = self.basic_of(period=period, employee=employee)

        self.assertEqual(
            line.proration_method,
            PayrollProrationMethod.FIXED_30,
        )
        self.assertEqual(line.proration_base_days, Decimal("30.00"))
        self.assertEqual(line.working_days, Decimal("15.00"))
        self.assertEqual(line.basic_salary, Decimal("9000000.00"))

        note = self.component(line, "BASIC").calculation_note

        self.assertIn("15", note)
        self.assertIn("30", note)
        self.assertIn("Fixed 30", note)


class FinalizedPolicyChangeTest(ProrationTestCase):
    """
    H. Kebijakan yang berganti bulan depan tidak menyentuh payroll yang
    sudah difinalisasi.

    Jaminannya **bukan** versioning kebijakan, melainkan penguncian yang
    sudah ada: run FINALIZED menolak dihitung ulang dan angkanya sudah
    dibekukan di `PayrollRunEmployee` beserta `Payslip.snapshot`.
    """

    def finalize(self, *, period):
        run = self.make_run(period)

        PayrollRunService.generate_employees(run=run)
        PayrollRunService.calculate(run=run)

        PayrollRunEmployee.objects.filter(
            run=run, payroll_assignment__isnull=True,
        ).update(
            is_excluded=True,
            status="excluded",
            exclusion_reason="Konfigurasi belum lengkap (fixture).",
        )

        PayrollRunService._refresh_totals(run=run)
        PayrollRunService.validate(run=run)
        PayrollRunService.acknowledge(run=run)

        run.refresh_from_db()
        run.status = PayrollRunStatus.APPROVED
        run.save(update_fields=["status"])

        PayrollRunService.finalize(run=run)

        run.refresh_from_db()

        return run

    def test_mengganti_metode_tidak_mengubah_run_yang_sudah_final(self):
        self.set_policy(PayrollProrationMethod.FIXED_30)

        period = self.make_month(2026, 10, 31)
        employee = self.make_employee(
            basic_salary="9300000",
            join_date=self.day_in(period, 17),
        )

        run = self.finalize(period=period)

        line = self.line_for(run, employee)
        before = self.component(line, "BASIC").amount

        # 9.300.000 / 30 x 15 hari.
        self.assertEqual(before, Decimal("4650000.00"))

        # Bulan depan perusahaan pindah ke hari kerja.
        self.set_policy(PayrollProrationMethod.WORKING_DAYS)

        line.refresh_from_db()

        self.assertEqual(self.component(line, "BASIC").amount, before)
        self.assertEqual(line.proration_base_days, Decimal("30.00"))
        self.assertEqual(
            line.proration_method,
            PayrollProrationMethod.FIXED_30,
        )

    def test_slip_yang_sudah_terbit_tetap_membawa_metode_lamanya(self):
        self.set_policy(PayrollProrationMethod.FIXED_30)

        period = self.make_month(2026, 9, 30)
        employee = self.make_employee(
            basic_salary="9000000",
            join_date=self.day_in(period, 16),
        )

        run = self.finalize(period=period)

        slip = Payslip.objects.get(
            run_employee=self.line_for(run, employee),
        )

        self.set_policy(PayrollProrationMethod.CALENDAR_DAYS)

        slip.refresh_from_db()

        self.assertEqual(
            slip.snapshot["days"]["proration_method"],
            PayrollProrationMethod.FIXED_30,
        )
        self.assertEqual(
            slip.snapshot["days"]["proration_base_days"],
            "30.00",
        )

    def test_periode_berikutnya_memakai_kebijakan_yang_baru(self):
        """
        Sisi lain dari test di atas: yang belum final **harus** ikut
        berubah, kalau tidak kebijakannya tidak pernah berlaku.
        """
        self.set_policy(PayrollProrationMethod.FIXED_30)

        period_lama = self.make_month(2026, 10, 31)
        period_baru = self.make_month(2026, 10, 31)

        # Dua pegawai, karena kedua periodenya jatuh di tahun yang
        # berbeda — satu orang tidak bisa masuk tanggal 17 di dua tahun.
        # Yang dibandingkan tetap keadaan yang sama persis: gaji sama,
        # tanggal masuk sama, panjang bulan sama.
        lama = self.make_employee(
            basic_salary="9300000",
            join_date=self.day_in(period_lama, 17),
        )
        baru = self.make_employee(
            basic_salary="9300000",
            join_date=self.day_in(period_baru, 17),
        )

        amount_lama, _ = self.basic_of(period=period_lama, employee=lama)

        self.set_policy(PayrollProrationMethod.CALENDAR_DAYS)

        amount_baru, _ = self.basic_of(period=period_baru, employee=baru)

        self.assertEqual(amount_lama, Decimal("4650000.00"))
        self.assertEqual(amount_baru, Decimal("4500000.00"))
