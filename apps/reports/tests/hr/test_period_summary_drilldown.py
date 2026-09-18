"""
Drill-down HR Period Summary sebagai **bukti**, bukan daftar kedua.

Yang dijaga berkas ini:

* rekonsiliasi — angka di tabel == agregat drill-down, untuk kejadian
  (Late/Early), jam (OT), dan hari (cuti);
* durasi Late/Early dibaca dari menit milik `AttendancePolicyResolver`,
  **bukan** dari selisih jam jadwal dan jam tap;
* cakupan data — mengganti `employee_id` tidak membuka rincian pegawai
  di luar cakupan.

Satu kelas saja: tiap `TenantTestCase` membangun schema tenant sendiri.
"""

from __future__ import annotations

from datetime import date, datetime

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.accounts.models import AuthorityMode, DataScopeLevel, Role
from apps.accounts.services.role_assignment import grant_role
from apps.hr.api.attendance.schedule import WALL_CLOCK_TZ
from apps.hr.models import EmployeeAttendance
from apps.hr.models.attendance.choices import AttendanceStatus
from apps.hr.tests.access_helpers import grant_employee_read
from apps.reports.api.hr.period_summary.drilldown import (
    EmployeeNotVisible,
    HRPeriodSummaryDrilldown,
)
from apps.reports.api.hr.period_summary.metrics import Metric
from apps.reports.api.hr.period_summary.services import (
    HRPeriodSummaryPresenter,
    HRPeriodSummaryService,
)

from .base import PERIOD_END, PERIOD_START, PeriodSummaryTestCase


User = get_user_model()

URL = "/api/reports/hr/period-summary/drilldown/"


def wall(day: date, hour: int, minute: int) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=WALL_CLOCK_TZ)


# Juni 2026: tanggal 1 hari Senin; 17 Juni libur perusahaan.
MON = date(2026, 6, 1)
TUE = date(2026, 6, 2)
WED = date(2026, 6, 3)
THU = date(2026, 6, 4)
FRI = date(2026, 6, 5)
NEXT_MON = date(2026, 6, 8)


