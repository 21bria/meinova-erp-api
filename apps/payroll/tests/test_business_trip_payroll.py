"""
BT-3 — Business Trip × payroll.

`BUSINESS_TRIP` = hari tugas yang **dibayar**, bukan hadir fisik:

* `attendance_days` = hadir fisik saja;
* `business_trip_days` = hari dinas tanpa hadir fisik, disimpan terpisah
  di `PayrollRunEmployee` (snapshot);
* gaji bulanan tidak dipotong untuk hari dinas;
* upah harian = hadir + dinas (+ kategori lain yang sudah ada);
* tunjangan per hari hadir hanya hadir fisik; per hari dibayar ikut
  hari dinas;
* satu tanggal tidak pernah dihitung dua kali;
* hanya perjalanan APPROVED / ON_TRIP / COMPLETED yang menutup alpa;
* run yang sudah Finalized tidak bergeser.

Fixture dipakai ulang dari `test_attendance_deduction` supaya keadaan
awalnya sama dengan seluruh test payroll lainnya.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError

from apps.hr.api.business_trip.reconcile import reconcile_attendance
from apps.hr.models import (
    BusinessTrip,
    BusinessTripDestinationType,
    BusinessTripPurpose,
    BusinessTripStatus,
    PayrollAssignment,
)
from apps.hr.models.attendance import AttendanceStatus, EmployeeAttendance
from apps.hr.models.attendance.choices import AttendanceSource
from apps.payroll.models import (
    AllowanceTemplate,
    AllowanceTemplateLine,
    PayrollBasis,
    PayrollDailyRateMethod,
    PayrollPayBasis,
    PayrollPolicy,
    PayrollProrationMethod,
    PayrollRunEmployee,
    PayrollRunStatus,
    PayrollRunEmployeeStatus,
)
from apps.payroll.models.choices import PayrollPeriodStatus
from apps.payroll.services import PayrollRunService, PayrollSourceService

from .test_attendance_deduction import AttendanceDeductionTestCase


WALL = ZoneInfo("Asia/Jakarta")


def at(day, hour, minute=0):
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=WALL)


class BusinessTripPayrollTest(AttendanceDeductionTestCase):
    # ------------------------------------------------------------------
    # Pabrik data
    # ------------------------------------------------------------------

    def make_trip(self, employee, start, end, *,
                  status=BusinessTripStatus.APPROVED, **extra):
        data = {
            "request_date": start - timedelta(days=7),
            "employee": employee,
            "company": self.company,
            "destination_type": BusinessTripDestinationType.EXTERNAL_DOMESTIC,
            "destination_detail": "Kendari",
            "purpose_category": BusinessTripPurpose.SITE_VISIT,
            "purpose": "Inspeksi",
            "departure_datetime": at(start, 7),
            "return_datetime": at(end, 18),
            "status": status,
        }
        data.update(extra)

        return BusinessTrip.objects.create(**data)

    def trip_rows(self, employee, trip, *dates):
        """Baris yang ditulis penutup hari untuk hari dinas tanpa tap."""
        for work_date in dates:
            EmployeeAttendance.objects.create(
                employee=employee,
                company=self.company,
                work_date=work_date,
                status=AttendanceStatus.BUSINESS_TRIP,
                source=AttendanceSource.SYSTEM,
                business_trip=trip,
            )

    def facts_for(self, employee, period):
        return PayrollSourceService.collect(
            employee=employee,
            start_date=period.start_date,
            end_date=period.end_date,
        )

    def set_template(self, employee, *lines):
        type(self)._counter += 1

        template = AllowanceTemplate.objects.create(
            code=f"BT3-{type(self)._counter}",
            name="Paket BT-3",
        )

        for sequence, (code, basis, amount) in enumerate(lines, start=1):
            AllowanceTemplateLine.objects.create(
                template=template,
                code=code,
                name=code,
                sequence=sequence * 10,
                basis=basis,
                amount=Decimal(amount),
                is_taxable=True,
                is_prorated=False,
            )

        PayrollAssignment.objects.filter(employee=employee).update(
            allowance_template=template,
        )

    def make_daily(self, employee, *, daily_rate="200000"):
        type(self)._counter += 1

        policy = PayrollPolicy(
            company=self.company,
            code=f"BT3DAILY{type(self)._counter}",
            name="Harian",
            pay_basis=PayrollPayBasis.DAILY,
            daily_rate_method=PayrollDailyRateMethod.ASSIGNMENT_RATE,
            pay_paid_leave="no",
        )
        policy.full_clean()
        policy.save()

        assignment = PayrollAssignment.objects.get(
            employee=employee, is_current=True, is_deleted=False,
        )
        assignment.payroll_policy = policy
        assignment.daily_rate = Decimal(daily_rate)
        assignment.full_clean()
        assignment.save()

    def finalize(self, run):
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

    # ------------------------------------------------------------------
    # 18, 19, 20 — bulanan
    # ------------------------------------------------------------------

    def test_monthly_trip_days_are_not_deducted_and_stored_separately(self):
        self.set_attendance_policy(PayrollProrationMethod.FIXED_30)

        period = self.make_month(2041, 9, 30)
        employee = self.make_employee(basic_salary="9000000")

        trip = self.make_trip(
            employee,
            self.day_in(period, 10),
            self.day_in(period, 12),
        )
        self.trip_rows(
            employee,
            trip,
            self.day_in(period, 10),
            self.day_in(period, 11),
            self.day_in(period, 12),
        )
        self.make_present(employee, self.day_in(period, 13))

        line, _ = self.run_payroll(period=period, employee=employee)

        self.assertEqual(line.absent_days, Decimal("0.00"))
        self.assertEqual(line.absence_deduction, Decimal("0.00"))

        self.assertEqual(line.attendance_days, Decimal("1.00"))
        self.assertEqual(line.business_trip_days, Decimal("3.00"))

        # Dokumen ada → bukan temuan "tanpa dokumen".
        self.assertNotIn(
            "business_trip_without_document",
            {finding["code"] for finding in line.findings},
        )

    # ------------------------------------------------------------------
    # 21 — tidak dihitung dua kali
    # ------------------------------------------------------------------

    def test_physical_attendance_on_a_trip_day_is_counted_once(self):
        period = self.make_month(2042, 9, 30)
        employee = self.make_employee(basic_salary="9000000")

        trip = self.make_trip(
            employee,
            self.day_in(period, 10),
            self.day_in(period, 11),
        )

        # Hari pertama ada tap fisik (dengan konteks perjalanan), hari
        # kedua tanpa tap.
        EmployeeAttendance.objects.create(
            employee=employee,
            company=self.company,
            work_date=self.day_in(period, 10),
            status=AttendanceStatus.PRESENT,
            business_trip=trip,
            check_in=at(self.day_in(period, 10), 7, 55),
        )
        self.trip_rows(employee, trip, self.day_in(period, 11))

        facts = self.facts_for(employee, period)

        self.assertEqual(facts.attendance_days, Decimal("1"))
        self.assertEqual(facts.business_trip_days, Decimal("1"))

    def test_trip_row_with_an_unresolved_tap_stays_physical_attendance(self):
        """Tap fisik menang walaupun resolver tidak bisa menghitung jadwal."""
        period = self.make_month(2043, 9, 30)
        employee = self.make_employee(basic_salary="9000000")

        trip = self.make_trip(
            employee,
            self.day_in(period, 10),
            self.day_in(period, 10),
        )

        EmployeeAttendance.objects.create(
            employee=employee,
            company=self.company,
            work_date=self.day_in(period, 10),
            status=AttendanceStatus.BUSINESS_TRIP,
            business_trip=trip,
            check_in=at(self.day_in(period, 10), 8, 5),
        )

        facts = self.facts_for(employee, period)

        self.assertEqual(facts.attendance_days, Decimal("1"))
        self.assertEqual(facts.business_trip_days, Decimal("0.00"))

    def test_absent_row_on_an_approved_trip_date_is_covered(self):
        """
        Perjalanan disetujui sesudah penutup hari menulis alpa: barisnya
        tidak ditulis ulang, payroll menutupnya berdasarkan tanggal.
        """
        self.set_attendance_policy(PayrollProrationMethod.FIXED_30)

        period = self.make_month(2044, 9, 30)
        employee = self.make_employee(basic_salary="9000000")

        self.make_trip(
            employee,
            self.day_in(period, 10),
            self.day_in(period, 10),
        )
        self.make_absence(
            employee,
            self.day_in(period, 10),
            self.day_in(period, 20),
        )

        line, _ = self.run_payroll(period=period, employee=employee)

        self.assertEqual(line.absent_days, Decimal("1.00"))
        self.assertEqual(line.absence_deduction, Decimal("300000.00"))
        self.assertEqual(line.business_trip_days, Decimal("1.00"))

        facts = self.facts_for(employee, period)
        self.assertEqual(facts.absence_covered_by_business_trip, 1)

    def test_leave_wins_over_a_trip_on_the_same_date(self):
        period = self.make_month(2045, 9, 30)
        employee = self.make_employee(basic_salary="9000000")

        day = self.day_in(period, 10)

        self.make_trip(employee, day, day)
        self.make_leave(employee, start=day, end=day, unpaid=True)
        self.make_absence(employee, day)

        facts = self.facts_for(employee, period)

        self.assertEqual(facts.absence_covered_by_leave, 1)
        self.assertEqual(facts.absence_covered_by_business_trip, 0)
        self.assertEqual(facts.business_trip_days, Decimal("0.00"))
        self.assertEqual(facts.unpaid_leave_days, Decimal("1"))

    # ------------------------------------------------------------------
    # 22 — harian
    # ------------------------------------------------------------------

    def test_daily_paid_payable_days_include_business_trip_days(self):
        period = self.make_month(2046, 9, 30)
        employee = self.make_employee(basic_salary="0")
        self.make_daily(employee, daily_rate="200000")

        trip = self.make_trip(
            employee,
            self.day_in(period, 10),
            self.day_in(period, 11),
        )
        self.trip_rows(
            employee,
            trip,
            self.day_in(period, 10),
            self.day_in(period, 11),
        )
        self.make_present(
            employee,
            self.day_in(period, 12),
            self.day_in(period, 13),
            self.day_in(period, 14),
        )

        line, _ = self.run_payroll(period=period, employee=employee)

        self.assertEqual(line.attendance_days, Decimal("3.00"))
        self.assertEqual(line.business_trip_days, Decimal("2.00"))
        self.assertEqual(line.paid_days, Decimal("5.00"))

    # ------------------------------------------------------------------
    # 23, 24 — tunjangan
    # ------------------------------------------------------------------

    def test_allowances_per_attendance_day_exclude_and_per_paid_day_include_trips(self):
        self.set_attendance_policy(PayrollProrationMethod.FIXED_30)

        period = self.make_month(2047, 9, 30)
        employee = self.make_employee(basic_salary="9000000")

        self.set_template(
            employee,
            ("MEAL", PayrollBasis.PER_ATTENDANCE_DAY, "50000"),
            ("DUTY", PayrollBasis.PER_PAID_DAY, "10000"),
        )

        trip = self.make_trip(
            employee,
            self.day_in(period, 10),
            self.day_in(period, 12),
        )
        self.trip_rows(
            employee,
            trip,
            self.day_in(period, 10),
            self.day_in(period, 11),
            self.day_in(period, 12),
        )
        self.make_present(
            employee,
            self.day_in(period, 13),
            self.day_in(period, 14),
        )

        line, _ = self.run_payroll(period=period, employee=employee)

        meal = line.components.get(code="MEAL")
        duty = line.components.get(code="DUTY")

        # Hanya dua hari hadir fisik.
        self.assertEqual(meal.quantity, Decimal("2"))
        self.assertEqual(meal.amount, Decimal("100000.00"))

        # Hari dibayar tidak dikurangi hari dinas.
        self.assertEqual(duty.quantity, line.paid_days)
        self.assertEqual(line.paid_days, line.working_days)

    # ------------------------------------------------------------------
    # 25 — perjalanan yang tidak berlaku tidak menutup apa pun
    # ------------------------------------------------------------------

    def test_non_approved_or_cancelled_trips_do_not_cover_absence(self):
        self.set_attendance_policy(PayrollProrationMethod.FIXED_30)

        period = self.make_month(2048, 9, 30)
        day = self.day_in(period, 10)

        cases = [
            {"status": BusinessTripStatus.SUBMITTED},
            {"status": BusinessTripStatus.REJECTED},
            {"status": BusinessTripStatus.DRAFT},
            {
                "status": BusinessTripStatus.CANCELLED,
                "cancelled_at": at(day - timedelta(days=3), 9),
            },
        ]

        for extra in cases:
            with self.subTest(status=extra["status"]):
                employee = self.make_employee(basic_salary="9000000")
                self.make_trip(employee, day, day, **extra)
                self.make_absence(employee, day)

                facts = self.facts_for(employee, period)

                self.assertEqual(facts.absent_days, Decimal("1"))
                self.assertEqual(facts.business_trip_days, Decimal("0.00"))

    # ------------------------------------------------------------------
    # 26 — deterministik
    # ------------------------------------------------------------------

    def test_recalculation_is_deterministic(self):
        period = self.make_month(2049, 9, 30)
        employee = self.make_employee(basic_salary="9000000")

        trip = self.make_trip(
            employee,
            self.day_in(period, 10),
            self.day_in(period, 11),
        )
        self.trip_rows(
            employee,
            trip,
            self.day_in(period, 10),
            self.day_in(period, 11),
        )
        self.make_present(employee, self.day_in(period, 12))

        line, run = self.run_payroll(period=period, employee=employee)

        def snapshot(item):
            item.refresh_from_db()

            return (
                item.attendance_days,
                item.business_trip_days,
                item.paid_days,
                item.absent_days,
                item.net_pay,
                sorted(
                    (c.code, c.quantity, c.amount)
                    for c in item.components.all()
                ),
            )

        first = snapshot(line)

        PayrollRunService.calculate(run=run)

        self.assertEqual(snapshot(line), first)

    # ------------------------------------------------------------------
    # 27 — snapshot historis
    # ------------------------------------------------------------------

    def test_finalized_run_keeps_its_business_trip_days(self):
        period = self.make_month(2050, 9, 30)
        employee = self.make_employee(basic_salary="9000000")

        trip = self.make_trip(
            employee,
            self.day_in(period, 10),
            self.day_in(period, 11),
        )
        self.trip_rows(
            employee,
            trip,
            self.day_in(period, 10),
            self.day_in(period, 11),
        )

        line, run = self.run_payroll(period=period, employee=employee)
        self.finalize(run)

        # Dokumennya berubah sesudah run dikunci.
        BusinessTrip.objects.filter(pk=trip.pk).update(
            status=BusinessTripStatus.CANCELLED,
            cancelled_at=at(self.day_in(period, 1), 9),
        )

        with self.assertRaises(ValidationError):
            PayrollRunService.calculate(run=run)

        line.refresh_from_db()
        self.assertEqual(line.business_trip_days, Decimal("2.00"))

    def test_revocation_is_refused_inside_a_finalized_period(self):
        period = self.make_month(2051, 9, 30)
        employee = self.make_employee(basic_salary="9000000")

        trip = self.make_trip(
            employee,
            self.day_in(period, 10),
            self.day_in(period, 12),
            status=BusinessTripStatus.ON_TRIP,
        )
        self.trip_rows(
            employee,
            trip,
            self.day_in(period, 10),
            self.day_in(period, 11),
            self.day_in(period, 12),
        )

        period.status = PayrollPeriodStatus.FINALIZED
        period.save(update_fields=["status"])

        # Pulang lebih awal pada tanggal 10: tanggal 11–12 tidak lagi
        # diizinkan, tapi keduanya sudah dipakai payroll yang dikunci.
        # (`complete()` memanggil fungsi yang sama di dalam transaksinya,
        # jadi penolakan ini ikut membatalkan perpindahan statusnya.)
        trip.status = BusinessTripStatus.COMPLETED
        trip.actual_return_datetime = at(self.day_in(period, 10), 16)

        with self.assertRaises(ValidationError):
            reconcile_attendance(trip)

        self.assertEqual(
            EmployeeAttendance.objects.filter(
                business_trip=trip, is_deleted=False,
            ).count(),
            3,
        )

    # ------------------------------------------------------------------
    # 28 — pegawai lain tidak ikut tertutup
    # ------------------------------------------------------------------

    def test_trip_covers_only_its_own_employee(self):
        period = self.make_month(2052, 9, 30)
        day = self.day_in(period, 10)

        traveller = self.make_employee(basic_salary="9000000")
        colleague = self.make_employee(basic_salary="9000000")

        self.make_trip(traveller, day, day)
        self.make_absence(traveller, day)
        self.make_absence(colleague, day)

        self.assertEqual(
            self.facts_for(traveller, period).absent_days,
            Decimal("0.00"),
        )
        self.assertEqual(
            self.facts_for(colleague, period).absent_days,
            Decimal("1"),
        )

    # ------------------------------------------------------------------
    # 29 — kelayakan grup
    # ------------------------------------------------------------------

    def test_approved_trip_stays_authorized_after_group_switched_off(self):
        """
        Kelayakan dinilai saat pengajuan (BT-2). Izin yang sudah
        disetujui tidak dicabut diam-diam oleh perubahan master grup.
        """
        from apps.administration.models import EmployeeGroup
        from apps.hr.models import EmploymentAssignment

        type(self)._counter += 1

        group = EmployeeGroup.objects.create(
            code=f"BT3G{type(self)._counter}",
            name="Grup BT-3",
            business_trip_applicable=True,
        )

        period = self.make_month(2053, 9, 30)
        day = self.day_in(period, 10)
        employee = self.make_employee(basic_salary="9000000")

        EmploymentAssignment.objects.filter(employee=employee).update(
            employee_group=group,
        )

        trip = self.make_trip(employee, day, day)
        self.trip_rows(employee, trip, day)

        group.business_trip_applicable = False
        group.save(update_fields=["business_trip_applicable"])

        facts = self.facts_for(employee, period)

        self.assertEqual(facts.business_trip_days, Decimal("1"))
        self.assertEqual(facts.absent_days, Decimal("0.00"))
