"""
HR Period Summary — Business Trip bukan kehadiran fisik (BT-3R).

Yang dikunci di tingkat status (baris diketik langsung, tanpa dokumen
perjalanan — jalur penutup hari + tap diuji di
`apps/hr/tests/business_trip/test_attendance_integration.py`):

* Present = PRESENT / LATE / REMOTE, plus baris dinas yang punya tap;
* baris dinas tanpa tap = metrik Business Trip sendiri, di hari
  terjadwal maupun tidak — tidak pernah Present, Absent, atau Off Worked;
* tabel, baris Total, drill-down, dan Attendance Rate membaca
  klasifikasi yang sama;
* cuti, mangkir, hari off, dan hari libur tidak berubah.
"""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from apps.reports.api.hr.period_summary.drilldown import HRPeriodSummaryDrilldown
from apps.reports.api.hr.period_summary.metrics import (
    DRILLDOWN_METRICS,
    Metric,
)
from apps.reports.api.hr.period_summary.schema import TABLE_WIDGET
from apps.reports.api.hr.period_summary.services import (
    HRPeriodSummaryPresenter,
    HRPeriodSummaryService,
)
from apps.hr.models.attendance.choices import AttendanceStatus

from .base import PERIOD_END, PERIOD_START, PeriodSummaryTestCase


WALL = ZoneInfo("Asia/Jakarta")

# Juni 2026: Senin 1 Juni; Sabtu 6, Minggu 7; libur perusahaan Rabu 17.
MON, TUE, WED, THU, FRI = (date(2026, 6, day) for day in range(1, 6))
SAT, SUN = date(2026, 6, 6), date(2026, 6, 7)


class BusinessTripReportingTests(PeriodSummaryTestCase):

    def build(self, employee):
        return HRPeriodSummaryService.build(
            self.context(employee),
            PERIOD_START,
            PERIOD_END,
        )

    def trip_row(self, employee, day, *, tapped=False):
        row = self.make_attendance(
            employee,
            day,
            status=AttendanceStatus.BUSINESS_TRIP,
        )

        if tapped:
            row.check_in = datetime(day.year, day.month, day.day, 8, tzinfo=WALL)
            row.save(update_fields=["check_in"])

        return row

    # ------------------------------------------------------------------

    def test_present_late_remote_count_trip_does_not(self):
        employee = self.make_office_employee()

        self.make_attendance(employee, MON)
        self.make_attendance(
            employee, TUE, status=AttendanceStatus.LATE, late_minutes=15,
        )
        # REMOTE sudah Present sebelum BT-3R; tidak disentuh.
        self.make_attendance(employee, WED, status=AttendanceStatus.REMOTE)
        self.trip_row(employee, THU)
        self.trip_row(employee, FRI)

        row = self.row(self.build(employee), employee)

        self.assertEqual(row.present, 3)
        self.assertEqual(row.business_trip, 2)
        self.assertEqual(row.late, 1)
        self.assertEqual(row.days_by_metric[Metric.BUSINESS_TRIP], [THU, FRI])
        self.assertNotIn(THU, row.days_by_metric[Metric.PRESENT])
        self.assertNotIn(THU, row.days_by_metric.get(Metric.ABSENT, []))

        # Seluruh hari terjadwal tetap terbagi habis, tanpa hitung ganda.
        self.assertEqual(
            row.scheduled,
            row.present + row.business_trip + row.absent + int(row.leave_total),
        )

    def test_trip_row_with_a_tap_is_present_once(self):
        """Sama dengan payroll: baris dinas yang punya `check_in` = hadir."""
        employee = self.make_office_employee()

        self.trip_row(employee, MON, tapped=True)

        row = self.row(self.build(employee), employee)

        self.assertIn(MON, row.days_by_metric[Metric.PRESENT])
        self.assertEqual(row.business_trip, 0)

    def test_trip_on_an_off_day_is_business_trip_not_off_worked(self):
        employee = self.make_office_employee()

        self.trip_row(employee, SAT)
        # Kerja fisik di hari off / libur: tidak berubah.
        self.make_attendance(employee, SUN)
        self.make_attendance(employee, self.holiday_date)

        row = self.row(self.build(employee), employee)

        self.assertEqual(row.business_trip, 1)
        self.assertEqual(row.days_by_metric[Metric.BUSINESS_TRIP], [SAT])
        self.assertEqual(row.off_worked, 1)
        self.assertEqual(row.days_by_metric[Metric.OFF_WORKED], [SUN])
        self.assertEqual(row.holiday_worked, 1)
        self.assertNotIn(SAT, row.days_by_metric.get(Metric.PRESENT, []))

    def test_leave_and_absence_unchanged(self):
        employee = self.make_office_employee()

        self.trip_row(employee, MON)
        self.make_leave(employee, leave_type=self.annual, start=TUE, end=TUE)
        self.make_attendance(employee, WED, status=AttendanceStatus.ABSENT)

        row = self.row(self.build(employee), employee)

        self.assertEqual(row.leave(Metric.ANNUAL), 1)
        self.assertIn(TUE, row.days_by_metric[Metric.ANNUAL])
        self.assertIn(WED, row.days_by_metric[Metric.ABSENT])
        self.assertEqual(row.business_trip, 1)
        self.assertEqual(row.present, 0)
        # Sisa hari terjadwal tanpa baris tetap Absent.
        self.assertEqual(row.absent, row.scheduled - 2)

    # ------------------------------------------------------------------
    # Penyaji
    # ------------------------------------------------------------------

    def test_table_totals_drilldown_and_rate_read_the_same_split(self):
        employee = self.make_office_employee()

        self.make_attendance(employee, MON)
        self.trip_row(employee, TUE)
        self.trip_row(employee, WED)

        context = self.context(employee)

        table = HRPeriodSummaryPresenter.employee_table(context)

        self.assertEqual(table["items"][0][Metric.BUSINESS_TRIP], 2)
        self.assertEqual(table["items"][0][Metric.PRESENT], 1)
        self.assertEqual(table["totals"][Metric.BUSINESS_TRIP], 2.0)

        detail = HRPeriodSummaryDrilldown.resolve(
            context,
            metric=Metric.BUSINESS_TRIP,
            employee_id=employee.id,
        )

        self.assertEqual(detail["total"], 2.0)
        self.assertEqual([item["date"] for item in detail["items"]], [TUE, WED])
        self.assertEqual(
            {item["status"] for item in detail["items"]},
            {AttendanceStatus.BUSINESS_TRIP},
        )
        self.assertEqual(detail["source_code"], "attendance")

        # Present ÷ (Present + Absent): hari dinas di luar keduanya.
        summary = HRPeriodSummaryService.summary(context)
        row = self.row(summary, employee)

        self.assertEqual(
            HRPeriodSummaryPresenter._attendance_rate(summary),
            round(1 / (1 + row.absent) * 100, 2),
        )

    def test_business_trip_is_a_drillable_table_column(self):
        self.assertIn(Metric.BUSINESS_TRIP, DRILLDOWN_METRICS)

        columns = {
            column["key"]: column
            for column in TABLE_WIDGET["columns"]
        }

        self.assertEqual(
            columns[Metric.BUSINESS_TRIP]["drilldown"],
            Metric.BUSINESS_TRIP,
        )
