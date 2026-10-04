"""
BT-1 → BT-3 — perlakuan payroll atas `AttendanceStatus.BUSINESS_TRIP`.

Berkas ini dibuat BT-1 untuk mengunci perilaku **sebelum** BT-3, dan
sengaja diubah bersama BT-3 (`docs/claude/hr/business-trip.md` §11,
§32). Setiap pin yang berubah menyebut perilaku lama dan barunya:

| Pin | Sebelum BT-3 | Sesudah BT-3 |
|---|---|---|
| hari dinas | ikut `attendance_days` (dianggap hadir) | `business_trip_days`, **bukan** hadir fisik |
| wadah terpisah | tidak ada | `PeriodFacts.business_trip_days` + snapshot `PayrollRunEmployee.business_trip_days` |
| gaji bulanan | tidak dipotong | tetap tidak dipotong (hari dinas bukan alpa) |
| alpa tanpa penutup | dipotong | tetap dipotong (penutupan oleh perjalanan diuji di `test_business_trip_payroll`) |
| upah harian | `attendance_days` (hari dinas ikut karena dianggap hadir) | `attendance_days + business_trip_days` — angkanya tetap sama |
| tunjangan per hari hadir | ikut menghitung hari dinas | **tidak** lagi — hanya hadir fisik |

Alasannya satu: Business Trip adalah izin kerja di luar lokasi yang
dibayar, bukan kehadiran fisik. Menyamakannya membuat tunjangan yang
mensyaratkan hadir (makan/transport) terbayar untuk hari yang tidak
dihadiri.

Baris di sini diketik langsung tanpa dokumen Business Trip — itu yang
diuji: status baris tetap dihormati, dan payroll menandainya sebagai
temuan (`manual_business_trip_days`).
"""

from __future__ import annotations

from decimal import Decimal
from types import SimpleNamespace

from apps.hr.models.attendance import AttendanceStatus, EmployeeAttendance
from apps.payroll.models import PayrollBasis, PayrollProrationMethod
from apps.payroll.services import PayrollRunService, PayrollSourceService
from apps.payroll.services.calculation import PayrollCalculationService

from .test_attendance_deduction import AttendanceDeductionTestCase


