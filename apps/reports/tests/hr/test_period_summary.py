"""
HR Period Summary — angka yang keluar dari laporan.

Yang diuji bukan "service-nya jalan", melainkan **aturan mana yang
dipakainya**. Tiap test menyebut satu keputusan yang kalau berubah
diam-diam akan membuat laporan berbohong tanpa satu pun error:

* hari terjadwal datang dari roster/kalender, bukan Senin–Jumat tetap
* kerja di luar jadwal tidak menambah Present
* cuti dikelompokkan dari kode LeaveType, bukan dari nama
* field break bukan cuti
* kategori lembur mengikuti jenis harinya
"""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from apps.hr.models import LeaveStatus, RosterSegmentType
from apps.hr.models.attendance.choices import AttendanceStatus
from apps.reports.api.hr.period_summary.metrics import Metric
from apps.reports.api.hr.period_summary.services import (
    HRPeriodSummaryPresenter,
    HRPeriodSummaryService,
)

from .base import PERIOD_END, PERIOD_START, PeriodSummaryTestCase


def workdays(start: date, end: date, *, skip: set[date] | None = None) -> list[date]:
    """Senin–Jumat pada rentang, di luar tanggal yang dikecualikan."""
    skip = skip or set()

    days = []
    current = start

    while current <= end:
        if current.weekday() < 5 and current not in skip:
            days.append(current)

        current += timedelta(days=1)

    return days


class ScheduledDaysTests(PeriodSummaryTestCase):
    """
    Hari terjadwal — angka yang seluruh kolom lain bersandar padanya.
    """

    def test_office_employee_follows_work_calendar_minus_holidays(self):
        """
        Senin–Jumat dari `WorkCalendar`, **dikurangi hari libur**.

        Kalau hari liburnya ikut terhitung, orang yang tidak masuk di
        tanggal merah muncul sebagai mangkir — dan yang paling tertib
        justru yang angkanya paling jelek.
        """
        employee = self.make_office_employee()

        summary = HRPeriodSummaryService.build(
            self.context(employee),
            PERIOD_START,
            PERIOD_END,
        )

        expected = len(
            workdays(PERIOD_START, PERIOD_END, skip={self.holiday_date}),
        )

        self.assertEqual(self.row(summary, employee).scheduled, expected)

    def test_site_employee_follows_roster_segments(self):
        """
        Pegawai roster memakai baris `RotationPeriod` yang berlaku, bukan
        kalender kantor — dan **bukan** rumus siklusnya: roster boleh
        digeser tangan, dan begitu digeser rumusnya tidak lagi
        menggambarkan jadwal yang berlaku.
        """
        employee = self.make_site_employee()

        rotation = self.make_rotation(employee)

        self.make_segment(
            employee,
            segment_type=RosterSegmentType.WORK,
            start=date(2026, 6, 1),
            end=date(2026, 6, 14),
            rotation=rotation,
        )

        self.make_segment(
            employee,
            segment_type=RosterSegmentType.FIELD_BREAK,
            start=date(2026, 6, 15),
            end=date(2026, 6, 21),
            rotation=rotation,
        )

        summary = HRPeriodSummaryService.build(
            self.context(employee),
            PERIOD_START,
            PERIOD_END,
        )

        row = self.row(summary, employee)

        # 14 hari blok kerja — akhir pekan ikut, tanggal merah ikut.
        self.assertEqual(row.scheduled, 14)

        # Field break tetap kategorinya sendiri, tidak menyentuh cuti.
        self.assertEqual(row.field_break, 7)
        self.assertEqual(row.leave_total, Decimal("0"))

    def test_join_date_bounds_scheduled_days(self):
        """
        Yang baru masuk tanggal 15 tidak dijadwalkan tanggal 1–14.
        Tanpa pagar ini ia ditandai mangkir setengah bulan.
        """
        employee = self.make_office_employee(join_date=date(2026, 6, 15))

        summary = HRPeriodSummaryService.build(
            self.context(employee),
            PERIOD_START,
            PERIOD_END,
        )

        expected = len(
            workdays(
                date(2026, 6, 15),
                PERIOD_END,
                skip={self.holiday_date},
            ),
        )

        self.assertEqual(self.row(summary, employee).scheduled, expected)


