"""
Pabrik data bersama untuk test HR Period Summary.

`TenantTestCase` django-tenants tidak memanggil rollback per-test dan
`setUpTestData` tidak pernah jalan, jadi tiap test membuat pegawainya
sendiri dan hanya membaca miliknya — pola yang sama dengan
`apps/hr/tests/travel_request/base.py`. Kalau tidak, urutan eksekusi
yang menentukan hasilnya.

Dua pegawai contoh yang dipakai berulang:

* **HO** — WorkCalendar Senin–Jumat, satu hari libur perusahaan.
* **Site** — roster: blok WORK, blok FIELD_BREAK.

Keduanya harus ada di hampir setiap test karena justru di situ letak
seluruh perbedaannya: hari terjadwal pegawai kantor datang dari
kalender, milik pegawai site datang dari baris roster yang berlaku.
"""

from __future__ import annotations

from datetime import date, timedelta

from django_tenants.test.cases import TenantTestCase

from apps.administration.models import (
    Company,
    Holiday,
    LeaveType,
    Location,
    OvertimeType,
    RosterCrew,
    WorkCalendar,
    WorkSchedule,
)
from apps.hr.models import (
    Employee,
    EmployeeAttendance,
    EmployeeLeave,
    EmployeeOvertime,
    EmploymentAssignment,
    LeaveStatus,
    OrganizationAssignment,
    RosterSegmentType,
    RotationPeriod,
    RotationPeriodType,
    SiteRotation,
)
from apps.hr.models.attendance.choices import (
    AttendanceSource,
    AttendanceStatus,
)


# Periode uji: Juni 2026.
#
# Sengaja bukan bulan berjalan — kartu KPI menyembunyikan bucket chart
# yang belum terjadi, dan bulan yang separuhnya di masa depan membuat
# assertion soal chart bergantung pada tanggal saat test dijalankan.
PERIOD_START = date(2026, 6, 1)
PERIOD_END = date(2026, 6, 30)


