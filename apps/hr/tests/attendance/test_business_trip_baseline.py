"""
BT-1 — perilaku presensi yang **hari ini** menjadi pijakan Business Trip.

Kontrak BT-0B (`docs/claude/hr/business-trip.md` §0, §10) bersandar pada
tiga fakta. Berkas ini menguncinya sebelum BT-3 membangun di atasnya:

1. `AttendanceStatus.BUSINESS_TRIP` sudah ada, dan resolver kebijakan
   **tidak** menimpanya selama tidak ada tap; tap sungguhan menjadikannya
   PRESENT/LATE ("fakta fisik menang"). Karena itu `BUSINESS_TRIP`
   sengaja **tidak** ada di `NON_COMPUTED_STATUSES` — koreksi BT-0A yang
   disetujui.
2. Penutup hari menulis LEAVE untuk hari terjadwal yang tertutup cuti
   RECORDED/APPROVED, ABSENT untuk sisanya, dan tidak pernah menimpa
   baris yang sudah ada. Cakupan Business Trip di BT-3 meniru pola ini.
3. Tanpa Business Trip yang disetujui, penutup hari tidak pernah
   menulis `BUSINESS_TRIP`. (Sebelum BT-3 ia tidak mengenal perjalanan
   sama sekali; sejak BT-3 ia menulisnya hanya untuk tanggal yang
   diizinkan dokumen perjalanan — diuji di
   `apps/hr/tests/business_trip/test_attendance_integration.py`.)

Ketiga fakta ini tetap berlaku sesudah BT-3; yang berubah hanya
penjelasan poin 3.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.test import SimpleTestCase

from apps.administration.models import Company, LeaveType, Location, WorkCalendar
from apps.administration.models.references.hr_attendance import Shift
from apps.core.testing.tenant import ReusableTenantTestCase
from apps.hr.api.attendance.closing import AttendanceClosingService
from apps.hr.api.attendance.policy import (
    NON_COMPUTED_STATUSES,
    AttendancePolicyResolver,
    AttendanceRules,
)
from apps.hr.api.attendance.services import EmployeeAttendanceService
from apps.hr.models import (
    Employee,
    EmployeeAttendance,
    EmployeeLeave,
    EmploymentAssignment,
    LeaveStatus,
    OrganizationAssignment,
)
from apps.hr.models.attendance.choices import AttendanceStatus


WALL = ZoneInfo("Asia/Jakarta")

# Senin–Jumat dipatok, bukan dihitung dari hari ini.
MONDAY = date(2026, 3, 2)
FRIDAY = date(2026, 3, 6)


def at(day: date, hour: int, minute: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=WALL)


class BusinessTripStatusResolverContract(SimpleTestCase):
    """Fungsi murni — tanpa database."""

    rules = AttendanceRules(late_tolerance_minutes=0)

    def compute(self, *, status, check_in=None):
        return AttendancePolicyResolver.compute(
            rules=self.rules,
            scheduled_check_in=at(MONDAY, 8),
            scheduled_check_out=at(MONDAY, 17),
            check_in=check_in,
            check_out=None,
            status=status,
        )

    def test_business_trip_status_value(self):
        self.assertEqual(AttendanceStatus.BUSINESS_TRIP, "business_trip")

    def test_non_computed_statuses_are_exactly_these(self):
        """
        Himpunannya dikunci utuh. `BUSINESS_TRIP` **tidak** termasuk
        (keputusan BT-0B). Menambah/mengurangi anggota harus disengaja.
        """
        self.assertEqual(
            {str(status) for status in NON_COMPUTED_STATUSES},
            {
                AttendanceStatus.ABSENT,
                AttendanceStatus.LEAVE,
                AttendanceStatus.SICK,
                AttendanceStatus.PERMIT,
                AttendanceStatus.HOLIDAY,
                AttendanceStatus.DAY_OFF,
            },
        )

        self.assertNotIn(AttendanceStatus.BUSINESS_TRIP, NON_COMPUTED_STATUSES)

    def test_business_trip_without_tap_keeps_its_status(self):
        result = self.compute(status=AttendanceStatus.BUSINESS_TRIP)

        self.assertNotIn("status", result)

    def test_business_trip_with_on_time_tap_becomes_present(self):
        result = self.compute(
            status=AttendanceStatus.BUSINESS_TRIP,
            check_in=at(MONDAY, 8),
        )

        self.assertEqual(result["status"], AttendanceStatus.PRESENT)

    def test_business_trip_with_late_tap_becomes_late(self):
        result = self.compute(
            status=AttendanceStatus.BUSINESS_TRIP,
            check_in=at(MONDAY, 9),
        )

        self.assertEqual(result["status"], AttendanceStatus.LATE)
        self.assertEqual(result["late_minutes"], 60)

    def test_leave_with_tap_is_not_recomputed(self):
        """Pembanding: status yang memang non-computed tidak disentuh."""
        result = self.compute(
            status=AttendanceStatus.LEAVE,
            check_in=at(MONDAY, 9),
        )

        self.assertEqual(result, {})


class BusinessTripAttendanceBaselineTests(ReusableTenantTestCase):
    reusable_schema_name = "fast_bt1_attendance"

    _counter = 0

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "bt1-attendance"
        tenant.name = "BT-1 Attendance"

    @classmethod
    def build_baseline(cls):
        cls.company, _ = Company.objects.get_or_create(
            code="BTA",
            is_deleted=False,
            defaults={"name": "BT Attendance Co"},
        )

        cls.head_office, _ = Location.objects.get_or_create(
            code="BTA-HO",
            is_deleted=False,
            defaults={"company": cls.company, "name": "Jakarta HO"},
        )

        cls.calendar, _ = WorkCalendar.objects.get_or_create(
            code="BTA-OFFICE",
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
            code="BTA-DAY",
            is_deleted=False,
            defaults={
                "name": "Day 08-17",
                "start_time": time(8, 0),
                "end_time": time(17, 0),
                "crosses_midnight": False,
            },
        )

        cls.leave_type, _ = LeaveType.objects.get_or_create(
            code="BTA-ANNUAL",
            is_deleted=False,
            defaults={"name": "Annual"},
        )

    # ------------------------------------------------------------------

    @classmethod
    def make_employee(cls) -> Employee:
        cls._counter += 1

        employee = Employee.objects.create(
            employee_number=f"BTA{cls._counter:04d}",
            first_name="Trip",
            last_name=f"Employee {cls._counter}",
        )

        OrganizationAssignment.objects.create(
            employee=employee,
            company=cls.company,
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

    def make_row(self, employee, *, day=MONDAY, status=None, check_in=None):
        data = {
            "employee": employee,
            "work_date": day,
            "shift": self.day_shift,
            "scheduled_check_in": at(day, 8),
            "scheduled_check_out": at(day, 17),
            "check_in": check_in,
        }

        if status is not None:
            data["status"] = status

        return EmployeeAttendanceService.create(data=data)

    def make_leave(self, employee, *, start, end, status):
        return EmployeeLeave.objects.create(
            employee=employee,
            company=self.company,
            location=self.head_office,
            leave_type=self.leave_type,
            start_date=start,
            end_date=end,
            total_days=(end - start).days + 1,
            status=status,
        )

    @staticmethod
    def statuses(employee) -> dict[date, str]:
        return dict(
            EmployeeAttendance.objects
            .filter(employee=employee, is_deleted=False)
            .values_list("work_date", "status")
        )

    # ------------------------------------------------------------------
    # Baris BUSINESS_TRIP lewat service
    # ------------------------------------------------------------------

    def test_manual_business_trip_row_without_tap_is_kept(self):
        row = self.make_row(
            self.make_employee(),
            status=AttendanceStatus.BUSINESS_TRIP,
        )

        row.refresh_from_db()

        self.assertEqual(row.status, AttendanceStatus.BUSINESS_TRIP)
        self.assertIsNone(row.check_in)

    def test_business_trip_row_with_a_real_tap_becomes_present(self):
        row = self.make_row(
            self.make_employee(),
            status=AttendanceStatus.BUSINESS_TRIP,
            check_in=at(MONDAY, 7, 55),
        )

        row.refresh_from_db()

        self.assertEqual(row.status, AttendanceStatus.PRESENT)

    # ------------------------------------------------------------------
    # Penutup hari: pola cakupan cuti
    # ------------------------------------------------------------------

    def close(self, employee):
        return AttendanceClosingService.close(
            start=MONDAY,
            end=FRIDAY,
            employees=[employee.pk],
        )

    def test_closer_writes_leave_for_approved_or_recorded_leave(self):
        employee = self.make_employee()

        self.make_leave(
            employee,
            start=MONDAY,
            end=MONDAY + timedelta(days=1),
            status=LeaveStatus.APPROVED,
        )

        self.make_leave(
            employee,
            start=FRIDAY,
            end=FRIDAY,
            status=LeaveStatus.RECORDED,
        )

        result = self.close(employee)

        self.assertEqual(result["leave"], 3)
        self.assertEqual(result["absent"], 2)

        statuses = self.statuses(employee)

        self.assertEqual(statuses[MONDAY], AttendanceStatus.LEAVE)
        self.assertEqual(
            statuses[MONDAY + timedelta(days=1)],
            AttendanceStatus.LEAVE,
        )
        self.assertEqual(statuses[FRIDAY], AttendanceStatus.LEAVE)
        self.assertEqual(
            statuses[MONDAY + timedelta(days=2)],
            AttendanceStatus.ABSENT,
        )

    def test_submitted_leave_does_not_cover_the_day(self):
        employee = self.make_employee()

        self.make_leave(
            employee,
            start=MONDAY,
            end=MONDAY,
            status=LeaveStatus.SUBMITTED,
        )

        self.close(employee)

        self.assertEqual(
            self.statuses(employee)[MONDAY],
            AttendanceStatus.ABSENT,
        )

    def test_closer_rows_use_the_close_external_id(self):
        employee = self.make_employee()

        self.close(employee)

        row = EmployeeAttendance.objects.get(
            employee=employee,
            work_date=MONDAY,
            is_deleted=False,
        )

        self.assertEqual(
            row.external_id,
            f"CLOSE-{employee.employee_number}-{MONDAY:%Y%m%d}",
        )

    def test_leave_approved_after_closing_does_not_rewrite_absent(self):
        """
        Cuti tidak menulis ulang presensi: baris ABSENT yang sudah terbit
        tetap ABSENT, dan payroll yang menutupnya lewat tanggal
        (`absence_covered_by_leave`). BT-3 meniru pola ini.
        """
        employee = self.make_employee()

        self.close(employee)

        self.make_leave(
            employee,
            start=MONDAY,
            end=MONDAY,
            status=LeaveStatus.APPROVED,
        )

        self.close(employee)

        self.assertEqual(
            self.statuses(employee)[MONDAY],
            AttendanceStatus.ABSENT,
        )

    def test_closer_never_overwrites_a_business_trip_row(self):
        employee = self.make_employee()

        self.make_row(employee, status=AttendanceStatus.BUSINESS_TRIP)

        result = self.close(employee)

        self.assertEqual(result["absent"], 4)
        self.assertEqual(
            self.statuses(employee)[MONDAY],
            AttendanceStatus.BUSINESS_TRIP,
        )

    def test_closer_writes_only_absent_or_leave_today(self):
        """Tanpa Business Trip yang disetujui: hanya alpa atau cuti."""
        employee = self.make_employee()

        self.make_leave(
            employee,
            start=MONDAY,
            end=MONDAY,
            status=LeaveStatus.APPROVED,
        )

        self.close(employee)

        self.assertEqual(
            set(self.statuses(employee).values()),
            {AttendanceStatus.LEAVE, AttendanceStatus.ABSENT},
        )