class AttendanceClassificationTests(PeriodSummaryTestCase):
    def test_present_absent_and_leave_partition_scheduled(self):
        """
        Invariant utama: Scheduled = Present + Absent + Leave.

        Hari terjadwal **tanpa baris presensi sama sekali** ikut
        terhitung — di sistem ini ketidakhadiran memang berupa baris
        yang tidak ada, dan laporan yang cuma menjumlahkan baris yang
        ada tidak akan pernah bisa menampilkan angka mangkir.
        """
        employee = self.make_office_employee()

        days = workdays(PERIOD_START, PERIOD_END, skip={self.holiday_date})

        for day in days[:10]:
            self.make_attendance(employee, day)

        self.make_leave(
            employee,
            leave_type=self.annual,
            start=days[10],
            end=days[11],
        )

        summary = HRPeriodSummaryService.build(
            self.context(employee),
            PERIOD_START,
            PERIOD_END,
        )

        row = self.row(summary, employee)

        self.assertEqual(row.present, 10)
        self.assertEqual(row.leave(Metric.ANNUAL), Decimal("2"))
        self.assertEqual(row.absent, len(days) - 12)

        self.assertEqual(
            row.scheduled,
            row.present + row.absent + int(row.leave_total),
        )

    def test_late_and_early_are_counted_from_policy_minutes(self):
        employee = self.make_office_employee()

        days = workdays(PERIOD_START, PERIOD_END, skip={self.holiday_date})

        self.make_attendance(
            employee,
            days[0],
            status=AttendanceStatus.LATE,
            late_minutes=25,
        )

        self.make_attendance(
            employee,
            days[1],
            early_leave_minutes=40,
        )

        # Tepat waktu: tidak menambah keduanya.
        self.make_attendance(employee, days[2])

        summary = HRPeriodSummaryService.build(
            self.context(employee),
            PERIOD_START,
            PERIOD_END,
        )

        row = self.row(summary, employee)

        self.assertEqual(row.late, 1)
        self.assertEqual(row.early, 1)

        # Telat tetap hadir — bukan kategori ketiga.
        self.assertEqual(row.present, 3)

    def test_off_worked_does_not_inflate_present(self):
        """
        Kerja di hari off masuk kolomnya sendiri.

        Scheduled 21 / Present 21 / Off Worked 2 — **bukan** Present 23.
        Menambahkannya ke Present membuat tingkat kehadiran melewati
        100% dan menghapus satu-satunya angka yang menunjukkan orang itu
        dipanggil di hari liburnya.
        """
        employee = self.make_office_employee()

        days = workdays(PERIOD_START, PERIOD_END, skip={self.holiday_date})

        for day in days:
            self.make_attendance(employee, day)

        # Sabtu — bukan hari kerja menurut kalendernya.
        saturday = date(2026, 6, 6)

        self.assertEqual(saturday.weekday(), 5)

        self.make_attendance(employee, saturday)

        summary = HRPeriodSummaryService.build(
            self.context(employee),
            PERIOD_START,
            PERIOD_END,
        )

        row = self.row(summary, employee)

        self.assertEqual(row.scheduled, len(days))
        self.assertEqual(row.present, len(days))
        self.assertEqual(row.off_worked, 1)
        self.assertEqual(row.holiday_worked, 0)

    def test_holiday_worked_is_separate_from_off_worked(self):
        employee = self.make_office_employee()

        self.make_attendance(employee, self.holiday_date)

        summary = HRPeriodSummaryService.build(
            self.context(employee),
            PERIOD_START,
            PERIOD_END,
        )

        row = self.row(summary, employee)

        self.assertEqual(row.holiday_worked, 1)
        self.assertEqual(row.off_worked, 0)
        self.assertEqual(row.present, 0)

    def test_day_marked_holiday_leaves_scheduled_instead_of_becoming_absent(self):
        """
        Koreksi tangan "hari itu libur perusahaan" mengeluarkan harinya
        dari Scheduled, bukan menjadikannya mangkir. Aturan yang sama
        dengan `NON_WORKING_STATUSES` di dashboard HR.
        """
        employee = self.make_office_employee()

        days = workdays(PERIOD_START, PERIOD_END, skip={self.holiday_date})

        self.make_attendance(
            employee,
            days[0],
            status=AttendanceStatus.DAY_OFF,
        )

        summary = HRPeriodSummaryService.build(
            self.context(employee),
            PERIOD_START,
            PERIOD_END,
        )

        row = self.row(summary, employee)

        self.assertEqual(row.scheduled, len(days) - 1)
        self.assertEqual(row.absent, len(days) - 1)


