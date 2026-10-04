"""
Payroll Policy — aturan perhitungan per kelompok pegawai.

Yang diuji di sini satu pertanyaan yang tidak pernah bisa dijawab
sebelumnya: **dua orang di perusahaan yang sama, dihitung dengan cara
yang berbeda, di dalam satu run yang sama.**

Tiga lapis yang urutannya harus tetap — kebijakan kelompok, default
perusahaan, perilaku teknis lama — dan satu jebakan yang seluruh bagian
kedua berkas ini ada untuk membuktikan tidak terjadi: pegawai harian
yang hari alpanya tidak menghasilkan upah **dan** dipotong lagi karena
alpa. Itu potongan dua kali untuk satu hari yang sama.

Fixture-nya dipakai ulang dari `test_attendance_deduction`, yang
dipakai ulang dari `test_proration`, supaya keadaan awalnya persis sama
dengan seluruh test payroll lainnya.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError

from apps.hr.models import PayrollAssignment
from apps.payroll.models import (
    PayrollDailyRateMethod,
    PayrollPayBasis,
    PayrollPolicy,
    PayrollPolicyToggle,
    PayrollProrationMethod,
    PayrollRunStatus,
    PayrollSetting,
    Payslip,
)
from apps.payroll.services import (
    PayrollPolicyService,
    PayrollRunService,
    PayrollSettingService,
)

from .test_attendance_deduction import AttendanceDeductionTestCase


class PolicyTestCase(AttendanceDeductionTestCase):
    """
    Satu perusahaan, beberapa kebijakan, angka yang harus cocok sampai
    rupiah.
    """

    # ------------------------------------------------------------------
    # Pabrik kebijakan
    # ------------------------------------------------------------------

    def make_policy(self, **kwargs):
        type(self)._counter += 1

        defaults = {
            "company": self.company,
            "code": f"POL{type(self)._counter}",
            "name": f"Policy {type(self)._counter}",
            "pay_basis": PayrollPayBasis.MONTHLY,
            "is_active": True,
        }
        defaults.update(kwargs)

        policy = PayrollPolicy(**defaults)
        policy.full_clean()
        policy.save()

        return policy

    def make_daily_policy(self, **kwargs):
        """
        Kebijakan harian yang **lengkap**. Yang tidak lengkap dibuat
        sendiri oleh test yang memang mengujinya — kelengkapan itu
        justru salah satu yang diperiksa.
        """
        defaults = {
            "pay_basis": PayrollPayBasis.DAILY,
            "daily_rate_method": PayrollDailyRateMethod.ASSIGNMENT_RATE,
            "pay_paid_leave": "no",
        }
        defaults.update(kwargs)

        return self.make_policy(**defaults)

    def assign_policy(self, employee, policy=None, *, daily_rate=None):
        """
        Pasang kebijakan pada assignment yang berlaku sekarang.

        Menyunting baris yang ada, bukan membuat baris baru: yang diuji
        di sebagian besar berkas ini bukan pergantian kebijakan
        melainkan akibatnya. Pergantiannya sendiri punya kelasnya
        sendiri di bawah.
        """
        assignment = (
            PayrollAssignment.objects
            .filter(employee=employee, is_current=True, is_deleted=False)
            .first()
        )

        assignment.payroll_policy = policy

        if daily_rate is not None:
            assignment.daily_rate = Decimal(daily_rate)

        assignment.full_clean()
        assignment.save()

        return assignment

    def make_daily_employee(
        self,
        *,
        policy,
        daily_rate="200000",
        basic_salary="0",
        join_date=date(2025, 1, 1),
    ):
        employee = self.make_employee(
            basic_salary=basic_salary, join_date=join_date,
        )
        self.assign_policy(employee, policy, daily_rate=daily_rate)

        return employee


# ----------------------------------------------------------------------
# A. Default perusahaan
# ----------------------------------------------------------------------


class CompanyDefaultTest(PolicyTestCase):
    def test_tanpa_kebijakan_mengikuti_payroll_setting_perusahaan(self):
        """
        A. Pegawai tanpa Payroll Policy dihitung persis seperti sebelum
        kebijakan ini ada.
        """
        self.set_policy(PayrollProrationMethod.CALENDAR_DAYS)

        period = self.make_month(2026, 4, 30)
        employee = self.make_employee(
            basic_salary="9000000", join_date=self.day_in(period, 16),
        )

        line, _ = self.run_payroll(period=period, employee=employee)

        self.assertIsNone(line.payroll_policy_id)
        self.assertEqual(line.pay_basis, PayrollPayBasis.MONTHLY)
        self.assertEqual(
            line.proration_method, PayrollProrationMethod.CALENDAR_DAYS,
        )

        # 15 dari 30 hari kalender.
        self.assertEqual(
            self.component(line, "BASIC").amount, Decimal("4500000.00"),
        )

    def test_kebijakan_kosong_seluruhnya_sama_dengan_tanpa_kebijakan(self):
        """
        Kebijakan yang tidak menimpa apa pun tidak boleh menggeser satu
        rupiah pun. Kosong berarti **ikut**, bukan matikan.
        """
        self.set_policy(
            PayrollProrationMethod.FIXED_30,
            on_join=False,
        )

        policy = self.make_policy()

        period = self.make_month(2026, 5, 31)

        plain = self.make_employee(
            basic_salary="9000000", join_date=self.day_in(period, 16),
        )
        with_policy = self.make_employee(
            basic_salary="9000000", join_date=self.day_in(period, 16),
        )
        self.assign_policy(with_policy, policy)

        run = self.make_run(period)
        PayrollRunService.generate_employees(run=run)
        PayrollRunService.calculate(run=run)

        first = self.line_for(run, plain)
        second = self.line_for(run, with_policy)

        self.assertEqual(first.net_pay, second.net_pay)
        self.assertEqual(
            second.proration_method, PayrollProrationMethod.FIXED_30,
        )
        # Saklar `False` perusahaan tidak boleh dinyalakan kembali oleh
        # kebijakan yang diam.
        self.assertEqual(second.proration_factor, Decimal("1.000000"))

    def test_kebijakan_nonaktif_jatuh_ke_default_perusahaan(self):
        self.set_policy(PayrollProrationMethod.CALENDAR_DAYS)

        policy = self.make_policy(
            proration_method=PayrollProrationMethod.FIXED_30,
            is_active=False,
        )

        period = self.make_month(2026, 7, 31)
        employee = self.make_employee(
            basic_salary="9000000", join_date=self.day_in(period, 17),
        )
        self.assign_policy(employee, policy)

        line, run = self.run_payroll(period=period, employee=employee)

        self.assertEqual(
            line.proration_method, PayrollProrationMethod.CALENDAR_DAYS,
        )

        codes = {item["code"] for item in run.validation_summary["warnings"]}
        self.assertIn("policy_inactive", codes)


# ----------------------------------------------------------------------
# B. Penimpaan aturan bulanan
# ----------------------------------------------------------------------


class MonthlyOverrideTest(PolicyTestCase):
    def test_kebijakan_menimpa_metode_prorata_perusahaan(self):
        """
        B. Perusahaan Calendar Days, kebijakan Fixed 30 — yang berlaku
        Fixed 30.
        """
        self.set_policy(PayrollProrationMethod.CALENDAR_DAYS)

        policy = self.make_policy(
            proration_method=PayrollProrationMethod.FIXED_30,
        )

        # 31 hari, masuk tanggal 17 → 15 hari.
        period = self.make_month(2026, 8, 31)
        employee = self.make_employee(
            basic_salary="9000000", join_date=self.day_in(period, 17),
        )
        self.assign_policy(employee, policy)

        line, _ = self.run_payroll(period=period, employee=employee)

        self.assertEqual(
            line.proration_method, PayrollProrationMethod.FIXED_30,
        )
        self.assertEqual(line.proration_base_days, Decimal("30.00"))
        self.assertEqual(
            self.component(line, "BASIC").amount, Decimal("4500000.00"),
        )

    def test_kebijakan_menimpa_pembagi_potongan_saja(self):
        """
        Prorata dan potongan dua keputusan terpisah, dan kebijakan boleh
        menimpa yang satu tanpa menyentuh yang lain.
        """
        self.set_attendance_policy(PayrollProrationMethod.FIXED_30)
        self.set_policy(PayrollProrationMethod.CALENDAR_DAYS)

        policy = self.make_policy(
            attendance_deduction_method=PayrollProrationMethod.CALENDAR_DAYS,
        )

        period = self.make_month(2026, 10, 31)
        employee = self.make_employee(basic_salary="9300000")
        self.assign_policy(employee, policy)

        self.make_absence(employee, self.day_in(period, 6))

        line, _ = self.run_payroll(period=period, employee=employee)

        # Pembagi 31 (kebijakan), bukan 30 (perusahaan).
        self.assertEqual(line.deduction_base_days, Decimal("31.00"))
        self.assertEqual(line.absence_deduction, Decimal("300000.00"))

        # Prorata tetap milik perusahaan.
        self.assertEqual(
            line.proration_method, PayrollProrationMethod.CALENDAR_DAYS,
        )

    def test_kebijakan_boleh_mematikan_potongan_yang_dinyalakan_perusahaan(self):
        """
        `Tidak` adalah keputusan, bukan kekosongan. Saklar yang sengaja
        dimatikan kebijakan tidak boleh dinyalakan kembali perusahaan.
        """
        self.set_attendance_policy(
            PayrollProrationMethod.FIXED_30, absence=True,
        )

        policy = self.make_policy(deduct_absence=PayrollPolicyToggle.OFF)

        period = self.make_month(2027, 10, 31)
        employee = self.make_employee(basic_salary="9000000")
        self.assign_policy(employee, policy)

        self.make_absence(employee, self.day_in(period, 8))

        line, _ = self.run_payroll(period=period, employee=employee)

        self.assertEqual(line.absent_days, Decimal("1.00"))
        self.assertEqual(line.absence_deduction, Decimal("0.00"))
        self.assertNotIn("ABSENT", self.codes(line))

    def test_kebijakan_boleh_menyalakan_prorata_yang_dimatikan_perusahaan(self):
        self.set_policy(PayrollProrationMethod.FIXED_30, on_join=False)

        policy = self.make_policy(
            prorate_on_join=PayrollPolicyToggle.ON,
        )

        period = self.make_month(2028, 10, 31)
        employee = self.make_employee(
            basic_salary="9000000", join_date=self.day_in(period, 17),
        )
        self.assign_policy(employee, policy)

        line, _ = self.run_payroll(period=period, employee=employee)

        self.assertEqual(
            self.component(line, "BASIC").amount, Decimal("4500000.00"),
        )


# ----------------------------------------------------------------------
# C & I. Beberapa kebijakan di satu perusahaan, satu run
# ----------------------------------------------------------------------


class MixedRunTest(PolicyTestCase):
    def test_dua_kebijakan_bulanan_di_satu_run(self):
        """
        C. HO memakai hari kalender, Lokal memakai hari kerja — di
        perusahaan yang sama, dan di run yang sama.
        """
        self.set_policy(PayrollProrationMethod.FIXED_30)

        ho = self.make_policy(
            proration_method=PayrollProrationMethod.CALENDAR_DAYS,
        )
        local = self.make_policy(
            proration_method=PayrollProrationMethod.WORKING_DAYS,
        )

        period = self.make_month(2026, 6, 30)

        first = self.make_employee(
            basic_salary="9000000", join_date=self.day_in(period, 16),
        )
        second = self.make_employee(
            basic_salary="9000000", join_date=self.day_in(period, 16),
        )

        self.assign_policy(first, ho)
        self.assign_policy(second, local)

        run = self.make_run(period)
        PayrollRunService.generate_employees(run=run)
        PayrollRunService.calculate(run=run)

        line_ho = self.line_for(run, first)
        line_local = self.line_for(run, second)

        self.assertEqual(
            line_ho.proration_method, PayrollProrationMethod.CALENDAR_DAYS,
        )
        self.assertEqual(
            line_local.proration_method, PayrollProrationMethod.WORKING_DAYS,
        )

        self.assertEqual(line_ho.proration_base_days, Decimal("30.00"))
        self.assertNotEqual(
            line_local.proration_base_days, Decimal("30.00"),
        )

    def test_bulanan_dan_harian_dihitung_bersama_dalam_satu_run(self):
        """
        I. Satu run memproses pegawai bulanan dan harian sekaligus.

        Tidak ada pencabangan berdasarkan nama kelompok, jenis
        kepegawaian, atau lokasi di mana pun — yang membedakan cuma
        kebijakan yang dipilih HR.
        """
        self.set_policy(PayrollProrationMethod.CALENDAR_DAYS)

        daily_policy = self.make_daily_policy()

        period = self.make_month(2027, 6, 30)

        monthly = self.make_employee(basic_salary="9000000")
        daily = self.make_daily_employee(
            policy=daily_policy, daily_rate="200000",
        )

        self.make_present(
            monthly, *[self.day_in(period, day) for day in range(1, 21)],
        )
        self.make_present(
            daily, *[self.day_in(period, day) for day in range(1, 21)],
        )

        run = self.make_run(period)
        PayrollRunService.generate_employees(run=run)
        PayrollRunService.calculate(run=run)

        line_monthly = self.line_for(run, monthly)
        line_daily = self.line_for(run, daily)

        self.assertEqual(line_monthly.pay_basis, PayrollPayBasis.MONTHLY)
        self.assertEqual(line_daily.pay_basis, PayrollPayBasis.DAILY)

        self.assertEqual(
            self.component(line_monthly, "BASIC").amount,
            Decimal("9000000.00"),
        )
        self.assertEqual(
            self.component(line_daily, "BASIC").amount,
            Decimal("4000000.00"),
        )

        self.assertEqual(run.employee_count, 2)


# ----------------------------------------------------------------------
# D. Effective date
# ----------------------------------------------------------------------


class EffectiveDateTest(PolicyTestCase):
    def test_periode_lama_memakai_kebijakan_lama(self):
        """
        D. Assignment berpindah kebijakan mulai bulan berikutnya.
        Periode lama tetap memakai kebijakan lama.

        Yang menjaganya bukan mesin versi kedua: kebijakan dibawa
        `PayrollAssignment`, dan assignment yang berlaku dicari lewat
        rentang efektifnya.
        """
        self.set_policy(PayrollProrationMethod.FIXED_30)

        old_policy = self.make_policy(
            proration_method=PayrollProrationMethod.FIXED_30,
        )
        new_policy = self.make_policy(
            proration_method=PayrollProrationMethod.CALENDAR_DAYS,
        )

        june = self.make_month(2029, 6, 30)
        july = self.make_month(june.start_date.year, 7, 31)

        employee = self.make_employee(basic_salary="9000000")
        self.assign_policy(employee, old_policy)

        # Kebijakan baru berlaku 1 Juli.
        assignment = (
            PayrollAssignment.objects
            .filter(employee=employee, is_current=True)
            .first()
        )
        assignment.is_current = False
        assignment.effective_to = july.start_date - timedelta(days=1)
        assignment.save()

        PayrollAssignment.objects.create(
            employee=employee,
            payroll_group=self.payroll_group,
            currency=self.currency,
            tax_status=self.tax_status,
            basic_salary=Decimal("9000000"),
            allowance_template=self.allowance_template,
            deduction_template=self.deduction_template,
            payroll_policy=new_policy,
            effective_from=july.start_date,
            is_current=True,
        )

        june_line, _ = self.run_payroll(period=june, employee=employee)
        july_line, _ = self.run_payroll(period=july, employee=employee)

        self.assertEqual(june_line.payroll_policy_id, old_policy.pk)
        self.assertEqual(july_line.payroll_policy_id, new_policy.pk)

        self.assertEqual(
            june_line.proration_method, PayrollProrationMethod.FIXED_30,
        )
        self.assertEqual(
            july_line.proration_method,
            PayrollProrationMethod.CALENDAR_DAYS,
        )


# ----------------------------------------------------------------------
# E-H. Pegawai harian
# ----------------------------------------------------------------------


class DailyWageTest(PolicyTestCase):
    def test_hadir_penuh_dibayar_tarif_kali_hari(self):
        """E. Tarif harian x hari yang dibayar."""
        policy = self.make_daily_policy()

        period = self.make_month(2026, 11, 30)
        employee = self.make_daily_employee(
            policy=policy, daily_rate="150000",
        )

        self.make_present(
            employee, *[self.day_in(period, day) for day in range(1, 23)],
        )

        line, _ = self.run_payroll(period=period, employee=employee)

        self.assertEqual(line.pay_basis, PayrollPayBasis.DAILY)
        self.assertEqual(line.paid_days, Decimal("22.00"))
        self.assertEqual(
            self.component(line, "BASIC").amount, Decimal("3300000.00"),
        )

    def test_hari_alpa_tidak_menghasilkan_upah_dan_tidak_dipotong_lagi(self):
        """
        F. Satu hari alpa. Harinya tidak menghasilkan upah, dan **tidak
        ada potongan kedua** untuk hari yang sama.
        """
        self.set_attendance_policy(
            PayrollProrationMethod.FIXED_30, absence=True,
        )

        policy = self.make_daily_policy()

        period = self.make_month(2027, 11, 30)
        employee = self.make_daily_employee(
            policy=policy, daily_rate="150000", basic_salary="4500000",
        )

        self.make_present(
            employee, *[self.day_in(period, day) for day in range(1, 22)],
        )
        self.make_absence(employee, self.day_in(period, 22))

        line, _ = self.run_payroll(period=period, employee=employee)

        self.assertEqual(line.absent_days, Decimal("1.00"))
        self.assertEqual(line.paid_days, Decimal("21.00"))

        self.assertEqual(
            self.component(line, "BASIC").amount, Decimal("3150000.00"),
        )

        # Tidak ada komponen potongan ketidakhadiran sama sekali.
        self.assertNotIn("ABSENT", self.codes(line))
        self.assertEqual(line.absence_deduction, Decimal("0.00"))

    def test_cuti_tidak_dibayar_tidak_menghasilkan_upah_tanpa_potongan_kedua(self):
        """G. Cuti tidak dibayar — sekali, bukan dua kali."""
        self.set_attendance_policy(
            PayrollProrationMethod.FIXED_30, unpaid=True,
        )

        policy = self.make_daily_policy()

        period = self.make_month(2028, 11, 30)
        employee = self.make_daily_employee(
            policy=policy, daily_rate="150000", basic_salary="4500000",
        )

        self.make_present(
            employee, *[self.day_in(period, day) for day in range(1, 21)],
        )
        self.make_leave(
            employee,
            start=self.day_in(period, 21),
            end=self.day_in(period, 22),
            unpaid=True,
        )

        line, _ = self.run_payroll(period=period, employee=employee)

        self.assertEqual(line.unpaid_leave_days, Decimal("2.00"))
        self.assertEqual(line.paid_days, Decimal("20.00"))

        self.assertEqual(
            self.component(line, "BASIC").amount, Decimal("3000000.00"),
        )

        self.assertNotIn("UNPAID-LEAVE", self.codes(line))
        self.assertEqual(line.unpaid_leave_deduction, Decimal("0.00"))

    def test_cuti_dibayar_mengikuti_kebijakan_yang_dipilih(self):
        """
        H. Perlakuan cuti dibayar pegawai harian **dipilih perusahaan**,
        bukan ditebak sistem. Dua kebijakan, dua angka.
        """
        period = self.make_month(2029, 11, 30)

        paying = self.make_daily_policy(pay_paid_leave="yes")
        not_paying = self.make_daily_policy(pay_paid_leave="no")

        first = self.make_daily_employee(
            policy=paying, daily_rate="150000",
        )
        second = self.make_daily_employee(
            policy=not_paying, daily_rate="150000",
        )

        for employee in (first, second):
            self.make_present(
                employee,
                *[self.day_in(period, day) for day in range(1, 21)],
            )
            self.make_leave(
                employee,
                start=self.day_in(period, 21),
                end=self.day_in(period, 22),
                unpaid=False,
            )

        run = self.make_run(period)
        PayrollRunService.generate_employees(run=run)
        PayrollRunService.calculate(run=run)

        line_paying = self.line_for(run, first)
        line_not = self.line_for(run, second)

        self.assertEqual(line_paying.paid_days, Decimal("22.00"))
        self.assertEqual(line_not.paid_days, Decimal("20.00"))

        self.assertEqual(
            self.component(line_paying, "BASIC").amount,
            Decimal("3300000.00"),
        )
        self.assertEqual(
            self.component(line_not, "BASIC").amount,
            Decimal("3000000.00"),
        )

    def test_tarif_diturunkan_dari_gaji_sebulan_dibulatkan_sekali(self):
        """
        Tarif 3.000.000/26 tidak bulat. Yang dibayar harus hasil satu
        pembulatan di akhir, bukan tarif yang dibulatkan lalu dikali.
        """
        policy = self.make_daily_policy(
            daily_rate_method=PayrollDailyRateMethod.FROM_MONTHLY,
            daily_rate_divisor=Decimal("26"),
        )

        period = self.make_month(2026, 12, 31)
        employee = self.make_daily_employee(
            policy=policy, daily_rate="0", basic_salary="3000000",
        )

        self.make_present(
            employee, *[self.day_in(period, day) for day in range(1, 23)],
        )

        line, _ = self.run_payroll(period=period, employee=employee)

        # 3.000.000 x 22 / 26 = 2.538.461,538... → 2.538.461,54
        # Tarif yang dibulatkan lebih dulu (115.384,62) menghasilkan
        # 2.538.461,64 — sepuluh sen yang tidak bisa dijelaskan.
        self.assertEqual(
            self.component(line, "BASIC").amount, Decimal("2538461.54"),
        )

        component = self.component(line, "BASIC")
        self.assertIn("3000000", component.calculation_note)
        self.assertIn("26", component.calculation_note)

    def test_tarif_harian_belum_dikonfigurasi_menghalangi_finalize(self):
        """
        Tarif nol bukan upah nol. Konfigurasi yang belum selesai
        menghasilkan ERROR, bukan orang yang dibayar nol tanpa
        penjelasan.
        """
        policy = self.make_daily_policy()

        period = self.make_month(2027, 12, 31)
        employee = self.make_daily_employee(
            policy=policy, daily_rate="0",
        )

        self.make_present(
            employee, *[self.day_in(period, day) for day in range(1, 11)],
        )

        line, run = self.run_payroll(period=period, employee=employee)

        self.assertEqual(
            self.component(line, "BASIC").amount, Decimal("0.00"),
        )

        # Temuan mesin hitung naik ke ringkasan run dengan kodenya
        # sendiri — bukan menyamar jadi "gaji pokok kosong".
        codes = {item["code"] for item in run.validation_summary["errors"]}
        self.assertIn("daily_rate_missing", codes)

    def test_harian_tidak_diprorata_karena_masuk_di_tengah_periode(self):
        """
        Pegawai harian yang masuk tanggal 16 sudah hanya punya hari
        sejak tanggal 16. Memprorata di atasnya berarti memotong dua
        kali.
        """
        self.set_policy(PayrollProrationMethod.CALENDAR_DAYS)

        policy = self.make_daily_policy()

        period = self.make_month(2028, 12, 31)
        employee = self.make_daily_employee(
            policy=policy,
            daily_rate="150000",
            join_date=self.day_in(period, 16),
        )

        self.make_present(
            employee, *[self.day_in(period, day) for day in range(16, 26)],
        )

        line, _ = self.run_payroll(period=period, employee=employee)

        self.assertEqual(line.proration_factor, Decimal("1.000000"))
        self.assertEqual(line.proration_method, "")
        self.assertEqual(
            self.component(line, "BASIC").amount, Decimal("1500000.00"),
        )


# ----------------------------------------------------------------------
# J. Kekebalan setelah Finalize
# ----------------------------------------------------------------------


class FinalizedImmunityTest(PolicyTestCase):
    def test_mengubah_kebijakan_tidak_menggeser_run_yang_sudah_final(self):
        """
        J. Run yang sudah Finalized kebal terhadap perubahan kebijakan
        maupun perpindahan assignment.
        """
        self.set_policy(PayrollProrationMethod.CALENDAR_DAYS)

        policy = self.make_policy(
            proration_method=PayrollProrationMethod.FIXED_30,
        )

        period = self.make_month(2029, 12, 31)
        employee = self.make_employee(
            basic_salary="9000000", join_date=self.day_in(period, 17),
        )
        self.assign_policy(employee, policy)

        run = self.make_run(period)
        PayrollRunService.generate_employees(run=run)
        PayrollRunService.calculate(run=run)
        PayrollRunService.acknowledge(run=run)

        run.status = PayrollRunStatus.APPROVED
        run.save(update_fields=["status"])

        PayrollRunService.finalize(run=run)

        line = self.line_for(run, employee)
        before = line.net_pay
        payslip = Payslip.objects.filter(run_employee=line).first()
        snapshot_before = payslip.snapshot if payslip else None

        # Kebijakan dirombak sesudah slip terbit.
        policy.proration_method = PayrollProrationMethod.WORKING_DAYS
        policy.save()

        self.assign_policy(employee, None)

        line.refresh_from_db()

        self.assertEqual(line.net_pay, before)
        self.assertEqual(line.payroll_policy_id, policy.pk)
        self.assertEqual(
            line.proration_method, PayrollProrationMethod.FIXED_30,
        )

        if payslip is not None:
            payslip.refresh_from_db()
            self.assertEqual(payslip.snapshot, snapshot_before)

        with self.assertRaises(Exception):
            PayrollRunService.calculate(run=run)


# ----------------------------------------------------------------------
# Resolusi & validasi
# ----------------------------------------------------------------------


class ResolutionOrderTest(PolicyTestCase):
    """
    Urutan resolusinya diuji langsung, tanpa menjalankan run: yang
    dijamin di sini bentuk aturannya, bukan angka rupiahnya.
    """

    def resolve(self, policy):
        return PayrollPolicyService.resolve(
            policy=policy,
            company_proration=PayrollSettingService.resolve_policy(
                company=self.company,
            ),
            company_attendance=(
                PayrollSettingService.resolve_attendance_policy(
                    company=self.company,
                )
            ),
        )

    def test_tanpa_kebijakan_menghasilkan_kebijakan_perusahaan(self):
        self.set_policy(PayrollProrationMethod.WORKING_DAYS)

        resolved = self.resolve(None)

        self.assertEqual(
            resolved.proration.method, PayrollProrationMethod.WORKING_DAYS,
        )
        self.assertEqual(resolved.pay_basis, PayrollPayBasis.MONTHLY)
        self.assertEqual(resolved.label, "Default perusahaan")

    def test_saklar_off_bukan_kekosongan(self):
        self.set_attendance_policy(
            PayrollProrationMethod.FIXED_30, absence=True, unpaid=True,
        )

        policy = self.make_policy(
            deduct_absence=PayrollPolicyToggle.OFF,
            deduct_unpaid_leave=PayrollPolicyToggle.INHERIT,
        )

        resolved = self.resolve(policy)

        self.assertFalse(resolved.attendance.deduct_absence)
        self.assertTrue(resolved.attendance.deduct_unpaid_leave)

    def test_perusahaan_belum_memilih_tetap_terbaca_belum_memilih(self):
        """
        Kebijakan kelompok yang tidak menimpa metodenya tidak boleh
        membuat perusahaan **terlihat** sudah memutuskan.
        """
        self.clear_policy()

        policy = self.make_policy()

        resolved = self.resolve(policy)

        self.assertTrue(resolved.proration.is_default)
        self.assertTrue(resolved.attendance.is_default)

    def test_kebijakan_yang_mengisi_metode_menutup_status_belum_memilih(self):
        self.clear_policy()

        policy = self.make_policy(
            proration_method=PayrollProrationMethod.FIXED_30,
            attendance_deduction_method=PayrollProrationMethod.FIXED_30,
        )

        resolved = self.resolve(policy)

        self.assertFalse(resolved.proration.is_default)
        self.assertFalse(resolved.attendance.is_default)

    def test_label_kebijakan_menyebut_kode_dan_nama(self):
        policy = self.make_policy(code="HO-MONTHLY", name="Head Office")

        resolved = self.resolve(policy)

        self.assertEqual(resolved.label, "HO-MONTHLY - Head Office")


class PolicyModelValidationTest(PolicyTestCase):
    def test_aturan_bulanan_ditolak_pada_kebijakan_harian(self):
        with self.assertRaises(ValidationError) as error:
            self.make_policy(
                pay_basis=PayrollPayBasis.DAILY,
                daily_rate_method=PayrollDailyRateMethod.ASSIGNMENT_RATE,
                pay_paid_leave="no",
                proration_method=PayrollProrationMethod.FIXED_30,
            )

        self.assertIn("proration_method", error.exception.message_dict)

    def test_saklar_bulanan_ditolak_pada_kebijakan_harian(self):
        with self.assertRaises(ValidationError) as error:
            self.make_policy(
                pay_basis=PayrollPayBasis.DAILY,
                daily_rate_method=PayrollDailyRateMethod.ASSIGNMENT_RATE,
                pay_paid_leave="no",
                deduct_absence=PayrollPolicyToggle.OFF,
            )

        self.assertIn("deduct_absence", error.exception.message_dict)

    def test_aturan_harian_ditolak_pada_kebijakan_bulanan(self):
        with self.assertRaises(ValidationError) as error:
            self.make_policy(
                pay_basis=PayrollPayBasis.MONTHLY,
                daily_rate_method=PayrollDailyRateMethod.ASSIGNMENT_RATE,
            )

        self.assertIn("daily_rate_method", error.exception.message_dict)

    def test_pembagi_wajib_kalau_tarif_diturunkan_dari_gaji_sebulan(self):
        with self.assertRaises(ValidationError) as error:
            self.make_policy(
                pay_basis=PayrollPayBasis.DAILY,
                daily_rate_method=PayrollDailyRateMethod.FROM_MONTHLY,
                pay_paid_leave="no",
            )

        self.assertIn("daily_rate_divisor", error.exception.message_dict)

    def test_pembagi_nol_ditolak(self):
        with self.assertRaises(ValidationError) as error:
            self.make_policy(
                pay_basis=PayrollPayBasis.DAILY,
                daily_rate_method=PayrollDailyRateMethod.FROM_MONTHLY,
                daily_rate_divisor=Decimal("0"),
                pay_paid_leave="no",
            )

        self.assertIn("daily_rate_divisor", error.exception.message_dict)


class PolicyValidationFindingTest(PolicyTestCase):
    def run_with_policy(self, policy, *, period=None):
        period = period or self.make_month(2030, 3, 31)
        employee = self.make_daily_employee(
            policy=policy, daily_rate="150000",
        )
        self.make_present(employee, self.day_in(period, 2))

        run = self.make_run(period)
        PayrollRunService.generate_employees(run=run)
        PayrollRunService.calculate(run=run)

        return run

    def error_codes(self, run):
        return {item["code"] for item in run.validation_summary["errors"]}

    def test_harian_tanpa_cara_tarif_ditolak(self):
        policy = PayrollPolicy(
            company=self.company,
            code="DAILY-NORATE",
            name="Daily tanpa tarif",
            pay_basis=PayrollPayBasis.DAILY,
            pay_paid_leave="no",
        )
        policy.save()

        run = self.run_with_policy(policy)

        self.assertIn("daily_rate_method_missing", self.error_codes(run))

    def test_harian_tanpa_keputusan_cuti_dibayar_ditolak(self):
        """
        BUSINESS SUB-DECISION — DAILY PAID LEAVE. Belum ada aturan baku
        di sistem ini, jadi kebijakan yang belum memilih **ditolak**,
        bukan dihitung dengan bawaan.
        """
        policy = PayrollPolicy(
            company=self.company,
            code="DAILY-NOLEAVE",
            name="Daily tanpa keputusan cuti",
            pay_basis=PayrollPayBasis.DAILY,
            daily_rate_method=PayrollDailyRateMethod.ASSIGNMENT_RATE,
        )
        policy.save()

        run = self.run_with_policy(policy)

        self.assertIn("daily_paid_leave_undecided", self.error_codes(run))

    def test_kebijakan_milik_perusahaan_lain_ditolak(self):
        from apps.administration.models import Company

        type(self)._counter += 1

        other = Company.objects.create(
            code=f"OTH{type(self)._counter}", name="Other Company",
        )

        policy = self.make_daily_policy(company=other)

        run = self.run_with_policy(policy)

        self.assertIn("policy_company_mismatch", self.error_codes(run))


# ----------------------------------------------------------------------
# Hotfix — Employee Action tidak boleh membuang kebijakan
# ----------------------------------------------------------------------


class EmployeeActionCopyTest(PolicyTestCase):
    """
    Kenaikan gaji lewat Employee Action menerbitkan **baris payroll
    baru**, dan kolom yang tidak diusulkan action itu disalin dari baris
    berjalan lewat daftar nama yang ditulis tangan.

    Daftar itu sempat tidak memuat `payroll_policy` dan `daily_rate`,
    dan kegagalannya senyap: tidak ada error, tidak ada temuan — cuma
    pegawai harian yang bulan depan dihitung bulanan dengan tarif harian
    yang hilang. Kelas ini yang menahannya kembali.
    """

    def make_salary_change(self, employee, *, effective, proposed):
        from apps.hr.models import (
            EmployeeAction,
            EmployeeActionStatus,
            EmployeeActionType,
        )

        type(self)._counter += 1

        return EmployeeAction.objects.create(
            employee=employee,
            action_type=EmployeeActionType.SALARY_CHANGE,
            status=EmployeeActionStatus.APPROVED,
            effective_date=effective,
            document_number=f"ACT-{type(self)._counter}",
            reason="Kenaikan gaji berkala",
            company=self.company,
            proposed_basic_salary=Decimal(proposed),
        )

    def apply_action(self, action):
        from apps.hr.api.employee_action.services import EmployeeActionService

        return EmployeeActionService.apply(instance=action)

    def assignments_of(self, employee):
        return list(
            PayrollAssignment.objects
            .filter(employee=employee, is_deleted=False)
            .order_by("effective_from")
        )

    # ------------------------------------------------------------------

    def test_kenaikan_gaji_mempertahankan_kebijakan_dan_tarif_harian(self):
        """
        Baris baru membawa kebijakan **dan** tarif hariannya, sementara
        kenaikan yang diminta tetap diterapkan.
        """
        policy = self.make_daily_policy()

        employee = self.make_daily_employee(
            policy=policy, daily_rate="200000", basic_salary="3000000",
        )

        before = self.assignments_of(employee)[-1]
        effective = date(before.effective_from.year + 1, 7, 1)

        action = self.make_salary_change(
            employee, effective=effective, proposed="3600000",
        )
        self.apply_action(action)

        rows = self.assignments_of(employee)
        self.assertEqual(len(rows), 2)

        old, new = rows

        # Yang diminta action memang berubah.
        self.assertEqual(new.basic_salary, Decimal("3600000.00"))

        # Yang **tidak** diminta action tidak boleh hilang.
        self.assertEqual(new.payroll_policy_id, policy.pk)
        self.assertEqual(new.daily_rate, Decimal("200000.00"))

        # Baris lama ditutup mengikuti semantik existing, apa adanya.
        old.refresh_from_db()
        self.assertFalse(old.is_current)
        self.assertEqual(old.effective_to, effective)
        self.assertTrue(new.is_current)
        self.assertEqual(new.effective_from, effective)

    def test_periode_sesudah_kenaikan_tetap_dihitung_harian(self):
        """
        Buktinya bukan di kolom, melainkan di uangnya: periode sesudah
        action tetap dibayar `tarif x hari`, bukan gaji sebulan.
        """
        policy = self.make_daily_policy()

        employee = self.make_daily_employee(
            policy=policy, daily_rate="200000", basic_salary="3000000",
        )

        june = self.make_month(2031, 6, 30)
        july = self.make_month(june.start_date.year, 7, 31)

        action = self.make_salary_change(
            employee, effective=july.start_date, proposed="3600000",
        )
        self.apply_action(action)

        self.make_present(
            employee, *[self.day_in(july, day) for day in range(1, 22)],
        )

        line, _ = self.run_payroll(period=july, employee=employee)

        self.assertEqual(line.payroll_policy_id, policy.pk)
        self.assertEqual(line.pay_basis, PayrollPayBasis.DAILY)
        self.assertEqual(line.daily_rate, Decimal("200000.000000"))
        self.assertEqual(line.paid_days, Decimal("21.00"))

        # 21 x 200.000 — bukan 3.600.000 sebulan.
        self.assertEqual(
            self.component(line, "BASIC").amount, Decimal("4200000.00"),
        )

        # Gaji sebulan yang baru tetap tersalin, hanya saja tidak
        # dipakai membentuk upah harian.
        self.assertEqual(line.basic_salary, Decimal("3600000.00"))

    def test_kenaikan_gaji_pada_kebijakan_bulanan_tidak_berubah(self):
        """
        Regresi sisi sebaliknya: kebijakan bulanan ikut tersalin, dan
        tarif harian yang memang kosong tetap kosong.
        """
        self.set_policy(PayrollProrationMethod.CALENDAR_DAYS)

        policy = self.make_policy(
            proration_method=PayrollProrationMethod.FIXED_30,
        )

        employee = self.make_employee(basic_salary="9000000")
        self.assign_policy(employee, policy)

        before = self.assignments_of(employee)[-1]
        effective = date(before.effective_from.year + 1, 7, 1)

        action = self.make_salary_change(
            employee, effective=effective, proposed="10000000",
        )
        self.apply_action(action)

        rows = self.assignments_of(employee)
        self.assertEqual(len(rows), 2)

        new = rows[-1]

        self.assertEqual(new.basic_salary, Decimal("10000000.00"))
        self.assertEqual(new.payroll_policy_id, policy.pk)
        self.assertIsNone(new.daily_rate)

    def test_pegawai_tanpa_kebijakan_tetap_tanpa_kebijakan(self):
        """
        Menyalin tidak boleh berarti mengarang: pegawai yang memang
        mengikuti default perusahaan tetap tanpa kebijakan sesudah
        kenaikan gaji.

        Test ini juga penjaga cacat kedua yang ditemukan bersama
        hotfix ini, dan cacat itu **tidak** ada hubungannya dengan
        Payroll Policy: baris baru dulu disimpan selagi baris lama
        masih `is_current`, jadi
        `uniq_current_employee_payroll_assignment` menolaknya. Pegawai
        di sini sengaja tanpa kebijakan dan tanpa tarif harian — kalau
        urutannya kembali terbalik, yang gagal adalah kenaikan gaji
        pegawai bulanan biasa.
        """
        employee = self.make_employee(basic_salary="9000000")

        before = self.assignments_of(employee)[-1]
        effective = date(before.effective_from.year + 1, 7, 1)

        action = self.make_salary_change(
            employee, effective=effective, proposed="9500000",
        )
        self.apply_action(action)

        rows = self.assignments_of(employee)
        self.assertEqual(len(rows), 2)

        old, new = rows

        self.assertEqual(new.basic_salary, Decimal("9500000.00"))
        self.assertIsNone(new.payroll_policy_id)
        self.assertIsNone(new.daily_rate)

        # Tepat satu baris berjalan, dan yang lama tertutup.
        self.assertFalse(old.is_current)
        self.assertTrue(new.is_current)
        self.assertEqual(
            PayrollAssignment.objects
            .filter(employee=employee, is_current=True, is_deleted=False)
            .count(),
            1,
        )
