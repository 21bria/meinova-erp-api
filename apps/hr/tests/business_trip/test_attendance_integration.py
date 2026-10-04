"""
BT-3 — Business Trip × presensi.

Business Trip adalah **izin kerja di luar lokasi yang dibayar**, bukan
hadir fisik. Yang dikunci berkas ini:

* hari terjadwal tanpa tap yang diizinkan perjalanan yang disetujui →
  `business_trip` (+ FK), tanpa jam masuk/keluar, jam kerja, atau lembur;
* tap fisik selalu menang (PRESENT/LATE dari resolver yang ada), dan
  perjalanan tidak pernah menimpa baris yang sudah ada;
* urutan: cuti (termasuk sakit) → izin sehari penuh → perjalanan → alpa;
* hanya APPROVED / ON_TRIP / COMPLETED yang mengizinkan; CANCELLED hanya
  hari sebelum pembatalan;
* hari tidak terjadwal tidak pernah jadi hari kerja;
* penutup hari aman diulang;
* tanggal dibaca di zona jam dinding, bukan UTC;
* pulang lebih awal / pembatalan mencabut baris yang dimiliki
  perjalanan, tanpa menyentuh tap fisik.

Tanggalnya dipatok (Maret 2026), bukan dihitung dari hari ini.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.test import SimpleTestCase
from django.utils import timezone

from apps.administration.models import Company, LeaveType, Location, WorkCalendar
from apps.administration.models.references.hr_attendance import Shift
from apps.core.testing.tenant import ReusableTenantTestCase
from apps.hr.api.attendance.closing import AttendanceClosingService
from apps.hr.api.business_trip.coverage import coverage_range
from apps.hr.api.business_trip.reconcile import reconcile_attendance
from apps.hr.api.business_trip.services import BusinessTripService
from apps.hr.imports.services.attendance import AttendanceImportWriter
from apps.hr.models import (
    BusinessTrip,
    BusinessTripDestinationType,
    BusinessTripPurpose,
    BusinessTripStatus,
    Employee,
    EmployeeAttendance,
    EmployeeLeave,
    EmploymentAssignment,
    LeaveStatus,
    OrganizationAssignment,
)
from apps.hr.models.attendance.choices import AttendanceSource, AttendanceStatus
from apps.hr.models.attendance.permission import (
    AttendancePermission,
    AttendancePermissionStatus,
    AttendancePermissionType,
)


WALL = ZoneInfo("Asia/Jakarta")

MONDAY = date(2026, 3, 2)
TUESDAY = date(2026, 3, 3)
WEDNESDAY = date(2026, 3, 4)
THURSDAY = date(2026, 3, 5)
FRIDAY = date(2026, 3, 6)
SATURDAY = date(2026, 3, 7)
SUNDAY = date(2026, 3, 8)
NEXT_MONDAY = date(2026, 3, 9)


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=WALL)


# ======================================================================
# Tanggal cakupan — fungsi murni
# ======================================================================


class CoverageDateTests(SimpleTestCase):
    """17 — zona jam dinding, hari parsial, status."""

    @staticmethod
    def trip(**extra):
        data = {
            "is_deleted": False,
            "status": BusinessTripStatus.APPROVED,
            "departure_datetime": at(MONDAY, 7),
            "return_datetime": at(WEDNESDAY, 18),
            "actual_return_datetime": None,
            "cancelled_at": None,
        }
        data.update(extra)

        return SimpleNamespace(**data)

    def test_partial_first_and_last_day_are_covered_inclusive(self):
        self.assertEqual(
            coverage_range(
                self.trip(
                    departure_datetime=at(MONDAY, 23, 30),
                    return_datetime=at(THURSDAY, 0, 30),
                ),
            ),
            (MONDAY, THURSDAY),
        )

    def test_dates_are_read_on_the_wall_clock_not_utc(self):
        """
        06:00 WIB Selasa = 23:00 UTC Senin. Tanggal UTC-nya Senin, tapi
        hari bisnisnya Selasa.
        """
        departure = at(TUESDAY, 6)

        self.assertEqual(departure.astimezone(ZoneInfo("UTC")).date(), MONDAY)
        self.assertEqual(
            coverage_range(
                self.trip(
                    departure_datetime=departure,
                    return_datetime=at(TUESDAY, 20),
                ),
            ),
            (TUESDAY, TUESDAY),
        )

    def test_early_return_shortens_coverage(self):
        self.assertEqual(
            coverage_range(
                self.trip(
                    status=BusinessTripStatus.COMPLETED,
                    actual_return_datetime=at(TUESDAY, 15),
                ),
            ),
            (MONDAY, TUESDAY),
        )

    def test_only_approved_states_cover(self):
        for status in (
            BusinessTripStatus.DRAFT,
            BusinessTripStatus.SUBMITTED,
            BusinessTripStatus.REJECTED,
        ):
            with self.subTest(status=status):
                self.assertIsNone(coverage_range(self.trip(status=status)))

        for status in (
            BusinessTripStatus.APPROVED,
            BusinessTripStatus.ON_TRIP,
            BusinessTripStatus.COMPLETED,
        ):
            with self.subTest(status=status):
                self.assertEqual(
                    coverage_range(self.trip(status=status)),
                    (MONDAY, WEDNESDAY),
                )

    def test_cancelled_keeps_only_days_before_the_cancellation(self):
        self.assertEqual(
            coverage_range(
                self.trip(
                    status=BusinessTripStatus.CANCELLED,
                    cancelled_at=at(TUESDAY, 10),
                ),
            ),
            (MONDAY, MONDAY),
        )

        # Dibatalkan sebelum berangkat: tidak ada yang diizinkan.
        self.assertIsNone(
            coverage_range(
                self.trip(
                    status=BusinessTripStatus.CANCELLED,
                    cancelled_at=at(MONDAY - timedelta(days=3), 10),
                ),
            ),
        )

    def test_deleted_trip_covers_nothing(self):
        self.assertIsNone(coverage_range(self.trip(is_deleted=True)))


# ======================================================================
# Penutup hari, resolver, rekonsiliasi — database
# ======================================================================


class BusinessTripAttendanceIntegrationTests(ReusableTenantTestCase):
    reusable_schema_name = "fast_bt3_attendance"

    _counter = 0

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "bt3-attendance"
        tenant.name = "BT-3 Attendance"

    @classmethod
    def build_baseline(cls):
        cls.company, _ = Company.objects.get_or_create(
            code="BT3",
            is_deleted=False,
            defaults={"name": "BT-3 Co"},
        )

        cls.other_company, _ = Company.objects.get_or_create(
            code="BT3-B",
            is_deleted=False,
            defaults={"name": "BT-3 Other Co"},
        )

        cls.head_office, _ = Location.objects.get_or_create(
            code="BT3-HO",
            is_deleted=False,
            defaults={"company": cls.company, "name": "Jakarta HO"},
        )

        cls.calendar, _ = WorkCalendar.objects.get_or_create(
            code="BT3-OFFICE",
            is_deleted=False,
            defaults={
                "company": cls.company,
                "name": "Office Mon-Fri",
                "monday": True,
                "tuesday": True,
                "wednesday": True,
                "thursday": True,
                "friday": True,
                "saturday": False,
                "sunday": False,
                "is_default": True,
            },
        )

        cls.day_shift, _ = Shift.objects.get_or_create(
            code="BT3-DAY",
            is_deleted=False,
            defaults={
                "name": "Day 08-17",
                "start_time": time(8, 0),
                "end_time": time(17, 0),
                "crosses_midnight": False,
            },
        )

        cls.sick, _ = LeaveType.objects.get_or_create(
            code="BT3-SICK",
            is_deleted=False,
            defaults={"name": "Sick Leave"},
        )

    # ------------------------------------------------------------------
    # Pabrik data
    # ------------------------------------------------------------------

    @classmethod
    def make_employee(cls, *, company=None) -> Employee:
        cls._counter += 1

        employee = Employee.objects.create(
            employee_number=f"BT3{cls._counter:04d}",
            first_name="Trip",
            last_name=f"Employee {cls._counter}",
        )

        OrganizationAssignment.objects.create(
            employee=employee,
            company=company or cls.company,
            location=cls.head_office,
            organization_effective_date=date(2025, 1, 1),
        )

        EmploymentAssignment.objects.create(
            employee=employee,
            join_date=date(2025, 1, 1),
            working_calendar=cls.calendar,
            shift=cls.day_shift,
        )

        return Employee.objects.get(pk=employee.pk)

    @staticmethod
    def make_trip(employee, *, start=MONDAY, end=FRIDAY,
                  status=BusinessTripStatus.APPROVED, **extra):
        data = {
            "request_date": start - timedelta(days=7),
            "employee": employee,
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

    @staticmethod
    def close(employee, start=MONDAY, end=FRIDAY):
        return AttendanceClosingService.close(
            start=start,
            end=end,
            employees=[employee.pk],
        )

    @staticmethod
    def rows(employee) -> dict[date, EmployeeAttendance]:
        return {
            row.work_date: row
            for row in EmployeeAttendance.objects.filter(
                employee=employee,
                is_deleted=False,
            )
        }

    @classmethod
    def statuses(cls, employee) -> dict[date, str]:
        return {day: row.status for day, row in cls.rows(employee).items()}

    @staticmethod
    def tap(employee, when: datetime, day: date):
        """Tap mesin lewat jalur import yang sesungguhnya."""
        return AttendanceImportWriter.upsert(
            employee=employee,
            normalized={"log_time": when},
            work_date=day,
        )

    # ------------------------------------------------------------------
    # 1, 4, 5, 6 — tanpa tap
    # ------------------------------------------------------------------

    def test_approved_trip_without_tap_is_business_trip(self):
        employee = self.make_employee()
        trip = self.make_trip(employee)

        result = self.close(employee)

        self.assertEqual(result["business_trip"], 5)
        self.assertEqual(result["absent"], 0)

        for day, row in self.rows(employee).items():
            with self.subTest(day=day):
                self.assertEqual(row.status, AttendanceStatus.BUSINESS_TRIP)
                self.assertEqual(row.business_trip_id, trip.pk)
                self.assertEqual(row.source, AttendanceSource.SYSTEM)

    def test_trip_day_fabricates_no_clock_hours_or_overtime(self):
        employee = self.make_employee()
        self.make_trip(employee, start=MONDAY, end=MONDAY)

        self.close(employee, MONDAY, MONDAY)

        row = self.rows(employee)[MONDAY]

        self.assertIsNone(row.check_in)
        self.assertIsNone(row.check_out)
        self.assertIsNone(row.first_check_in)
        self.assertIsNone(row.last_check_out)
        self.assertEqual(row.worked_minutes, 0)
        self.assertEqual(row.overtime_minutes, 0)
        self.assertEqual(row.late_minutes, 0)

    # ------------------------------------------------------------------
    # 2, 3, 16 — tap fisik menang
    # ------------------------------------------------------------------

    def test_on_time_tap_on_a_trip_day_resolves_present(self):
        employee = self.make_employee()
        trip = self.make_trip(employee, start=MONDAY, end=MONDAY)

        self.close(employee, MONDAY, MONDAY)
        self.tap(employee, at(MONDAY, 7, 55), MONDAY)

        row = self.rows(employee)[MONDAY]

        self.assertEqual(row.status, AttendanceStatus.PRESENT)
        # Konteks perjalanannya tetap tercatat.
        self.assertEqual(row.business_trip_id, trip.pk)

    def test_late_tap_on_a_trip_day_resolves_late(self):
        employee = self.make_employee()
        self.make_trip(employee, start=MONDAY, end=MONDAY)

        self.close(employee, MONDAY, MONDAY)
        self.tap(employee, at(MONDAY, 9), MONDAY)

        row = self.rows(employee)[MONDAY]

        self.assertEqual(row.status, AttendanceStatus.LATE)
        self.assertGreater(row.late_minutes, 0)

    def test_existing_physical_row_is_never_overwritten(self):
        employee = self.make_employee()
        self.make_trip(employee)

        self.tap(employee, at(TUESDAY, 7, 50), TUESDAY)

        self.close(employee)

        row = self.rows(employee)[TUESDAY]

        self.assertEqual(row.status, AttendanceStatus.PRESENT)
        self.assertIsNone(row.business_trip_id)
        self.assertIsNotNone(row.check_in)

    # ------------------------------------------------------------------
    # 7–10 — status dokumen
    # ------------------------------------------------------------------

    def test_non_approved_trips_do_not_authorize(self):
        for status in (
            BusinessTripStatus.DRAFT,
            BusinessTripStatus.SUBMITTED,
            BusinessTripStatus.REJECTED,
        ):
            with self.subTest(status=status):
                employee = self.make_employee()
                self.make_trip(employee, status=status)

                self.close(employee)

                self.assertEqual(
                    set(self.statuses(employee).values()),
                    {AttendanceStatus.ABSENT},
                )

    def test_cancelled_trip_does_not_authorize_days_after_cancellation(self):
        employee = self.make_employee()
        self.make_trip(
            employee,
            status=BusinessTripStatus.CANCELLED,
            cancelled_at=at(WEDNESDAY, 9),
        )

        self.close(employee)

        self.assertEqual(
            self.statuses(employee),
            {
                MONDAY: AttendanceStatus.BUSINESS_TRIP,
                TUESDAY: AttendanceStatus.BUSINESS_TRIP,
                WEDNESDAY: AttendanceStatus.ABSENT,
                THURSDAY: AttendanceStatus.ABSENT,
                FRIDAY: AttendanceStatus.ABSENT,
            },
        )

    # ------------------------------------------------------------------
    # 11, 12 — urutan
    # ------------------------------------------------------------------

    def test_sick_leave_on_a_trip_day_wins_and_trip_is_untouched(self):
        employee = self.make_employee()
        trip = self.make_trip(employee)

        EmployeeLeave.objects.create(
            employee=employee,
            company=self.company,
            location=self.head_office,
            leave_type=self.sick,
            start_date=WEDNESDAY,
            end_date=WEDNESDAY,
            total_days=1,
            status=LeaveStatus.APPROVED,
        )

        self.close(employee)

        statuses = self.statuses(employee)

        self.assertEqual(statuses[WEDNESDAY], AttendanceStatus.LEAVE)
        self.assertEqual(statuses[TUESDAY], AttendanceStatus.BUSINESS_TRIP)
        self.assertIsNone(self.rows(employee)[WEDNESDAY].business_trip_id)

        trip.refresh_from_db()
        self.assertEqual(trip.status, BusinessTripStatus.APPROVED)

    def test_full_day_permission_wins_over_the_trip(self):
        employee = self.make_employee()
        self.make_trip(employee)

        AttendancePermission.objects.create(
            employee=employee,
            company=self.company,
            permission_type=AttendancePermissionType.FULL_DAY,
            date=THURSDAY,
            reason="Urusan keluarga",
            status=AttendancePermissionStatus.APPROVED,
        )

        self.close(employee)

        row = self.rows(employee)[THURSDAY]

        # Perilaku izin sehari penuh yang sudah ada: baris alpa yang
        # dijelaskan izinnya — bukan hari dinas.
        self.assertEqual(row.status, AttendanceStatus.ABSENT)
        self.assertIsNone(row.business_trip_id)
        self.assertEqual(
            self.statuses(employee)[FRIDAY],
            AttendanceStatus.BUSINESS_TRIP,
        )

    # ------------------------------------------------------------------
    # 13 — hari tidak terjadwal
    # ------------------------------------------------------------------

    def test_weekend_inside_a_trip_does_not_become_a_working_day(self):
        employee = self.make_employee()
        self.make_trip(employee, start=FRIDAY, end=NEXT_MONDAY)

        self.close(employee, FRIDAY, NEXT_MONDAY)

        statuses = self.statuses(employee)

        self.assertNotIn(SATURDAY, statuses)
        self.assertNotIn(SUNDAY, statuses)
        self.assertEqual(statuses[FRIDAY], AttendanceStatus.BUSINESS_TRIP)
        self.assertEqual(statuses[NEXT_MONDAY], AttendanceStatus.BUSINESS_TRIP)

    # ------------------------------------------------------------------
    # 14, 15 — idempoten
    # ------------------------------------------------------------------

    def test_closing_twice_changes_nothing(self):
        employee = self.make_employee()
        self.make_trip(employee)

        self.close(employee)
        first = {
            day: (row.pk, row.status, row.business_trip_id)
            for day, row in self.rows(employee).items()
        }

        again = self.close(employee)

        self.assertEqual(again["business_trip"], 0)
        self.assertEqual(again["absent"], 0)
        self.assertEqual(
            {
                day: (row.pk, row.status, row.business_trip_id)
                for day, row in self.rows(employee).items()
            },
            first,
        )
        self.assertEqual(
            EmployeeAttendance.objects.filter(employee=employee).count(),
            5,
        )

    # ------------------------------------------------------------------
    # 28 — perusahaan lain tidak ikut tertutup
    # ------------------------------------------------------------------

    def test_trip_covers_only_its_own_employee(self):
        traveller = self.make_employee()
        colleague = self.make_employee(company=self.other_company)
        self.make_trip(traveller)

        AttendanceClosingService.close(
            start=MONDAY,
            end=FRIDAY,
            employees=[traveller.pk, colleague.pk],
        )

        self.assertEqual(
            set(self.statuses(colleague).values()),
            {AttendanceStatus.ABSENT},
        )
        self.assertEqual(
            set(self.statuses(traveller).values()),
            {AttendanceStatus.BUSINESS_TRIP},
        )

    # ------------------------------------------------------------------
    # 10 — pencabutan saat pulang lebih awal / dibatalkan
    # ------------------------------------------------------------------

    def test_early_return_revokes_later_trip_days_but_keeps_taps(self):
        employee = self.make_employee()
        trip = self.make_trip(employee, status=BusinessTripStatus.ON_TRIP)

        self.close(employee)

        # Rabu ada tap susulan: tetap hadir, konteks perjalanannya dilepas.
        self.tap(employee, at(WEDNESDAY, 7, 50), WEDNESDAY)

        BusinessTripService.complete(
            trip=trip,
            actual_return=at(TUESDAY, 16),
        )

        rows = self.rows(employee)

        self.assertEqual(rows[MONDAY].status, AttendanceStatus.BUSINESS_TRIP)
        self.assertEqual(rows[TUESDAY].status, AttendanceStatus.BUSINESS_TRIP)

        self.assertEqual(rows[WEDNESDAY].status, AttendanceStatus.PRESENT)
        self.assertIsNone(rows[WEDNESDAY].business_trip_id)

        # Kamis–Jumat: dicabut lalu ditutup ulang dengan aturan biasa.
        self.assertEqual(rows[THURSDAY].status, AttendanceStatus.ABSENT)
        self.assertEqual(rows[FRIDAY].status, AttendanceStatus.ABSENT)
        self.assertIsNone(rows[THURSDAY].business_trip_id)

        # Baris lamanya soft-deleted, bukan hilang.
        self.assertTrue(
            EmployeeAttendance.objects.filter(
                employee=employee,
                work_date=THURSDAY,
                is_deleted=True,
                business_trip=trip,
            ).exists(),
        )

    def test_cancel_revokes_trip_rows_from_the_cancellation_date(self):
        employee = self.make_employee()
        today = timezone.localtime(timezone.now(), WALL).date()
        tomorrow = today + timedelta(days=1)
        later = today + timedelta(days=10)

        trip = self.make_trip(employee, start=tomorrow, end=later)

        # Penutup hari yang dijalankan untuk tanggal depan (lewat perintah
        # dengan `--end` eksplisit) menulis baris dinas lebih dulu.
        self.close(employee, tomorrow, later)

        self.assertIn(
            AttendanceStatus.BUSINESS_TRIP,
            set(self.statuses(employee).values()),
        )

        type(self)._counter += 1

        admin = get_user_model().objects.create_user(
            username=f"bt3.admin{self._counter}",
            email=f"bt3.admin{self._counter}@example.test",
            password="Test-Only#Pw1",
            is_superuser=True,
        )

        BusinessTripService.cancel(trip=trip, user=admin, reason="Batal")

        self.assertNotIn(
            AttendanceStatus.BUSINESS_TRIP,
            set(self.statuses(employee).values()),
        )
        self.assertTrue(
            EmployeeAttendance.objects.filter(
                employee=employee,
                business_trip=trip,
                is_deleted=True,
            ).exists(),
        )

        # Diulang: tidak ada yang berubah lagi.
        trip.refresh_from_db()
        self.assertEqual(reconcile_attendance(trip)["revoked"], 0)

    # ------------------------------------------------------------------
    # BT-3R — pelaporan: dinas bukan kehadiran fisik
    # ------------------------------------------------------------------
    #
    # Baris presensinya dibuat jalur sesungguhnya (penutup hari + tap
    # import), lalu dibaca ketiga penyaji: HR Period Summary, HR
    # Dashboard, dan Self Service. Ketiganya harus menyebut angka yang
    # sama.

    @staticmethod
    def report_row(employee, start=MONDAY, end=FRIDAY):
        from apps.reports.api.hr.period_summary.services import (
            HRPeriodSummaryService,
        )

        return HRPeriodSummaryService.build_for([employee], start, end).rows[0]

    def dashboard_context(self, employee, start=MONDAY, end=FRIDAY) -> dict:
        organization = employee.organization

        return {
            "user": None,
            "company": organization.company_id,
            "period": {
                "start": start,
                "end": end,
                "year": start.year,
                "mode": "custom",
                "previous": {"start": start, "end": end},
            },
        }

    @staticmethod
    def self_service(employee, start=MONDAY, end=FRIDAY) -> dict:
        from apps.self_service.services.attendance import SelfAttendanceService

        data, _ = SelfAttendanceService.build(
            employee=employee,
            date_from=start.isoformat(),
            date_to=end.isoformat(),
        )

        return data

    def trip_week_with_taps(self):
        """
        Senin–Kamis dinas, Jumat tanpa apa pun.

        Senin tap tepat waktu → PRESENT, Selasa tap terlambat → LATE,
        Rabu–Kamis tanpa tap → BUSINESS_TRIP, Jumat → ABSENT.
        """
        employee = self.make_employee()
        self.make_trip(employee, start=MONDAY, end=THURSDAY)

        self.close(employee)
        self.tap(employee, at(MONDAY, 7, 55), MONDAY)
        self.tap(employee, at(TUESDAY, 9), TUESDAY)

        self.assertEqual(
            self.statuses(employee),
            {
                MONDAY: AttendanceStatus.PRESENT,
                TUESDAY: AttendanceStatus.LATE,
                WEDNESDAY: AttendanceStatus.BUSINESS_TRIP,
                THURSDAY: AttendanceStatus.BUSINESS_TRIP,
                FRIDAY: AttendanceStatus.ABSENT,
            },
        )

        return employee

    def test_report_present_is_physical_and_trip_is_its_own_metric(self):
        """Case A + B: 1 PRESENT + 1 LATE + 2 BUSINESS_TRIP → Present 2, bukan 4."""
        from apps.reports.api.hr.period_summary.metrics import Metric

        employee = self.trip_week_with_taps()

        row = self.report_row(employee)

        self.assertEqual(row.scheduled, 5)
        self.assertEqual(row.present, 2)
        self.assertEqual(row.business_trip, 2)
        self.assertEqual(row.absent, 1)
        self.assertEqual(row.late, 1)

        # Tap di hari dinas dihitung sekali, sebagai hadir.
        self.assertEqual(row.days_by_metric[Metric.PRESENT], [MONDAY, TUESDAY])
        self.assertEqual(
            row.days_by_metric[Metric.BUSINESS_TRIP],
            [WEDNESDAY, THURSDAY],
        )
        self.assertEqual(
            row.scheduled,
            row.present + row.business_trip + row.absent + int(row.leave_total),
        )

    def test_dashboard_does_not_count_trip_days_as_present_or_absent(self):
        from apps.hr.api.dashboard.services import HRDashboardService

        employee = self.trip_week_with_taps()
        context = self.dashboard_context(employee)

        # Present ÷ (Present + Absent) = 2 ÷ 3 — sama dengan laporan.
        self.assertEqual(
            HRDashboardService.attendance_rate(context, MONDAY, FRIDAY),
            66.67,
        )

        trend = HRDashboardService.attendance_trend(context)
        totals = {
            dataset["label"]: sum(dataset["data"])
            for dataset in trend["datasets"]
        }

        self.assertEqual(totals, {"Hadir": 1, "Telat": 1, "Tidak Hadir": 1})

    def test_self_service_present_excludes_trip_days(self):
        employee = self.trip_week_with_taps()

        data = self.self_service(employee)
        summary = data["summary"]

        self.assertEqual(summary["work_days"]["value"], 5)
        self.assertEqual(summary["present"]["value"], 2)
        self.assertEqual(summary["late"]["value"], 1)
        self.assertEqual(summary["absent"]["value"], 1)
        self.assertEqual(
            summary["business_trip"],
            {"value": 2, "available": True},
        )

        self.assertEqual(
            [day["outcome"] for day in data["daily"]],
            ["present", "late", "business_trip", "business_trip", "absent"],
        )

    def test_trip_only_day_is_business_trip_not_present_not_absent(self):
        """Case C."""
        employee = self.make_employee()
        self.make_trip(employee, start=MONDAY, end=MONDAY)

        self.close(employee, MONDAY, MONDAY)

        row = self.report_row(employee, MONDAY, MONDAY)

        self.assertEqual(
            (row.scheduled, row.present, row.business_trip, row.absent),
            (1, 0, 1, 0),
        )

        summary = self.self_service(employee, MONDAY, MONDAY)["summary"]

        self.assertEqual(summary["present"]["value"], 0)
        self.assertEqual(summary["absent"]["value"], 0)
        self.assertEqual(summary["business_trip"]["value"], 1)

        from apps.hr.api.dashboard.services import HRDashboardService

        # Tidak ada peluang hadir fisik sama sekali — bukan 0%.
        self.assertIsNone(
            HRDashboardService.attendance_rate(
                self.dashboard_context(employee, MONDAY, MONDAY),
                MONDAY,
                MONDAY,
            ),
        )

    def test_report_leave_permission_and_weekend_unchanged_on_trip(self):
        """Case D: cuti, izin sehari penuh, dan akhir pekan tetap seperti BT-3."""
        sick = self.make_employee()
        self.make_trip(sick)
        EmployeeLeave.objects.create(
            employee=sick,
            company=self.company,
            location=self.head_office,
            leave_type=self.sick,
            start_date=WEDNESDAY,
            end_date=WEDNESDAY,
            total_days=1,
            status=LeaveStatus.APPROVED,
        )
        self.close(sick)

        row = self.report_row(sick)

        self.assertEqual(row.leave_total, 1)
        self.assertEqual((row.present, row.business_trip, row.absent), (0, 4, 0))

        permitted = self.make_employee()
        self.make_trip(permitted)
        AttendancePermission.objects.create(
            employee=permitted,
            company=self.company,
            permission_type=AttendancePermissionType.FULL_DAY,
            date=THURSDAY,
            reason="Urusan keluarga",
            status=AttendancePermissionStatus.APPROVED,
        )
        self.close(permitted)

        row = self.report_row(permitted)

        # Baris alpa yang dijelaskan izin tetap Absent di laporan.
        self.assertEqual((row.present, row.business_trip, row.absent), (0, 4, 1))

        weekend = self.make_employee()
        self.make_trip(weekend, start=FRIDAY, end=NEXT_MONDAY)
        self.close(weekend, FRIDAY, NEXT_MONDAY)

        row = self.report_row(weekend, FRIDAY, NEXT_MONDAY)

        self.assertEqual(row.scheduled, 2)
        self.assertEqual(row.business_trip, 2)
        self.assertEqual((row.off_worked, row.holiday_worked), (0, 0))