class PeriodSummaryDrilldownTests(PeriodSummaryTestCase):
    # ------------------------------------------------------------------
    # Bantu
    # ------------------------------------------------------------------

    def attend(self, employee, day, *, scheduled_in=None, check_in=None,
               scheduled_out=None, check_out=None, **kwargs):
        record = self.make_attendance(employee, day, **kwargs)

        # `update()`, bukan `save()`: yang diuji laporan ini, bukan
        # resolver kebijakannya — menit yang disimpan adalah faktanya.
        EmployeeAttendance.objects.filter(pk=record.pk).update(
            scheduled_check_in=scheduled_in,
            check_in=check_in,
            scheduled_check_out=scheduled_out,
            check_out=check_out,
        )

        return record

    def drill(self, employee, metric, **context):
        ctx = self.context(employee, **context)

        return HRPeriodSummaryDrilldown.resolve(
            ctx, metric=metric, employee_id=employee.id,
        )

    def table_value(self, employee, metric, **context):
        table = HRPeriodSummaryPresenter.employee_table(
            self.context(employee, **context),
        )

        return next(
            row for row in table["items"] if row["id"] == employee.id
        )[metric]

    # ------------------------------------------------------------------
    # Late / Early
    # ------------------------------------------------------------------

    def test_late_occurrences_reconcile_and_duration_is_canonical(self):
        employee = self.make_office_employee()

        # Selisih jam 27 menit, tapi resolver sudah memotong toleransi
        # 15 menit → 12. Yang benar 12.
        first = self.attend(
            employee, MON, status=AttendanceStatus.LATE, late_minutes=12,
            scheduled_in=wall(MON, 8, 0), check_in=wall(MON, 8, 27),
        )
        self.attend(
            employee, TUE, status=AttendanceStatus.LATE, late_minutes=15,
            scheduled_in=wall(TUE, 8, 0), check_in=wall(TUE, 8, 15),
        )
        self.attend(employee, WED)  # tepat waktu

        result = self.drill(employee, Metric.LATE)

        self.assertEqual(self.table_value(employee, Metric.LATE), 2)
        self.assertEqual(result["aggregate"], {"value": 2.0, "unit": "occurrence"})
        self.assertEqual(result["occurrences"], 2)
        self.assertEqual(result["total"], 2.0)
        self.assertEqual(result["duration_minutes"], 27)
        self.assertTrue(result["duration_complete"])
        self.assertEqual(result["source_code"], "attendance")
        self.assertEqual(result["detail_kind"], "late")
        self.assertEqual(result["employee"]["id"], employee.id)

        row = result["items"][0]

        self.assertEqual(row["date"], MON)
        self.assertEqual(row["scheduled_time"], "08:00")
        self.assertEqual(row["actual_time"], "08:27")
        self.assertEqual(row["duration_minutes"], 12)
        self.assertEqual(row["record_id"], first.id)
        self.assertEqual(row["row_unit"], "occurrence")
        # Kunci lama tetap ada.
        self.assertEqual(row["value"], 1.0)
        self.assertEqual(result["unit"], "days")
        self.assertEqual(result["source"], "Attendance")

    def test_late_without_recorded_minutes_is_counted_but_not_guessed(self):
        employee = self.make_office_employee()

        self.attend(
            employee, MON, status=AttendanceStatus.LATE, late_minutes=0,
            scheduled_in=wall(MON, 8, 0), check_in=wall(MON, 8, 40),
        )
        self.attend(employee, TUE, status=AttendanceStatus.LATE, late_minutes=10)

        result = self.drill(employee, Metric.LATE)

        self.assertEqual(result["occurrences"], 2)
        self.assertEqual(self.table_value(employee, Metric.LATE), 2)
        self.assertIsNone(result["items"][0]["duration_minutes"])
        self.assertEqual(result["duration_minutes"], 10)
        self.assertFalse(result["duration_complete"])

    def test_early_occurrences_reconcile_and_duration(self):
        employee = self.make_office_employee()

        # Selisih jam 18 menit; toleransi 10 → resolver menyimpan 8.
        self.attend(
            employee, THU, early_leave_minutes=8,
            scheduled_out=wall(THU, 17, 0), check_out=wall(THU, 16, 42),
        )
        self.attend(employee, FRI, early_leave_minutes=37)
        self.attend(employee, NEXT_MON)

        result = self.drill(employee, Metric.EARLY)

        self.assertEqual(self.table_value(employee, Metric.EARLY), 2)
        self.assertEqual(result["aggregate"], {"value": 2.0, "unit": "occurrence"})
        self.assertEqual(len(result["items"]), 2)
        self.assertEqual(result["duration_minutes"], 45)
        self.assertEqual(result["detail_kind"], "early")

        row = result["items"][0]

        self.assertEqual(row["scheduled_time"], "17:00")
        self.assertEqual(row["actual_time"], "16:42")
        self.assertEqual(row["duration_minutes"], 8)

    # ------------------------------------------------------------------
    # Jam
    # ------------------------------------------------------------------

    def test_overtime_hours_reconcile_exactly(self):
        employee = self.make_office_employee()

        self.make_overtime(employee, MON, minutes=240)
        self.make_overtime(employee, TUE, minutes=150)

        result = self.drill(employee, Metric.OT_REGULAR)

        self.assertEqual(self.table_value(employee, Metric.OT_REGULAR), 6.5)
        self.assertEqual(result["aggregate"], {"value": 6.5, "unit": "hour"})
        self.assertEqual(result["total"], 6.5)
        self.assertEqual(result["duration_minutes"], 390)
        self.assertEqual(
            sum(item["duration_minutes"] for item in result["items"]), 390,
        )

        row = result["items"][0]

        self.assertEqual(row["start_time"], "18:00")
        self.assertEqual(row["end_time"], "21:00")
        self.assertEqual(row["row_unit"], "hour")
        self.assertEqual(result["source_code"], "overtime")

    def test_overtime_rounding_follows_table_not_per_row(self):
        """Tiga lembur 20 menit: tabel 1,0 jam — dulu rincian 0,99."""
        employee = self.make_office_employee()

        for day in (MON, TUE, WED):
            self.make_overtime(employee, day, minutes=20)

        result = self.drill(employee, Metric.OT_REGULAR)

        self.assertEqual(self.table_value(employee, Metric.OT_REGULAR), 1.0)
        self.assertEqual(result["total"], 1.0)
        self.assertEqual(result["duration_minutes"], 60)

    def test_aggregate_without_employee_matches_footer_total(self):
        first = self.make_office_employee()
        second = self.make_office_employee()

        self.make_overtime(first, MON, minutes=20)
        self.make_overtime(second, MON, minutes=20)
        self.attend(first, TUE, status=AttendanceStatus.LATE, late_minutes=5)

        context = self.context()
        table = HRPeriodSummaryPresenter.employee_table(context)

        for metric in (Metric.OT_REGULAR, Metric.LATE, Metric.PRESENT):
            result = HRPeriodSummaryDrilldown.resolve(context, metric=metric)

            self.assertEqual(result["total"], table["totals"][metric], metric)

    # ------------------------------------------------------------------
    # Hari
    # ------------------------------------------------------------------

    def test_leave_days_reconcile(self):
        employee = self.make_office_employee()

        leave = self.make_leave(
            employee, leave_type=self.annual, start=MON, end=TUE,
        )
        self.make_leave(
            employee, leave_type=self.sick, start=WED, end=WED, is_half_day=True,
        )

        annual = self.drill(employee, Metric.ANNUAL)
        sick = self.drill(employee, Metric.SICK)

        self.assertEqual(self.table_value(employee, Metric.ANNUAL), 2.0)
        self.assertEqual(annual["aggregate"], {"value": 2.0, "unit": "day"})
        self.assertEqual(sum(item["quantity"] for item in annual["items"]), 2.0)
        self.assertIsNone(annual["duration_minutes"])
        self.assertEqual(annual["source_code"], "leave")

        row = annual["items"][0]

        self.assertEqual(row["record_id"], leave.id)
        self.assertEqual(row["detail_code"], "ANNUAL")
        self.assertEqual(row["range_start"], MON)
        self.assertEqual(row["range_end"], TUE)

        self.assertEqual(self.table_value(employee, Metric.SICK), 0.5)
        self.assertEqual(sick["total"], 0.5)
        self.assertEqual(sick["items"][0]["quantity"], 0.5)

    def test_off_worked_is_days_with_attendance_evidence(self):
        employee = self.make_office_employee()
        saturday = date(2026, 6, 6)

        record = self.attend(
            employee, saturday,
            check_in=wall(saturday, 9, 0), check_out=wall(saturday, 13, 0),
        )
        EmployeeAttendance.objects.filter(pk=record.pk).update(worked_minutes=240)

        result = self.drill(employee, Metric.OFF_WORKED)

        self.assertEqual(self.table_value(employee, Metric.OFF_WORKED), 1)
        self.assertEqual(result["aggregate"], {"value": 1.0, "unit": "day"})
        self.assertEqual(result["detail_kind"], "attendance_day")

        row = result["items"][0]

        self.assertEqual(row["record_id"], record.id)
        self.assertEqual(row["start_time"], "09:00")
        self.assertEqual(row["end_time"], "13:00")
        self.assertEqual(row["duration_minutes"], 240)

    def test_absent_reconciles(self):
        employee = self.make_office_employee()

        self.attend(employee, MON)

        result = self.drill(employee, Metric.ABSENT)
        value = self.table_value(employee, Metric.ABSENT)

        self.assertGreater(value, 0)
        self.assertEqual(result["occurrences"], value)
        self.assertEqual(result["total"], value)

    def test_zero_value_has_no_rows(self):
        employee = self.make_office_employee()

        self.attend(employee, MON)

        result = self.drill(employee, Metric.LATE)

        self.assertEqual(self.table_value(employee, Metric.LATE), 0)
        self.assertEqual(result["items"], [])
        self.assertEqual(result["total"], 0.0)
        self.assertEqual(result["duration_minutes"], 0)

    # ------------------------------------------------------------------
    # Periode
    # ------------------------------------------------------------------

    def test_date_filter_is_respected(self):
        employee = self.make_office_employee()

        self.attend(employee, MON, status=AttendanceStatus.LATE, late_minutes=10)
        self.attend(employee, NEXT_MON, status=AttendanceStatus.LATE, late_minutes=20)
        self.make_overtime(employee, NEXT_MON, minutes=60)

        narrow = {"start": PERIOD_START, "end": FRI}

        late = self.drill(employee, Metric.LATE, **narrow)
        overtime = self.drill(employee, Metric.OT_REGULAR, **narrow)

        self.assertEqual([item["date"] for item in late["items"]], [MON])
        self.assertEqual(late["duration_minutes"], 10)
        self.assertEqual(overtime["items"], [])
        self.assertEqual(late["period"], {"start": PERIOD_START, "end": FRI})

        full = self.drill(employee, Metric.LATE)

        self.assertEqual(full["occurrences"], 2)
        self.assertEqual(full["duration_minutes"], 30)

    # ------------------------------------------------------------------
    # Cakupan data
    # ------------------------------------------------------------------

    def make_scoped_user(self, employee):
        user = User.objects.create_user(
            username=f"drill{employee.id}", password="Uji#12345",
        )
        role = Role.objects.create(
            code=f"ROLE-DRILL-{employee.id}", name="Drill scope",
        )
        grant_employee_read(role)
        grant_role(
            user, role,
            mode=AuthorityMode.PLACEMENT,
            level=DataScopeLevel.LOCATION,
        )
        employee.user = user
        employee.save(update_fields=["user"])

        return user

    def client_for(self, user):
        client = APIClient(HTTP_HOST=self.tenant.get_primary_domain().domain)
        client.force_authenticate(user=user)

        return client

    def params(self, **extra):
        return {
            "mode": "custom",
            "start": PERIOD_START.isoformat(),
            "end": PERIOD_END.isoformat(),
            **extra,
        }

    def test_employee_outside_scope_is_rejected(self):
        viewer = self.make_office_employee()           # HO
        colleague = self.make_office_employee()        # HO
        outsider = self.make_site_employee()           # Site

        self.attend(colleague, MON, status=AttendanceStatus.LATE, late_minutes=9)
        self.attend(outsider, MON, status=AttendanceStatus.LATE, late_minutes=33)

        user = self.make_scoped_user(viewer)
        client = self.client_for(user)

        allowed = client.get(URL, self.params(metric="late", employee_id=colleague.id))

        self.assertEqual(allowed.status_code, 200, allowed.content)
        self.assertEqual(allowed.json()["data"]["duration_minutes"], 9)

        denied = client.get(URL, self.params(metric="late", employee_id=outsider.id))

        self.assertEqual(denied.status_code, 404)
        self.assertNotIn("33", denied.content.decode())

        missing = client.get(URL, self.params(metric="late", employee_id=999999))

        self.assertEqual(missing.status_code, 404)

        invalid = client.get(URL, self.params(metric="late", employee_id="1 OR 1=1"))

        self.assertEqual(invalid.status_code, 400)

        # Tanpa employee_id: agregat hanya berisi cakupan pemanggil.
        everyone = client.get(URL, self.params(metric="late")).json()["data"]
        ids = {item["employee_id"] for item in everyone["items"]}

        self.assertNotIn(outsider.id, ids)
        self.assertIn(colleague.id, ids)

    def test_employee_outside_scope_service_level(self):
        viewer = self.make_office_employee()
        outsider = self.make_site_employee()
        user = self.make_scoped_user(viewer)

        context = self.context()
        context["user"] = user

        with self.assertRaises(EmployeeNotVisible):
            HRPeriodSummaryDrilldown.resolve(
                context, metric=Metric.LATE, employee_id=outsider.id,
            )

        # Populasi yang dipakai sama dengan laporannya.
        self.assertNotIn(
            outsider.id,
            {row.employee_id for row in HRPeriodSummaryService.summary(context).rows},
        )