class LeaveGroupingTests(PeriodSummaryTestCase):
    def test_leave_types_group_by_master_code(self):
        """
        ANNUAL / SICK / UNPAID punya kolomnya sendiri; sisanya jatuh ke
        "Other Leave" — pengelompokan **laporan**, bukan LeaveType baru.
        """
        employee = self.make_office_employee()

        days = workdays(PERIOD_START, PERIOD_END, skip={self.holiday_date})

        self.make_leave(
            employee,
            leave_type=self.annual,
            start=days[0],
            end=days[0],
        )
        self.make_leave(
            employee,
            leave_type=self.sick,
            start=days[1],
            end=days[1],
        )
        self.make_leave(
            employee,
            leave_type=self.unpaid,
            start=days[2],
            end=days[2],
        )
        self.make_leave(
            employee,
            leave_type=self.marriage,
            start=days[3],
            end=days[3],
        )

        summary = HRPeriodSummaryService.build(
            self.context(employee),
            PERIOD_START,
            PERIOD_END,
        )

        row = self.row(summary, employee)

        self.assertEqual(row.leave(Metric.ANNUAL), Decimal("1"))
        self.assertEqual(row.leave(Metric.SICK), Decimal("1"))
        self.assertEqual(row.leave(Metric.UNPAID), Decimal("1"))
        self.assertEqual(row.leave(Metric.OTHER_LEAVE), Decimal("1"))

        # Tipe aslinya tidak hilang — chart Leave Breakdown dan
        # drill-down tetap bisa menyebut "Cuti Menikah".
        self.assertIn("Cuti Menikah", summary.leave_by_type)

    def test_submitted_leave_is_not_counted(self):
        """
        Hanya RECORDED/APPROVED yang dihitung — daftar yang sama dengan
        yang memotong `LeaveBalance.used`. Pengajuan yang belum diputus
        tidak boleh sudah mengurangi apa pun.
        """
        employee = self.make_office_employee()

        days = workdays(PERIOD_START, PERIOD_END, skip={self.holiday_date})

        self.make_leave(
            employee,
            leave_type=self.annual,
            start=days[0],
            end=days[0],
            status=LeaveStatus.SUBMITTED,
        )

        summary = HRPeriodSummaryService.build(
            self.context(employee),
            PERIOD_START,
            PERIOD_END,
        )

        row = self.row(summary, employee)

        self.assertEqual(row.leave_total, Decimal("0"))
        self.assertEqual(row.absent, len(days))

    def test_half_day_leave_counts_as_half(self):
        employee = self.make_office_employee()

        days = workdays(PERIOD_START, PERIOD_END, skip={self.holiday_date})

        self.make_leave(
            employee,
            leave_type=self.annual,
            start=days[0],
            end=days[0],
            is_half_day=True,
        )

        summary = HRPeriodSummaryService.build(
            self.context(employee),
            PERIOD_START,
            PERIOD_END,
        )

        self.assertEqual(
            self.row(summary, employee).leave(Metric.ANNUAL),
            Decimal("0.5"),
        )

    def test_leave_outside_scheduled_days_is_not_counted(self):
        """
        Cuti yang jatuh di akhir pekan tidak memotong apa pun — aturan
        yang sama dengan `LeaveDayCalculator.count_working_days`.
        """
        employee = self.make_office_employee()

        saturday = date(2026, 6, 6)
        sunday = date(2026, 6, 7)

        self.make_leave(
            employee,
            leave_type=self.annual,
            start=saturday,
            end=sunday,
        )

        summary = HRPeriodSummaryService.build(
            self.context(employee),
            PERIOD_START,
            PERIOD_END,
        )

        self.assertEqual(
            self.row(summary, employee).leave(Metric.ANNUAL),
            Decimal("0"),
        )