class BusinessTripPayrollBaselineTest(AttendanceDeductionTestCase):
    def make_trip_days(self, employee, *dates):
        for work_date in dates:
            EmployeeAttendance.objects.create(
                employee=employee,
                company=self.company,
                work_date=work_date,
                status=AttendanceStatus.BUSINESS_TRIP,
            )

    def facts_for(self, employee, period):
        return PayrollSourceService.collect(
            employee=employee,
            start_date=period.start_date,
            end_date=period.end_date,
        )

    # ------------------------------------------------------------------

    def test_business_trip_rows_are_trip_days_not_attendance_days(self):
        """
        Sebelum BT-3: 2 dinas + 1 hadir = `attendance_days` 3.
        Sesudah BT-3: hadir fisik 1, hari dinas 2 — tidak digabung.
        """
        period = self.make_month(2035, 9, 30)
        employee = self.make_employee(basic_salary="9000000")

        self.make_trip_days(
            employee,
            self.day_in(period, 10),
            self.day_in(period, 11),
        )
        self.make_present(employee, self.day_in(period, 12))

        facts = self.facts_for(employee, period)

        self.assertEqual(facts.attendance_days, Decimal("1"))
        self.assertEqual(facts.business_trip_days, Decimal("2"))
        self.assertEqual(facts.absent_days, Decimal("0.00"))
        self.assertEqual(facts.unauthorized_absence_days, Decimal("0.00"))
        self.assertTrue(facts.has_attendance_source)

        # Tanpa dokumen Business Trip: tetap dihitung, tapi disebut.
        self.assertEqual(facts.manual_business_trip_days, 2)

    def test_separate_business_trip_bucket_exists(self):
        """Sebelum BT-3 wadahnya tidak ada; sesudahnya terisi."""
        period = self.make_month(2036, 9, 30)
        employee = self.make_employee(basic_salary="9000000")

        self.make_trip_days(employee, self.day_in(period, 10))

        facts = self.facts_for(employee, period)

        self.assertEqual(facts.business_trip_days, Decimal("1"))
        self.assertEqual(facts.attendance_days, Decimal("0.00"))

    def test_monthly_salary_is_not_deducted_for_trip_days(self):
        """
        Tidak berubah: tidak ada potongan. Yang berubah snapshot-nya —
        sebelum BT-3 `attendance_days` 2, sesudahnya `attendance_days` 0
        dan `business_trip_days` 2.
        """
        self.set_attendance_policy(PayrollProrationMethod.FIXED_30)

        period = self.make_month(2037, 9, 30)
        employee = self.make_employee(basic_salary="9000000")

        self.make_trip_days(
            employee,
            self.day_in(period, 10),
            self.day_in(period, 11),
        )

        line, _ = self.run_payroll(period=period, employee=employee)

        self.assertEqual(line.absent_days, Decimal("0.00"))
        self.assertEqual(line.absence_deduction, Decimal("0.00"))

        self.assertEqual(line.attendance_days, Decimal("0.00"))
        self.assertEqual(line.business_trip_days, Decimal("2.00"))

        self.assertIn(
            "business_trip_without_document",
            {finding["code"] for finding in line.findings},
        )

    def test_absent_row_is_deducted_when_nothing_covers_it(self):
        """
        Tidak berubah. Alpa yang tidak tertutup cuti **maupun** Business
        Trip yang disetujui tetap dipotong. Penutupan oleh perjalanan
        (`absence_covered_by_business_trip`) diuji di
        `test_business_trip_payroll`.
        """
        self.set_attendance_policy(PayrollProrationMethod.FIXED_30)

        period = self.make_month(2038, 9, 30)
        employee = self.make_employee(basic_salary="9000000")

        self.make_absence(employee, self.day_in(period, 10))

        line, _ = self.run_payroll(period=period, employee=employee)

        self.assertEqual(line.absent_days, Decimal("1.00"))
        self.assertEqual(line.absence_deduction, Decimal("300000.00"))

    def test_daily_paid_payable_days_include_business_trip_days(self):
        """
        Angkanya tetap 3, sumbernya berubah. Sebelum BT-3: `attendance_days`
        3 (hari dinas dianggap hadir). Sesudah BT-3: `attendance_days` 1 +
        `business_trip_days` 2 — upah harian tidak terpotong karena hari
        dinas keluar dari hari hadir.
        """
        period = self.make_month(2039, 9, 30)
        employee = self.make_employee(basic_salary="9000000")

        self.make_trip_days(
            employee,
            self.day_in(period, 10),
            self.day_in(period, 11),
        )
        self.make_present(employee, self.day_in(period, 12))

        facts = self.facts_for(employee, period)

        payable = PayrollRunService._payable_days(
            facts=facts,
            resolved=SimpleNamespace(pay_paid_leave=False),
        )

        self.assertEqual(facts.attendance_days, Decimal("1"))
        self.assertEqual(facts.business_trip_days, Decimal("2"))
        self.assertEqual(payable, Decimal("3"))

    def test_per_attendance_day_allowances_exclude_trip_days(self):
        """
        Sebelum BT-3: tunjangan per hari hadir memakai `attendance_days`
        yang ikut menghitung hari dinas (3). Sesudah BT-3: rumusnya sama
        (`attendance_days`), tapi isinya hanya hadir fisik (1).
        """
        period = self.make_month(2040, 9, 30)
        employee = self.make_employee(basic_salary="9000000")

        self.make_trip_days(
            employee,
            self.day_in(period, 10),
            self.day_in(period, 11),
        )
        self.make_present(employee, self.day_in(period, 12))

        facts = self.facts_for(employee, period)

        data = SimpleNamespace(
            working_days=Decimal("22"),
            paid_days=Decimal("22"),
            attendance_days=facts.attendance_days,
            absent_days=facts.absent_days,
            unpaid_leave_days=Decimal("0"),
            overtime_hours=Decimal("0"),
        )

        self.assertEqual(
            PayrollCalculationService._quantity_for(
                data,
                PayrollBasis.PER_ATTENDANCE_DAY,
            ),
            Decimal("1"),
        )