class PeriodSummaryTestCase(TenantTestCase):
    _counter = 0

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "reports-hr"
        tenant.name = "Reports HR"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.company = Company.objects.create(
            code="RPT",
            name="Report Test",
        )

        cls.ho = Location.objects.create(
            company=cls.company,
            code="RPT-HO",
            name="Jakarta HO",
        )

        cls.site = Location.objects.create(
            company=cls.company,
            code="RPT-SITE",
            name="Gebe Site",
        )

        # Senin–Jumat. Bawaan model sudah begitu, tapi ditulis eksplisit
        # supaya test tidak diam-diam berubah artinya kalau bawaannya
        # digeser.
        cls.calendar = WorkCalendar.objects.create(
            company=cls.company,
            code="RPT-CAL",
            name="Kantor Senin-Jumat",
            monday=True,
            tuesday=True,
            wednesday=True,
            thursday=True,
            friday=True,
            saturday=False,
            sunday=False,
            is_default=True,
        )

        # Rabu, 17 Juni 2026 — hari kerja menurut kalender, jadi
        # keberadaannya benar-benar mengurangi hari terjadwal.
        cls.holiday_date = date(2026, 6, 17)

        Holiday.objects.create(
            company=cls.company,
            date=cls.holiday_date,
            code="RPT-HOL",
            name="Libur Perusahaan",
        )

        cls.annual = LeaveType.objects.create(code="ANNUAL", name="Cuti Tahunan")
        cls.sick = LeaveType.objects.create(code="SICK", name="Cuti Sakit")
        cls.unpaid = LeaveType.objects.create(code="UNPAID", name="Cuti Tanpa Upah")
        cls.marriage = LeaveType.objects.create(code="MARRIAGE", name="Cuti Menikah")

        cls.overtime_type = OvertimeType.objects.create(
            code="RPT-WD",
            name="Lembur Hari Kerja",
        )

        # `WorkSchedule` adalah `BaseReference` — tidak punya company.
        # Pola siklusnya diisi supaya `EmploymentAssignment.clean()`
        # tetap lolos kalau suatu saat test memanggilnya.
        cls.roster_schedule = WorkSchedule.objects.create(
            code="RPT-ROSTER",
            name="Roster 14/7",
            schedule_type=WorkSchedule.ScheduleType.ROSTER,
            cycle_work_days=14,
            cycle_off_days=7,
        )

        cls.crew = RosterCrew.objects.create(
            company=cls.company,
            location=cls.site,
            work_schedule=cls.roster_schedule,
            code="RPT-CREW",
            name="Crew A",
            cycle_start_date=PERIOD_START,
        )

    # ------------------------------------------------------------------
    # Pegawai
    # ------------------------------------------------------------------

    @classmethod
    def _next(cls) -> int:
        cls._counter += 1

        return cls._counter

    @classmethod
    def make_office_employee(cls, **employment) -> Employee:
        index = cls._next()

        employee = Employee.objects.create(
            employee_number=f"HO{index:04d}",
            first_name="Kantor",
            last_name=f"Pegawai {index}",
        )

        OrganizationAssignment.objects.create(
            employee=employee,
            company=cls.company,
            location=cls.ho,
            organization_effective_date=date(2025, 1, 1),
        )

        EmploymentAssignment.objects.create(
            employee=employee,
            join_date=employment.pop("join_date", date(2025, 1, 1)),
            working_calendar=cls.calendar,
            **employment,
        )

        return Employee.objects.get(pk=employee.pk)

    @classmethod
    def make_site_employee(cls, **employment) -> Employee:
        index = cls._next()

        employee = Employee.objects.create(
            employee_number=f"ST{index:04d}",
            first_name="Site",
            last_name=f"Pegawai {index}",
        )

        OrganizationAssignment.objects.create(
            employee=employee,
            company=cls.company,
            location=cls.site,
            organization_effective_date=date(2025, 1, 1),
        )

        EmploymentAssignment.objects.create(
            employee=employee,
            join_date=employment.pop("join_date", date(2025, 1, 1)),
            roster_crew=cls.crew,
            work_schedule=cls.roster_schedule,
            **employment,
        )

        return Employee.objects.get(pk=employee.pk)

    # ------------------------------------------------------------------
    # Roster
    # ------------------------------------------------------------------

    @classmethod
    def make_segment(
        cls,
        employee,
        *,
        segment_type: str,
        start: date,
        end: date,
        rotation=None,
    ) -> RotationPeriod:
        rotation = rotation or cls.make_rotation(employee)

        return RotationPeriod.objects.create(
            rotation=rotation,
            employee=employee,
            sequence=RotationPeriod.objects.filter(employee=employee).count() + 1,
            period_type=(
                RotationPeriodType.WORK
                if segment_type == RosterSegmentType.WORK
                else RotationPeriodType.OFF
            ),
            segment_type=segment_type,
            start_date=start,
            end_date=end,
            total_days=(end - start).days + 1,
            cycle_number=1,
        )

    @classmethod
    def make_rotation(cls, employee) -> SiteRotation:
        return SiteRotation.objects.create(
            employee=employee,
            company=cls.company,
            location=cls.site,
            cycle_work_days=14,
            cycle_off_days=7,
            cycle_travel_days=0,
            start_date=PERIOD_START,
            cycle_count=1,
        )

    # ------------------------------------------------------------------
    # Transaksi
    # ------------------------------------------------------------------

    @classmethod
    def make_attendance(
        cls,
        employee,
        day: date,
        *,
        status: str = AttendanceStatus.PRESENT,
        late_minutes: int = 0,
        early_leave_minutes: int = 0,
    ) -> EmployeeAttendance:
        organization = employee.organization

        return EmployeeAttendance.objects.create(
            employee=employee,
            company=organization.company,
            location=organization.location,
            work_date=day,
            status=status,
            source=AttendanceSource.MANUAL,
            late_minutes=late_minutes,
            early_leave_minutes=early_leave_minutes,
        )

    @classmethod
    def make_leave(
        cls,
        employee,
        *,
        leave_type,
        start: date,
        end: date,
        is_half_day: bool = False,
        status: str = LeaveStatus.RECORDED,
    ) -> EmployeeLeave:
        organization = employee.organization

        return EmployeeLeave.objects.create(
            employee=employee,
            company=organization.company,
            location=organization.location,
            leave_type=leave_type,
            start_date=start,
            end_date=end,
            is_half_day=is_half_day,
            total_days=(end - start).days + 1,
            status=status,
        )

    @classmethod
    def make_overtime(
        cls,
        employee,
        day: date,
        *,
        minutes: int,
    ) -> EmployeeOvertime:
        organization = employee.organization

        return EmployeeOvertime.objects.create(
            employee=employee,
            company=organization.company,
            location=organization.location,
            overtime_type=cls.overtime_type,
            work_date=day,
            start_time="18:00",
            end_time="21:00",
            duration_minutes=minutes,
        )

    # ------------------------------------------------------------------
    # Bantu
    # ------------------------------------------------------------------

    @staticmethod
    def context(employee=None, *, start=PERIOD_START, end=PERIOD_END) -> dict:
        """
        Context minimal yang biasanya dirakit `BaseDashboardAPIView`.

        `user=None` berarti tanpa cakupan data — `DataScopeService`
        melewatkan queryset apa adanya. Cakupan diuji tersendiri, dengan
        user sungguhan.
        """
        previous_end = start - timedelta(days=1)
        previous_start = previous_end.replace(day=1)

        context = {
            "user": None,
            "period": {
                "start": start,
                "end": end,
                "year": start.year,
                "month": start.month,
                "mode": "month",
                "compare_label": "dari bulan lalu",
                "previous": {
                    "start": previous_start,
                    "end": previous_end,
                },
            },
        }

        if employee is not None:
            context["employee"] = employee.id

        return context

    @staticmethod
    def row(summary, employee):
        for item in summary.rows:
            if item.employee_id == employee.id:
                return item

        raise AssertionError(
            f"{employee.employee_number} tidak ada di hasil laporan.",
        )