class OvertimeTests(PeriodSummaryTestCase):
    def test_overtime_category_follows_day_type(self):
        """
        Regular / Off / Holiday OT ditentukan **jenis harinya**, dari
        resolver yang sama dengan Present / Off Worked / Holiday Worked
        — bukan dari `OvertimeType` master yang dipilih tangan.
        """
        employee = self.make_office_employee()

        monday = date(2026, 6, 1)
        saturday = date(2026, 6, 6)

        self.assertEqual(monday.weekday(), 0)
        self.assertEqual(saturday.weekday(), 5)

        self.make_overtime(employee, monday, minutes=180)
        self.make_overtime(employee, saturday, minutes=480)
        self.make_overtime(employee, self.holiday_date, minutes=120)

        summary = HRPeriodSummaryService.build(
            self.context(employee),
            PERIOD_START,
            PERIOD_END,
        )

        row = self.row(summary, employee)

        self.assertEqual(row.ot_regular_minutes, 180)
        self.assertEqual(row.ot_off_minutes, 480)
        self.assertEqual(row.ot_holiday_minutes, 120)
        self.assertEqual(row.ot_total_minutes, 780)

        self.assertEqual(row.metric(Metric.OT_TOTAL), 13.0)

    def test_roster_work_block_overtime_is_regular(self):
        """
        Lembur pegawai site di dalam blok kerjanya adalah Regular OT,
        walaupun tanggalnya Minggu. Rosternya yang jadi kalender.
        """
        employee = self.make_site_employee()

        rotation = self.make_rotation(employee)

        self.make_segment(
            employee,
            segment_type=RosterSegmentType.WORK,
            start=date(2026, 6, 1),
            end=date(2026, 6, 14),
            rotation=rotation,
        )

        sunday = date(2026, 6, 7)

        self.assertEqual(sunday.weekday(), 6)

        self.make_overtime(employee, sunday, minutes=240)

        summary = HRPeriodSummaryService.build(
            self.context(employee),
            PERIOD_START,
            PERIOD_END,
        )

        row = self.row(summary, employee)

        self.assertEqual(row.ot_regular_minutes, 240)
        self.assertEqual(row.ot_off_minutes, 0)


class FilterTests(PeriodSummaryTestCase):
    def test_location_filter_narrows_population(self):
        office = self.make_office_employee()
        site = self.make_site_employee()

        context = self.context()
        context["location"] = [self.ho.id]

        summary = HRPeriodSummaryService.build(
            context,
            PERIOD_START,
            PERIOD_END,
        )

        ids = {row.employee_id for row in summary.rows}

        self.assertIn(office.id, ids)
        self.assertNotIn(site.id, ids)

    def test_period_filter_excludes_records_outside_range(self):
        employee = self.make_office_employee()

        # Mei — di luar periode.
        self.make_overtime(employee, date(2026, 5, 4), minutes=300)

        summary = HRPeriodSummaryService.build(
            self.context(employee),
            PERIOD_START,
            PERIOD_END,
        )

        self.assertEqual(self.row(summary, employee).ot_total_minutes, 0)

    def test_employee_filter_returns_single_row(self):
        employee = self.make_office_employee()

        self.make_office_employee()

        summary = HRPeriodSummaryService.build(
            self.context(employee),
            PERIOD_START,
            PERIOD_END,
        )

        self.assertEqual(len(summary.rows), 1)
        self.assertEqual(summary.rows[0].employee_id, employee.id)

    def test_terminated_employee_stays_in_past_period(self):
        """
        Laporan bulan lalu tidak boleh berubah gara-gara ada yang resign
        minggu ini.
        """
        employee = self.make_office_employee()

        employment = employee.employment
        employment.termination_date = date(2026, 6, 20)
        employment.save(update_fields=["termination_date"])

        summary = HRPeriodSummaryService.build(
            self.context(employee),
            PERIOD_START,
            PERIOD_END,
        )

        row = self.row(summary, employee)

        expected = len(
            workdays(
                PERIOD_START,
                date(2026, 6, 20),
                skip={self.holiday_date},
            ),
        )

        self.assertEqual(row.scheduled, expected)


