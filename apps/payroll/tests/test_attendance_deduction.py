"""
Business Decision #2 — potongan absen dan cuti tidak dibayar.

Pertanyaan yang diuji di sini bukan "berapa hak gaji orang yang belum
sebulan bekerja" — itu Business Decision #1 dan sudah punya berkasnya
sendiri. Yang diuji di sini: **berapa yang hilang dari hak itu karena
ia tidak masuk.**

Dua lapisan yang sengaja tidak dicampur, dan sebagian besar berkas ini
ada untuk membuktikan bahwa keduanya memang tidak saling menumpang:
pegawai yang masuk tanggal 16 lalu alpa sehari tidak boleh diprorata
dua kali, dan satu tanggal yang berstatus alpa sekaligus cuti tidak
dibayar tidak boleh dipotong dua kali.

Fixture-nya dipakai ulang dari `test_proration`, yang dipakai ulang
dari `test_payroll_flow`, supaya keadaan awalnya persis sama dengan
seluruh test payroll lainnya.
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from apps.administration.models import Holiday, LeaveType, WorkCalendar
from apps.hr.models import EmployeeLeave
from apps.hr.models.attendance import AttendanceStatus, EmployeeAttendance
from apps.hr.models.leave import LeaveStatus
from apps.payroll.models import (
    EARNINGS_REDUCTION_BASES,
    PayrollRunEmployee,
    DeductionTemplate,
    DeductionTemplateLine,
    PayrollBasis,
    PayrollComponentType,
    PayrollLeaveRule,
    PayrollProrationMethod,
    PayrollRunEmployeeStatus,
    PayrollRunStatus,
    PayrollSetting,
    Payslip,
)
from apps.payroll.services import (
    PayrollRunService,
    PayslipService,
    PayrollSettingService,
    PayrollSourceService,
)

from .test_proration import ProrationTestCase


class AttendanceDeductionTestCase(ProrationTestCase):
    """
    Satu pegawai, satu periode, satu potongan yang harus cocok sampai
    rupiah.
    """

    # ------------------------------------------------------------------
    # Kebijakan
    # ------------------------------------------------------------------

    def set_attendance_policy(
        self,
        method="",
        *,
        absence=True,
        unpaid=True,
    ):
        """
        Kebijakan potongan saja — kebijakan prorata tidak ikut tersentuh.

        Ditulis begini, bukan lewat `update_or_create(defaults=...)`,
        supaya test yang cuma mengatur potongan tidak diam-diam
        mengembalikan metode prorata ke bawaan.
        """
        row, _ = PayrollSetting.objects.get_or_create(
            company=self.company,
            defaults={"is_active": True},
        )

        row.attendance_deduction_method = method
        row.deduct_absence = absence
        row.deduct_unpaid_leave = unpaid
        row.is_active = True
        row.save()

        return row

    def clear_policy(self):
        """Perusahaan yang belum memutuskan apa pun."""
        PayrollSetting.objects.filter(company=self.company).delete()

    # ------------------------------------------------------------------
    # Data sumber
    # ------------------------------------------------------------------

    def make_leave(self, employee, *, start, end, unpaid=True, days=None):
        type(self)._counter += 1

        leave_type = LeaveType.objects.create(
            code=f"LV{type(self)._counter}",
            name="Cuti Tanpa Gaji" if unpaid else "Cuti Tahunan",
        )

        PayrollLeaveRule.objects.create(
            leave_type=leave_type, is_unpaid=unpaid,
        )

        total = (
            Decimal(days)
            if days is not None
            else Decimal((end - start).days + 1)
        )

        return EmployeeLeave.objects.create(
            employee=employee,
            company=self.company,
            leave_type=leave_type,
            start_date=start,
            end_date=end,
            total_days=total,
            status=LeaveStatus.APPROVED,
        )

    def make_absence(self, employee, *dates):
        for work_date in dates:
            EmployeeAttendance.objects.create(
                employee=employee,
                company=self.company,
                work_date=work_date,
                status=AttendanceStatus.ABSENT,
            )

    def make_present(self, employee, *dates):
        for work_date in dates:
            EmployeeAttendance.objects.create(
                employee=employee,
                company=self.company,
                work_date=work_date,
                status=AttendanceStatus.PRESENT,
            )

    # ------------------------------------------------------------------
    # Menjalankan
    # ------------------------------------------------------------------

    def run_payroll(self, *, period, employee):
        run = self.make_run(period)

        PayrollRunService.generate_employees(run=run)
        PayrollRunService.calculate(run=run)

        return self.line_for(run, employee), run

    def codes(self, line):
        return {component.code for component in line.components.all()}


# ----------------------------------------------------------------------
# A. Cuti dibayar
# ----------------------------------------------------------------------


class PaidLeaveTest(AttendanceDeductionTestCase):
    def test_cuti_dibayar_tercatat_tapi_tidak_memotong(self):
        """
        A. Cuti tahunan yang disetujui tetap tercatat sebagai hari cuti
        dan **tidak** mengurangi gaji sepeser pun.
        """
        self.set_attendance_policy(PayrollProrationMethod.FIXED_30)

        period = self.make_month(2026, 9, 30)
        employee = self.make_employee(basic_salary="9000000")

        self.make_leave(
            employee,
            start=self.day_in(period, 10),
            end=self.day_in(period, 10),
            unpaid=False,
        )

        line, _ = self.run_payroll(period=period, employee=employee)

        self.assertEqual(line.leave_days, Decimal("1.00"))
        self.assertEqual(line.unpaid_leave_days, Decimal("0.00"))
        self.assertEqual(line.absent_days, Decimal("0.00"))

        self.assertEqual(line.absence_deduction, Decimal("0.00"))
        self.assertEqual(line.unpaid_leave_deduction, Decimal("0.00"))

        self.assertNotIn("UNPAID-LEAVE", self.codes(line))
        self.assertNotIn("ABSENT", self.codes(line))

        self.assertEqual(
            self.component(line, "BASIC").amount, Decimal("9000000.00"),
        )

    def test_cuti_dibayar_tidak_boleh_dihitung_sebagai_alpa(self):
        """
        Jenis cuti yang tidak punya `PayrollLeaveRule` sama sekali
        adalah cuti **dibayar**. Itu perilaku lama, dan tenant yang
        belum mengisi tabel aturan tidak boleh kehilangan sepeser pun
        hanya karena tabel itu lahir kosong.
        """
        self.set_attendance_policy(PayrollProrationMethod.FIXED_30)

        period = self.make_month(2027, 9, 30)
        employee = self.make_employee(basic_salary="9000000")

        type(self)._counter += 1

        leave_type = LeaveType.objects.create(
            code=f"NORULE{type(self)._counter}", name="Cuti Tanpa Aturan",
        )

        EmployeeLeave.objects.create(
            employee=employee,
            company=self.company,
            leave_type=leave_type,
            start_date=self.day_in(period, 5),
            end_date=self.day_in(period, 6),
            total_days=Decimal("2"),
            status=LeaveStatus.APPROVED,
        )

        line, _ = self.run_payroll(period=period, employee=employee)

        self.assertEqual(line.leave_days, Decimal("2.00"))
        self.assertEqual(line.unpaid_leave_days, Decimal("0.00"))
        self.assertEqual(line.unpaid_leave_deduction, Decimal("0.00"))


# ----------------------------------------------------------------------
# B & G. Cuti tidak dibayar
# ----------------------------------------------------------------------


class UnpaidLeaveTest(AttendanceDeductionTestCase):
    def test_dua_hari_cuti_tidak_dibayar_dipotong_fixed_30(self):
        """B + G. Angkanya diperiksa sampai rupiah."""
        self.set_attendance_policy(PayrollProrationMethod.FIXED_30)

        period = self.make_month(2026, 9, 30)
        employee = self.make_employee(basic_salary="9000000")

        self.make_leave(
            employee,
            start=self.day_in(period, 10),
            end=self.day_in(period, 11),
        )

        line, _ = self.run_payroll(period=period, employee=employee)

        # 9.000.000 x 2 / 30 = 600.000 tepat.
        self.assertEqual(line.unpaid_leave_days, Decimal("2.00"))
        self.assertEqual(line.deduction_base_days, Decimal("30.00"))
        self.assertEqual(
            line.attendance_deduction_method,
            PayrollProrationMethod.FIXED_30,
        )
        self.assertEqual(line.unpaid_leave_deduction, Decimal("600000.00"))

        # Bentuk barisnya **tidak berubah** oleh keputusan #2: tetap
        # potongan, tetap besaran positif. Yang berubah cara agregasi
        # membacanya, dan itu diperiksa `EarningsReductionTest`.
        component = self.component(line, "UNPAID-LEAVE")

        self.assertEqual(component.amount, Decimal("600000.00"))
        self.assertEqual(
            component.component_type, PayrollComponentType.DEDUCTION,
        )
        self.assertEqual(component.quantity, Decimal("2.0000"))

        self.assertEqual(line.absence_deduction, Decimal("0.00"))

    def test_pembulatan_hanya_sekali(self):
        """
        7.500.000 / 30 = 250.000 tepat, jadi kasus ini tidak
        membuktikan apa pun sendirian. Yang membuktikan: 10.000.000 / 30
        = 333.333,333… — nilai sehari yang dibulatkan lebih dulu lalu
        dikalikan tiga menghasilkan 999.999,99, dan satu rupiah itu
        tidak bisa dijelaskan kepada siapa pun.
        """
        self.set_attendance_policy(PayrollProrationMethod.FIXED_30)

        period = self.make_month(2028, 9, 30)
        employee = self.make_employee(basic_salary="10000000")

        self.make_leave(
            employee,
            start=self.day_in(period, 10),
            end=self.day_in(period, 12),
        )

        line, _ = self.run_payroll(period=period, employee=employee)

        self.assertEqual(
            line.unpaid_leave_deduction, Decimal("1000000.00"),
        )

    def test_cuti_melintasi_batas_periode_dipotong_sebagiannya_saja(self):
        """
        Cuti yang dimulai sebelum periode ini tidak boleh memotong
        penuh dua kali — sekali di bulan lalu, sekali lagi di sini.
        """
        self.set_attendance_policy(PayrollProrationMethod.FIXED_30)

        period = self.make_month(2029, 9, 30)
        employee = self.make_employee(basic_salary="9000000")

        # Empat hari beruntun: dua di bulan lalu, dua di periode ini.
        # `total_days` harus konsisten dengan rentangnya — cuti "5 hari"
        # yang membentang 4 tanggal adalah data yang mustahil, dan
        # pembagiannya per hari irisan lalu menghasilkan 2,5.
        self.make_leave(
            employee,
            start=period.start_date - timedelta(days=2),
            end=self.day_in(period, 2),
            days=Decimal("4"),
        )

        line, _ = self.run_payroll(period=period, employee=employee)

        # 4 hari cuti, 2 di antaranya jatuh di periode ini.
        self.assertEqual(line.unpaid_leave_days, Decimal("2.00"))
        self.assertEqual(line.unpaid_leave_deduction, Decimal("600000.00"))


# ----------------------------------------------------------------------
# C. Alpa
# ----------------------------------------------------------------------


class AbsenceTest(AttendanceDeductionTestCase):
    def test_dua_hari_alpa_dipotong(self):
        self.set_attendance_policy(PayrollProrationMethod.FIXED_30)

        period = self.make_month(2026, 9, 30)
        employee = self.make_employee(basic_salary="9000000")

        self.make_absence(
            employee,
            self.day_in(period, 8),
            self.day_in(period, 9),
        )

        line, _ = self.run_payroll(period=period, employee=employee)

        self.assertEqual(line.absent_days, Decimal("2.00"))
        self.assertEqual(line.absence_deduction, Decimal("600000.00"))

        component = self.component(line, "ABSENT")

        self.assertEqual(component.amount, Decimal("600000.00"))
        self.assertEqual(
            component.component_type, PayrollComponentType.DEDUCTION,
        )
        self.assertEqual(component.quantity, Decimal("2.0000"))

        self.assertEqual(line.unpaid_leave_deduction, Decimal("0.00"))

    def test_alpa_dan_cuti_tidak_dibayar_jadi_dua_komponen_terpisah(self):
        """
        Digabung jadi satu angka "potongan ketidakhadiran", pegawai yang
        membantah satu hari alpa harus membantah seluruhnya, dan HR
        tidak punya cara menunjukkan bagian mana yang datang dari
        dokumen cuti.
        """
        self.set_attendance_policy(PayrollProrationMethod.FIXED_30)

        period = self.make_month(2030, 9, 30)
        employee = self.make_employee(basic_salary="9000000")

        self.make_absence(employee, self.day_in(period, 8))
        self.make_leave(
            employee,
            start=self.day_in(period, 20),
            end=self.day_in(period, 21),
        )

        line, _ = self.run_payroll(period=period, employee=employee)

        self.assertEqual(line.absence_deduction, Decimal("300000.00"))
        self.assertEqual(line.unpaid_leave_deduction, Decimal("600000.00"))

        codes = self.codes(line)
        self.assertIn("ABSENT", codes)
        self.assertIn("UNPAID-LEAVE", codes)


# ----------------------------------------------------------------------
# D. Tumpang tindih
# ----------------------------------------------------------------------


class OverlapTest(AttendanceDeductionTestCase):
    """
    Ini yang paling mudah dikerjakan salah, dan paling mahal kalau
    salah: pegawai yang cutinya disetujui tetap meninggalkan baris
    absensi berstatus alpa, karena ia memang tidak menempelkan jari.
    """

    def test_tanggal_yang_sama_hanya_dipotong_sekali(self):
        self.set_attendance_policy(PayrollProrationMethod.FIXED_30)

        period = self.make_month(2031, 9, 30)
        employee = self.make_employee(basic_salary="9000000")

        overlap = [self.day_in(period, 10), self.day_in(period, 11)]

        self.make_leave(employee, start=overlap[0], end=overlap[1])
        self.make_absence(employee, *overlap)

        line, _ = self.run_payroll(period=period, employee=employee)

        self.assertEqual(line.unpaid_leave_days, Decimal("2.00"))
        self.assertEqual(line.absent_days, Decimal("0.00"))

        self.assertEqual(line.unpaid_leave_deduction, Decimal("600000.00"))
        self.assertEqual(line.absence_deduction, Decimal("0.00"))

        self.assertNotIn("ABSENT", self.codes(line))

    def test_cuti_dibayar_juga_mengalahkan_alpa_mentah(self):
        """
        Dokumen cuti adalah keputusan orang; baris absensi cuma jejak
        alat. Pegawai yang cuti tahunannya disetujui tidak boleh
        dipotong hanya karena mesin absensi tidak tahu.
        """
        self.set_attendance_policy(PayrollProrationMethod.FIXED_30)

        period = self.make_month(2032, 9, 30)
        employee = self.make_employee(basic_salary="9000000")

        day = self.day_in(period, 10)

        self.make_leave(employee, start=day, end=day, unpaid=False)
        self.make_absence(employee, day)

        line, _ = self.run_payroll(period=period, employee=employee)

        self.assertEqual(line.absent_days, Decimal("0.00"))
        self.assertEqual(line.absence_deduction, Decimal("0.00"))
        self.assertEqual(line.unpaid_leave_deduction, Decimal("0.00"))

    def test_alpa_di_luar_tanggal_cuti_tetap_dipotong(self):
        """
        Presedensinya per tanggal, bukan per pegawai. Punya cuti bukan
        surat sakti untuk seluruh bulan.
        """
        self.set_attendance_policy(PayrollProrationMethod.FIXED_30)

        period = self.make_month(2033, 9, 30)
        employee = self.make_employee(basic_salary="9000000")

        self.make_leave(
            employee,
            start=self.day_in(period, 10),
            end=self.day_in(period, 10),
        )
        self.make_absence(
            employee,
            self.day_in(period, 10),
            self.day_in(period, 20),
        )

        line, _ = self.run_payroll(period=period, employee=employee)

        self.assertEqual(line.absent_days, Decimal("1.00"))
        self.assertEqual(line.absence_deduction, Decimal("300000.00"))
        self.assertEqual(line.unpaid_leave_deduction, Decimal("300000.00"))

    def test_adapter_menghitung_tanggal_yang_ditutup_cuti(self):
        """
        Angkanya harus bisa dilihat, bukan cuma disimpulkan dari
        hasil akhir yang kebetulan cocok.
        """
        period = self.make_month(2034, 9, 30)
        employee = self.make_employee(basic_salary="9000000")

        day = self.day_in(period, 12)

        self.make_leave(employee, start=day, end=day)
        self.make_absence(employee, day)

        facts = PayrollSourceService.collect(
            employee=employee,
            start_date=period.start_date,
            end_date=period.end_date,
        )

        self.assertEqual(facts.absence_covered_by_leave, 1)
        self.assertEqual(facts.absent_days, Decimal("0.00"))
        self.assertEqual(facts.unpaid_leave_days, Decimal("1"))
        self.assertEqual(facts.paid_leave_days, Decimal("0"))


# ----------------------------------------------------------------------
# E & F. Batas masa kerja
# ----------------------------------------------------------------------


class EmploymentRangeTest(AttendanceDeductionTestCase):
    def test_alpa_sebelum_tanggal_masuk_tidak_dipotong(self):
        """
        E. Prorata gaji pokok dan potongan alpa berjalan bersamaan,
        dan tidak boleh saling menumpang.
        """
        self.set_attendance_policy(PayrollProrationMethod.FIXED_30)
        self.set_policy(PayrollProrationMethod.FIXED_30)

        period = self.make_month(2035, 9, 30)
        employee = self.make_employee(
            basic_salary="9000000",
            join_date=self.day_in(period, 16),
        )

        self.make_absence(
            employee,
            self.day_in(period, 5),    # sebelum masuk
            self.day_in(period, 20),   # sesudah masuk
        )

        line, _ = self.run_payroll(period=period, employee=employee)

        # Hak gaji pokoknya setengah bulan.
        self.assertEqual(
            self.component(line, "BASIC").amount, Decimal("4500000.00"),
        )

        # Yang dipotong hanya satu hari, dan pembaginya periode penuh —
        # bukan 4.500.000 / 15, yang akan memotong dua kali lipat
        # karena prorata sudah diperhitungkan sekali di gaji pokok.
        self.assertEqual(line.absent_days, Decimal("1.00"))
        self.assertEqual(line.deduction_base_days, Decimal("30.00"))
        self.assertEqual(line.absence_deduction, Decimal("300000.00"))

    def test_cuti_tidak_dibayar_sebelum_masuk_tidak_dihitung(self):
        self.set_attendance_policy(PayrollProrationMethod.FIXED_30)
        self.set_policy(PayrollProrationMethod.FIXED_30)

        period = self.make_month(2036, 9, 30)
        employee = self.make_employee(
            basic_salary="9000000",
            join_date=self.day_in(period, 16),
        )

        self.make_leave(
            employee,
            start=self.day_in(period, 5),
            end=self.day_in(period, 6),
        )

        line, _ = self.run_payroll(period=period, employee=employee)

        self.assertEqual(line.unpaid_leave_days, Decimal("0.00"))
        self.assertEqual(line.unpaid_leave_deduction, Decimal("0.00"))

    def test_alpa_sesudah_tanggal_berhenti_tidak_dipotong(self):
        """F. Tanggal berhenti inclusive, mengikuti Employment."""
        self.set_attendance_policy(PayrollProrationMethod.FIXED_30)
        self.set_policy(PayrollProrationMethod.FIXED_30)

        period = self.make_month(2037, 9, 30)
        employee = self.make_employee(
            basic_salary="9000000",
            termination_date=self.day_in(period, 20),
        )

        self.make_absence(
            employee,
            self.day_in(period, 20),   # hari terakhirnya, masih dihitung
            self.day_in(period, 25),   # sesudah berhenti
        )

        line, _ = self.run_payroll(period=period, employee=employee)

        self.assertEqual(line.absent_days, Decimal("1.00"))
        self.assertEqual(line.absence_deduction, Decimal("300000.00"))

    def test_saklar_prorata_mati_tidak_membuka_alpa_sebelum_masuk(self):
        """
        Perusahaan yang memilih membayar pegawai barunya sebulan penuh
        tetap tidak boleh memotongnya karena alpa di tanggal ia belum
        ada di sini. "Bayar penuh" bukan "anggap sudah bekerja sejak
        tanggal 1".
        """
        self.set_policy(
            PayrollProrationMethod.FIXED_30, on_join=False,
        )
        self.set_attendance_policy(PayrollProrationMethod.FIXED_30)

        period = self.make_month(2038, 9, 30)
        employee = self.make_employee(
            basic_salary="9000000",
            join_date=self.day_in(period, 16),
        )

        self.make_absence(employee, self.day_in(period, 5))

        line, _ = self.run_payroll(period=period, employee=employee)

        self.assertEqual(
            self.component(line, "BASIC").amount, Decimal("9000000.00"),
        )
        self.assertEqual(line.absent_days, Decimal("0.00"))
        self.assertEqual(line.absence_deduction, Decimal("0.00"))


# ----------------------------------------------------------------------
# H. Calendar days
# ----------------------------------------------------------------------


class CalendarDaysMethodTest(AttendanceDeductionTestCase):
    """
    H. Pembaginya berubah mengikuti panjang bulan, dan itu memang yang
    dicari sebagian perusahaan: sehari di Februari lebih mahal daripada
    sehari di Januari.
    """

    CASES = [
        (1, 31, Decimal("580645.16")),
        (9, 30, Decimal("600000.00")),
        (2, 29, Decimal("620689.66")),
        (2, 28, Decimal("642857.14")),
    ]

    def test_pembagi_mengikuti_panjang_bulan(self):
        self.set_attendance_policy(PayrollProrationMethod.CALENDAR_DAYS)

        for month, last_day, expected in self.CASES:
            with self.subTest(month=month, days=last_day):
                period = self.make_month(2040, month, last_day)
                employee = self.make_employee(basic_salary="9000000")

                self.make_leave(
                    employee,
                    start=self.day_in(period, 10),
                    end=self.day_in(period, 11),
                )

                line, _ = self.run_payroll(
                    period=period, employee=employee,
                )

                self.assertEqual(
                    line.deduction_base_days, Decimal(last_day),
                )
                self.assertEqual(line.unpaid_leave_deduction, expected)


# ----------------------------------------------------------------------
# I. Working days
# ----------------------------------------------------------------------


class WorkingDaysMethodTest(AttendanceDeductionTestCase):
    """
    I. Pembaginya hari kerja pegawai itu sendiri, dibaca dari kalender
    kerja dan hari libur yang sudah ada — sumber yang sama dengan
    Business Decision #1, dan sumber yang sama yang memotong saldo cuti.

    Tidak ada Senin-Jumat yang ditanam di Payroll. Yang di bawah ini
    adalah `WorkCalendar` sungguhan yang dibuat test-nya sendiri, dan
    hari liburnya `Holiday` sungguhan.
    """

    def setUp(self):
        super().setUp()

        type(self)._counter += 1

        self.calendar = WorkCalendar.objects.create(
            company=self.company,
            code=f"AD-{type(self)._counter}",
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

    def test_pembagi_adalah_hari_kerja_pegawai(self):
        self.set_attendance_policy(PayrollProrationMethod.WORKING_DAYS)

        period = self.make_month(2070, 9, 30)

        self.assertEqual(period.start_date.year, 2070)

        employee = self.make_employee(basic_salary="8800000")
        self.attach(employee)

        # 5 September 2070 jatuh hari Jumat.
        self.make_absence(employee, date(2070, 9, 5))

        line, _ = self.run_payroll(period=period, employee=employee)

        # September 2070: 22 hari kerja Senin-Jumat.
        self.assertEqual(line.deduction_base_days, Decimal("22.00"))
        self.assertEqual(line.absent_days, Decimal("1.00"))
        self.assertEqual(line.absence_deduction, Decimal("400000.00"))

    def test_hari_libur_mengurangi_pembagi_dan_menaikkan_potongan(self):
        """
        Hari libur nasional bukan hari kerja. Kalau `Holiday` tidak
        dibaca, pembaginya terlalu besar dan setiap potongan terlalu
        kecil — kesalahan yang tidak pernah dilaporkan siapa pun karena
        yang dirugikan perusahaan, bukan pegawainya.
        """
        self.set_attendance_policy(PayrollProrationMethod.WORKING_DAYS)

        period = self.make_month(2071, 9, 30)

        self.assertEqual(period.start_date.year, 2071)

        # 21 September 2071 jatuh hari Senin.
        Holiday.objects.create(
            company=self.company,
            date=date(2071, 9, 21),
            code=f"HOLAD-{type(self)._counter}",
            name="Libur Uji",
            is_national=True,
        )

        employee = self.make_employee(basic_salary="8400000")
        self.attach(employee)

        # 3 September 2071 jatuh hari Kamis.
        self.make_absence(employee, date(2071, 9, 3))

        line, _ = self.run_payroll(period=period, employee=employee)

        # 22 hari kerja - 1 hari libur = 21.
        self.assertEqual(line.deduction_base_days, Decimal("21.00"))
        self.assertEqual(line.absence_deduction, Decimal("400000.00"))


# ----------------------------------------------------------------------
# Saklar kebijakan
# ----------------------------------------------------------------------


class PolicySwitchTest(AttendanceDeductionTestCase):
    def test_deduct_absence_mati_mencatat_hari_tanpa_memotong(self):
        """
        "Tidak dipotong" dan "tidak pernah terjadi" harus tetap bisa
        dibedakan. Harinya tetap tercatat di barisnya.
        """
        self.set_attendance_policy(
            PayrollProrationMethod.FIXED_30, absence=False,
        )

        period = self.make_month(2041, 9, 30)
        employee = self.make_employee(basic_salary="9000000")

        self.make_absence(
            employee, self.day_in(period, 8), self.day_in(period, 9),
        )

        line, _ = self.run_payroll(period=period, employee=employee)

        self.assertEqual(line.absent_days, Decimal("2.00"))
        self.assertEqual(line.absence_deduction, Decimal("0.00"))
        self.assertNotIn("ABSENT", self.codes(line))

    def test_deduct_unpaid_leave_mati_mencatat_hari_tanpa_memotong(self):
        self.set_attendance_policy(
            PayrollProrationMethod.FIXED_30, unpaid=False,
        )

        period = self.make_month(2042, 9, 30)
        employee = self.make_employee(basic_salary="9000000")

        self.make_leave(
            employee,
            start=self.day_in(period, 10),
            end=self.day_in(period, 11),
        )

        line, _ = self.run_payroll(period=period, employee=employee)

        self.assertEqual(line.unpaid_leave_days, Decimal("2.00"))
        self.assertEqual(line.unpaid_leave_deduction, Decimal("0.00"))
        self.assertNotIn("UNPAID-LEAVE", self.codes(line))

    def test_dua_saklar_mati_sekaligus(self):
        self.set_attendance_policy(
            PayrollProrationMethod.FIXED_30,
            absence=False,
            unpaid=False,
        )

        period = self.make_month(2043, 9, 30)
        employee = self.make_employee(basic_salary="9000000")

        self.make_absence(employee, self.day_in(period, 8))
        self.make_leave(
            employee,
            start=self.day_in(period, 20),
            end=self.day_in(period, 20),
        )

        line, _ = self.run_payroll(period=period, employee=employee)

        self.assertEqual(
            self.component(line, "BASIC").amount, Decimal("9000000.00"),
        )

        # Yang nol potongan **ketidakhadiran**-nya. BPJS dan iuran lain
        # dari Deduction Template tetap jalan — mematikan potongan
        # absen bukan mematikan payroll.
        self.assertEqual(line.absence_deduction, Decimal("0.00"))
        self.assertEqual(line.unpaid_leave_deduction, Decimal("0.00"))

        codes = self.codes(line)
        self.assertNotIn("ABSENT", codes)
        self.assertNotIn("UNPAID-LEAVE", codes)

        # Harinya tetap tercatat.
        self.assertEqual(line.absent_days, Decimal("1.00"))
        self.assertEqual(line.unpaid_leave_days, Decimal("1.00"))


class PolicyResolutionTest(AttendanceDeductionTestCase):
    def test_perusahaan_tanpa_baris_memakai_pembagi_periode(self):
        """
        Perilaku sebelum kebijakan ini ada, dipertahankan apa adanya:
        pembaginya `PayrollPeriod.divisor_days`. Menambah layar
        konfigurasi tidak boleh menggeser satu rupiah pun pada payroll
        yang sudah berjalan.
        """
        self.clear_policy()

        policy = PayrollSettingService.resolve_attendance_policy(
            company=self.company,
        )

        self.assertEqual(policy.method, "")
        self.assertTrue(policy.is_default)
        self.assertTrue(policy.deduct_absence)
        self.assertTrue(policy.deduct_unpaid_leave)

        # `make_period` menulis working_days=30 di periodenya.
        period = self.make_period()
        employee = self.make_employee(basic_salary="9000000")

        self.make_absence(employee, date(2026, 9, 8))

        line, run = self.run_payroll(period=period, employee=employee)

        self.assertEqual(line.attendance_deduction_method, "")
        self.assertEqual(line.deduction_base_days, Decimal("30.00"))
        self.assertEqual(line.absence_deduction, Decimal("300000.00"))

    def test_belum_memilih_menghasilkan_temuan_yang_menyebutnya(self):
        """
        "Belum dipilih" dan "sudah dipilih, kebetulan sama" menghasilkan
        angka yang sama. Tanpa temuan ini tidak ada yang bisa
        membedakannya.
        """
        self.clear_policy()

        period = self.make_month(2044, 9, 30)
        employee = self.make_employee(basic_salary="9000000")

        _, run = self.run_payroll(period=period, employee=employee)

        run.refresh_from_db()

        codes = {
            item["code"]
            for item in run.validation_summary.get("warnings", [])
        }

        self.assertIn("attendance_deduction_policy_missing", codes)

    def test_baris_ada_tapi_metode_kosong_tetap_dianggap_belum_memilih(self):
        """
        Yang menentukan bukan ada tidaknya baris, melainkan ada tidaknya
        keputusan. Perusahaan yang membuka layarnya untuk mengatur
        prorata saja belum memutuskan apa pun soal potongan.
        """
        self.clear_policy()
        self.set_policy(PayrollProrationMethod.FIXED_30)

        policy = PayrollSettingService.resolve_attendance_policy(
            company=self.company,
        )

        self.assertTrue(policy.is_default)
        self.assertEqual(policy.method, "")

    def test_sudah_memilih_tidak_lagi_ditagih(self):
        self.set_attendance_policy(PayrollProrationMethod.FIXED_30)

        period = self.make_month(2045, 9, 30)
        employee = self.make_employee(basic_salary="9000000")

        _, run = self.run_payroll(period=period, employee=employee)

        run.refresh_from_db()

        codes = {
            item["code"]
            for item in run.validation_summary.get("warnings", [])
        }

        self.assertNotIn("attendance_deduction_policy_missing", codes)


# ----------------------------------------------------------------------
# Dasar pajak — Business Decision #6
# ----------------------------------------------------------------------


class TaxableBaseTest(AttendanceDeductionTestCase):
    """
    Ketidakhadiran **mengurangi** gross dan dasar pajak — Business
    Decision #2 butir 4, disetujui.

    Sebelumnya kebalikannya, dan test ini menjaga kebalikan itu supaya
    tidak berubah diam-diam. Sekarang ia menjaga arah yang baru, dengan
    dua jangkar yang membuat perubahannya tidak bisa lewat diam-diam
    ke arah mana pun — tanpa menyentuh **bentuk** barisnya, yang tetap
    potongan bermagnitudo positif:

    * `net_pay` **tidak bergeser satu rupiah pun**. Gross berkurang
      persis sebesar potongan yang hilang dari sisi satunya, jadi uang
      yang diterima pegawai sama dengan sebelum keputusan ini.
    * `total_deduction` **tidak lagi memuatnya**. Itu yang membedakan
      "penghasilan yang tidak pernah terbentuk" dari "uang yang sudah
      jadi hak lalu ditahan" — butir 2.

    Metode PPh21 sendiri tidak disentuh (#4 masih OPEN); yang berubah
    dasarnya, bukan rumusnya.
    """

    def test_ketidakhadiran_menurunkan_gross_dan_taxable(self):
        self.set_attendance_policy(PayrollProrationMethod.FIXED_30)

        period = self.make_month(2046, 9, 30)

        clean = self.make_employee(basic_salary="9000000")
        absent = self.make_employee(basic_salary="9000000")

        self.make_absence(absent, self.day_in(period, 8))

        run = self.make_run(period)
        PayrollRunService.generate_employees(run=run)
        PayrollRunService.calculate(run=run)

        clean_line = self.line_for(run, clean)
        absent_line = self.line_for(run, absent)

        reduction = Decimal("300000.00")

        # Gross dan taxable keduanya turun, persis sebesar gaji yang
        # tidak pernah menjadi hak.
        self.assertEqual(
            absent_line.gross_earning,
            clean_line.gross_earning - reduction,
        )
        self.assertEqual(
            absent_line.taxable_earning,
            clean_line.taxable_earning - reduction,
        )

        # Jejak auditnya tetap, dan tetap positif.
        self.assertEqual(absent_line.absence_deduction, reduction)

        # Bukan potongan: `total_deduction` tidak ikut naik.
        self.assertEqual(
            absent_line.total_deduction, clean_line.total_deduction,
        )

        # Dan yang dibawa pulang tidak berubah dibanding sebelum
        # keputusan #2 — pengurangnya pindah sisi, bukan dihitung dua
        # kali atau hilang.
        self.assertEqual(
            absent_line.net_pay,
            clean_line.net_pay - reduction,
        )


# ----------------------------------------------------------------------
# I2. Keputusan #2 — sekali, dan hanya sekali
# ----------------------------------------------------------------------


class EarningsReductionTest(AttendanceDeductionTestCase):
    """
    Skenario A-D dan F keputusan #2, diperiksa sebagai **selisih**
    terhadap pegawai yang sebulan penuh.

    Ditulis sebagai selisih, bukan sebagai angka absolut, karena itu
    yang menjawab pertanyaannya: "berapa yang berkurang, dan berapa
    kali". Angka absolut tetap benar kalau pengurangnya dikenakan dua
    kali dan salah satunya kebetulan nol.

    Komponennya sendiri tetap `deduction` bermagnitudo positif —
    kontrak tanda yang lama tidak disentuh keputusan #2. Yang diperiksa
    di sini akibatnya pada `gross_earning`, `taxable_earning`,
    `total_deduction`, dan `net_pay`.
    """

    def reduction_components(self, line):
        return [
            component
            for component in line.components.all()
            if component.basis in EARNINGS_REDUCTION_BASES
        ]

    def test_a_sebulan_penuh_tidak_berkurang_sama_sekali(self):
        self.set_attendance_policy(PayrollProrationMethod.FIXED_30)

        period = self.make_month(2046, 4, 30)
        employee = self.make_employee(basic_salary="9000000")

        line, _ = self.run_payroll(period=period, employee=employee)

        self.assertEqual(line.gross_earning, Decimal("9000000.00"))
        self.assertEqual(line.taxable_earning, Decimal("9000000.00"))
        self.assertEqual(line.absence_deduction, Decimal("0.00"))
        self.assertEqual(line.unpaid_leave_deduction, Decimal("0.00"))
        self.assertEqual(self.reduction_components(line), [])

    def test_b_satu_hari_cuti_tidak_dibayar_berkurang_tepat_sekali(self):
        self.set_attendance_policy(PayrollProrationMethod.FIXED_30)

        period = self.make_month(2046, 4, 30)

        clean = self.make_employee(basic_salary="9000000")
        employee = self.make_employee(basic_salary="9000000")

        self.make_leave(
            employee,
            start=self.day_in(period, 10),
            end=self.day_in(period, 10),
        )

        run = self.make_run(period)
        PayrollRunService.generate_employees(run=run)
        PayrollRunService.calculate(run=run)

        clean_line = self.line_for(run, clean)
        line = self.line_for(run, employee)

        one_day = Decimal("300000.00")

        # Tepat satu baris pengurang, dan nilainya tepat satu hari.
        components = self.reduction_components(line)

        self.assertEqual(len(components), 1)
        self.assertEqual(components[0].code, "UNPAID-LEAVE")
        self.assertEqual(components[0].amount, one_day)

        self.assertEqual(
            line.gross_earning, clean_line.gross_earning - one_day,
        )
        self.assertEqual(
            line.taxable_earning, clean_line.taxable_earning - one_day,
        )
        self.assertEqual(line.net_pay, clean_line.net_pay - one_day)
        self.assertEqual(
            line.total_deduction, clean_line.total_deduction,
        )

    def test_c_satu_hari_alpa_berkurang_tepat_sekali(self):
        self.set_attendance_policy(PayrollProrationMethod.FIXED_30)

        period = self.make_month(2046, 4, 30)

        clean = self.make_employee(basic_salary="9000000")
        employee = self.make_employee(basic_salary="9000000")

        self.make_absence(employee, self.day_in(period, 8))

        run = self.make_run(period)
        PayrollRunService.generate_employees(run=run)
        PayrollRunService.calculate(run=run)

        clean_line = self.line_for(run, clean)
        line = self.line_for(run, employee)

        one_day = Decimal("300000.00")

        components = self.reduction_components(line)

        self.assertEqual(len(components), 1)
        self.assertEqual(components[0].code, "ABSENT")
        self.assertEqual(components[0].amount, one_day)

        self.assertEqual(
            line.gross_earning, clean_line.gross_earning - one_day,
        )
        self.assertEqual(line.net_pay, clean_line.net_pay - one_day)
        self.assertEqual(
            line.total_deduction, clean_line.total_deduction,
        )

    def test_d_alpa_dan_cuti_tidak_dibayar_berkurang_masing_masing(self):
        self.set_attendance_policy(PayrollProrationMethod.FIXED_30)

        period = self.make_month(2046, 4, 30)

        clean = self.make_employee(basic_salary="9000000")
        employee = self.make_employee(basic_salary="9000000")

        self.make_leave(
            employee,
            start=self.day_in(period, 10),
            end=self.day_in(period, 10),
        )
        self.make_absence(employee, self.day_in(period, 20))

        run = self.make_run(period)
        PayrollRunService.generate_employees(run=run)
        PayrollRunService.calculate(run=run)

        clean_line = self.line_for(run, clean)
        line = self.line_for(run, employee)

        one_day = Decimal("300000.00")

        # Dua baris, bukan satu angka gabungan — pegawai yang membantah
        # hari alpanya tidak boleh harus membantah cutinya sekalian.
        self.assertEqual(len(self.reduction_components(line)), 2)
        self.assertEqual(line.absence_deduction, one_day)
        self.assertEqual(line.unpaid_leave_deduction, one_day)

        self.assertEqual(
            line.gross_earning, clean_line.gross_earning - one_day * 2,
        )
        self.assertEqual(
            line.taxable_earning,
            clean_line.taxable_earning - one_day * 2,
        )
        self.assertEqual(line.net_pay, clean_line.net_pay - one_day * 2)

    def test_f_pegawai_prorata_tidak_kena_prorata_kedua_kalinya(self):
        """
        F. Pegawai yang masuk tengah bulan sudah diprorata di gaji
        pokoknya. Pengurang ketidakhadirannya **tidak** ikut diprorata:
        satu hari tidak masuk tetap seharga satu hari, bukan setengah.

        Kalau prorata terkena dua kali, pengurangnya menyusut jadi
        150.000 dan pegawai justru diuntungkan karena bolos di bulan ia
        masuk kerja — kegagalan yang tidak terbaca di satu layar pun.
        """
        self.set_policy(PayrollProrationMethod.FIXED_30)
        self.set_attendance_policy(PayrollProrationMethod.FIXED_30)

        period = self.make_month(2046, 4, 30)

        joiner = self.make_employee(
            basic_salary="9000000",
            join_date=self.day_in(period, 16),
        )
        absent_joiner = self.make_employee(
            basic_salary="9000000",
            join_date=self.day_in(period, 16),
        )

        self.make_absence(absent_joiner, self.day_in(period, 20))

        run = self.make_run(period)
        PayrollRunService.generate_employees(run=run)
        PayrollRunService.calculate(run=run)

        base_line = self.line_for(run, joiner)
        line = self.line_for(run, absent_joiner)

        # Gaji pokoknya memang sudah setengah — prorata masa kerja
        # tetap berjalan seperti sebelumnya.
        self.assertEqual(
            self.component(base_line, "BASIC").amount,
            Decimal("4500000.00"),
        )

        # Dan pengurangnya tetap sehari penuh.
        one_day = Decimal("300000.00")

        self.assertEqual(line.absence_deduction, one_day)
        self.assertEqual(self.component(line, "ABSENT").amount, one_day)
        self.assertFalse(self.component(line, "ABSENT").is_prorated)

        self.assertEqual(
            line.gross_earning, base_line.gross_earning - one_day,
        )

    def test_g_slip_memperlihatkan_baris_pengurangnya(self):
        """
        G. Barisnya tetap terbaca di slip: jenis, jumlah hari, nilai
        sehari, dan uang yang berkurang. Ditambah kolom jejak yang
        sudah ada sejak sebelum keputusan ini.
        """
        self.set_attendance_policy(PayrollProrationMethod.FIXED_30)

        period = self.make_month(2046, 4, 30)
        employee = self.make_employee(basic_salary="9000000")

        self.make_absence(employee, self.day_in(period, 8))

        line, run = self.run_payroll(period=period, employee=employee)

        PayrollRunEmployee.objects.filter(
            run=run, payroll_assignment__isnull=True,
        ).update(
            is_excluded=True,
            status=PayrollRunEmployeeStatus.EXCLUDED,
            exclusion_reason="Konfigurasi belum lengkap (fixture).",
        )

        PayrollRunService._refresh_totals(run=run)
        PayrollRunService.validate(run=run)
        PayrollRunService.acknowledge(run=run)

        run.refresh_from_db()
        run.status = PayrollRunStatus.APPROVED
        run.save(update_fields=["status"])

        PayrollRunService.finalize(run=run)

        PayslipService.issue_for_run(run=run)

        slip = Payslip.objects.get(run_employee=line)

        # Barisnya tetap di tempat yang sama seperti sebelum keputusan
        # #2 — slip lama dan slip baru terbaca dengan cara yang sama.
        rows = {row["code"]: row for row in slip.snapshot["deductions"]}

        self.assertIn("ABSENT", rows)

        row = rows["ABSENT"]

        self.assertEqual(row["amount"], "300000.00")
        self.assertEqual(row["quantity"], "1.0000")
        # `rate` enam angka di belakang koma — kolomnya memang
        # begitu, dan yang diperiksa nilainya, bukan formatnya.
        self.assertEqual(Decimal(row["rate"]), Decimal("300000"))
        self.assertEqual(row["basis"], PayrollBasis.PER_ABSENT_DAY)

        # Jejak auditnya tetap ada.
        self.assertEqual(
            slip.snapshot["days"]["absence_deduction"], "300000.00",
        )

        # Dan totalnya yang membawa keputusan #2: gross sudah bersih
        # dari hari yang tidak dijalani, dan `total_deduction` tidak
        # memuatnya lagi — jadi slip ini tidak mengurangi dua kali.
        totals = slip.snapshot["totals"]

        self.assertEqual(totals["gross_earning"], "8700000.00")

        # Diperiksa sebagai **selisih** terhadap jumlah baris
        # potongannya sendiri, bukan sebagai angka absolut: pegawai
        # fixture ini punya potongan lain yang tidak ada hubungannya,
        # dan angka absolut akan ikut berubah tiap kali fixture-nya
        # disentuh tanpa memberi tahu apa pun soal keputusan #2.
        listed = sum(
            Decimal(row["amount"]) for row in slip.snapshot["deductions"]
        )

        self.assertEqual(
            listed - Decimal(totals["total_deduction"]),
            Decimal("300000.00"),
        )

        # Yang dibawa pulang tetap gross dikurangi potongan yang
        # memang memotong — sekali, bukan dua kali.
        self.assertEqual(
            Decimal(totals["net_pay"]),
            Decimal(totals["gross_earning"])
            - Decimal(totals["total_deduction"]),
        )

    def test_komponen_master_menang_dan_tetap_sekali(self):
        """
        Tenant yang menulis pengurangnya sendiri di Deduction Template
        tidak boleh kena dua kali. Barisnya tetap ditulis di layar itu;
        yang berubah cuma sisi tempat hasilnya mendarat.
        """
        self.set_attendance_policy(PayrollProrationMethod.FIXED_30)

        period = self.make_month(2046, 4, 30)
        employee = self.make_employee(basic_salary="9000000")

        template = DeductionTemplate.objects.create(
            code="DED-ABS", name="Potongan Alpa Sendiri",
        )

        DeductionTemplateLine.objects.create(
            template=template,
            code="ALPA-SENDIRI",
            name="Alpa Menurut Perusahaan",
            basis=PayrollBasis.PER_ABSENT_DAY,
            amount=Decimal("250000"),
            sequence=10,
        )

        assignment = employee.payroll_assignments.first()
        assignment.deduction_template = template
        assignment.save()

        self.make_absence(employee, self.day_in(period, 8))

        line, _ = self.run_payroll(period=period, employee=employee)

        codes = self.codes(line)

        # Punya tenant dipakai; bawaan mesin tidak ikut menambah.
        self.assertIn("ALPA-SENDIRI", codes)
        self.assertNotIn("ABSENT", codes)

        component = self.component(line, "ALPA-SENDIRI")

        self.assertEqual(
            component.component_type, PayrollComponentType.DEDUCTION,
        )
        self.assertEqual(component.amount, Decimal("250000.00"))

        # Kolom jejaknya membaca basis, bukan nama komponen, jadi ia
        # tetap terisi walau kodenya karangan tenant.
        self.assertEqual(line.absence_deduction, Decimal("250000.00"))
        self.assertEqual(
            line.gross_earning, Decimal("8750000.00"),
        )


# ----------------------------------------------------------------------
# J. Kekebalan histori
# ----------------------------------------------------------------------


class FinalizedImmunityTest(AttendanceDeductionTestCase):
    """
    J. Run yang sudah Finalized kebal terhadap perubahan sumbernya.

    Tidak ada sistem versioning baru untuk ini: penguncian dan snapshot
    yang sudah ada sudah cukup, dan membangun yang kedua di atasnya
    berarti dua tempat yang harus sepakat tentang hal yang sama.
    """

    def finalize(self, run):
        from apps.payroll.models import PayrollRunEmployee

        PayrollRunEmployee.objects.filter(
            run=run, payroll_assignment__isnull=True,
        ).update(
            is_excluded=True,
            status=PayrollRunEmployeeStatus.EXCLUDED,
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

    def test_mengubah_sumber_setelah_final_tidak_mengubah_angkanya(self):
        self.set_attendance_policy(PayrollProrationMethod.FIXED_30)

        period = self.make_month(2047, 9, 30)
        employee = self.make_employee(basic_salary="9000000")

        leave = self.make_leave(
            employee,
            start=self.day_in(period, 10),
            end=self.day_in(period, 11),
        )
        self.make_absence(employee, self.day_in(period, 20))

        run = self.make_run(period)
        PayrollRunService.generate_employees(run=run)
        PayrollRunService.calculate(run=run)

        run = self.finalize(run)

        line = self.line_for(run, employee)

        self.assertEqual(line.unpaid_leave_deduction, Decimal("600000.00"))
        self.assertEqual(line.absence_deduction, Decimal("300000.00"))

        slip = Payslip.objects.get(run_employee=line)
        snapshot_days = slip.snapshot["days"]

        # --- sumbernya diubah sesudah Finalize ---------------------
        leave.status = LeaveStatus.CANCELLED
        leave.save(update_fields=["status"])

        EmployeeAttendance.objects.filter(employee=employee).delete()

        self.set_attendance_policy(
            PayrollProrationMethod.CALENDAR_DAYS,
            absence=False,
            unpaid=False,
        )

        line.refresh_from_db()

        self.assertEqual(line.unpaid_leave_deduction, Decimal("600000.00"))
        self.assertEqual(line.absence_deduction, Decimal("300000.00"))
        self.assertEqual(
            line.attendance_deduction_method,
            PayrollProrationMethod.FIXED_30,
        )

        slip.refresh_from_db()
        self.assertEqual(slip.snapshot["days"], snapshot_days)
        self.assertEqual(
            snapshot_days["unpaid_leave_deduction"], "600000.00",
        )
        self.assertEqual(snapshot_days["absence_deduction"], "300000.00")

    def test_periode_berikutnya_memakai_kebijakan_yang_baru(self):
        """
        Kebalikannya juga harus benar: kebijakan baru berlaku untuk run
        berikutnya. Kebal bukan berarti beku selamanya.
        """
        self.set_attendance_policy(PayrollProrationMethod.FIXED_30)

        first = self.make_month(2048, 1, 31)
        employee = self.make_employee(basic_salary="9300000")

        self.make_absence(employee, self.day_in(first, 5))

        line, _ = self.run_payroll(period=first, employee=employee)
        self.assertEqual(line.absence_deduction, Decimal("310000.00"))

        self.set_attendance_policy(PayrollProrationMethod.CALENDAR_DAYS)

        second = self.make_month(2048, 3, 31)
        other = self.make_employee(basic_salary="9300000")

        self.make_absence(other, self.day_in(second, 5))

        line, _ = self.run_payroll(period=second, employee=other)

        # 9.300.000 / 31 = 300.000.
        self.assertEqual(line.deduction_base_days, Decimal("31.00"))
        self.assertEqual(line.absence_deduction, Decimal("300000.00"))