class ConsistencyTests(PeriodSummaryTestCase):
    """
    KPI = chart = tabel = drill-down, untuk filter dan periode yang sama.

    Ini invariant yang paling mudah pecah dan paling sulit terlihat:
    empat penyaji yang merakit querysetnya masing-masing akan sepakat
    hari ini dan berbeda tiga bulan lagi, tanpa satu pun error.
    """

    def _fixture(self):
        employee = self.make_office_employee()

        days = workdays(PERIOD_START, PERIOD_END, skip={self.holiday_date})

        for day in days[:12]:
            self.make_attendance(
                employee,
                day,
                status=(
                    AttendanceStatus.LATE if day == days[0] else AttendanceStatus.PRESENT
                ),
                late_minutes=15 if day == days[0] else 0,
            )

        self.make_leave(
            employee,
            leave_type=self.annual,
            start=days[12],
            end=days[13],
        )

        self.make_overtime(employee, days[0], minutes=120)
        self.make_overtime(employee, date(2026, 6, 6), minutes=300)

        return employee, days

    def test_kpi_matches_employee_table(self):
        employee, _ = self._fixture()

        context = self.context(employee)

        table = HRPeriodSummaryPresenter.employee_table(context)

        present_kpi = HRPeriodSummaryPresenter.metric_stat(
            context,
            Metric.PRESENT,
        )

        absent_kpi = HRPeriodSummaryPresenter.metric_stat(
            context,
            Metric.ABSENT,
        )

        overtime_kpi = HRPeriodSummaryPresenter.metric_stat(
            context,
            Metric.OT_TOTAL,
        )

        rows = table["items"]

        self.assertEqual(
            present_kpi["value"],
            sum(row[Metric.PRESENT] for row in rows),
        )

        self.assertEqual(
            absent_kpi["value"],
            sum(row[Metric.ABSENT] for row in rows),
        )

        self.assertAlmostEqual(
            overtime_kpi["value"],
            sum(row[Metric.OT_TOTAL] for row in rows),
            places=1,
        )

    def test_chart_matches_employee_table(self):
        employee, _ = self._fixture()

        context = self.context(employee)

        table = HRPeriodSummaryPresenter.employee_table(context)
        chart = HRPeriodSummaryPresenter.attendance_trend(context)

        by_label = {
            dataset["label"]: sum(dataset["data"])
            for dataset in chart["datasets"]
        }

        rows = table["items"]

        # "Hadir" di chart tidak mencakup yang telat; keduanya bersama
        # baru sama dengan kolom Present.
        self.assertEqual(
            by_label["Hadir"] + by_label["Telat"],
            sum(row[Metric.PRESENT] for row in rows),
        )

        self.assertEqual(
            by_label["Telat"],
            sum(row[Metric.LATE] for row in rows),
        )

        self.assertEqual(
            by_label["Tidak Hadir"],
            sum(row[Metric.ABSENT] for row in rows),
        )

    def test_overtime_chart_matches_employee_table(self):
        employee, _ = self._fixture()

        context = self.context(employee)

        table = HRPeriodSummaryPresenter.employee_table(context)
        chart = HRPeriodSummaryPresenter.overtime_trend(context)

        charted = sum(
            sum(dataset["data"]) for dataset in chart["datasets"]
        )

        self.assertAlmostEqual(
            charted,
            sum(row[Metric.OT_TOTAL] for row in table["items"]),
            places=1,
        )

    def test_table_footer_totals_match_rows(self):
        employee, _ = self._fixture()

        table = HRPeriodSummaryPresenter.employee_table(self.context(employee))

        for metric in (
            Metric.SCHEDULED,
            Metric.PRESENT,
            Metric.ABSENT,
            Metric.ANNUAL,
            Metric.OT_TOTAL,
        ):
            self.assertAlmostEqual(
                table["totals"][metric],
                sum(row[metric] for row in table["items"]),
                places=1,
                msg=f"Total kolom {metric} tidak cocok dengan barisnya.",
            )
