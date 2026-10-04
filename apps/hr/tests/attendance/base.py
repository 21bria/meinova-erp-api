"""
Pabrik data bersama untuk test Attendance Import.

`TenantTestCase` django-tenants **tidak** memanggil `super().setUpClass()`
dengan rollback per-test, jadi tiap test membuat pegawainya sendiri dan
hanya membaca miliknya — pola yang sama dengan test Roster dan Travel
Request.
"""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from apps.core.testing.tenant import ReusableTenantTestCase

from apps.administration.models import Company, Location, RosterPolicy
from apps.administration.models.references.hr import EmployeeGroup
from apps.administration.models.references.hr_attendance import Shift
from apps.hr.models import (
    AttendanceDevice,
    AttendanceDeviceEmployee,
    Employee,
    EmploymentAssignment,
    OrganizationAssignment,
    RosterSegmentType,
    RotationPeriod,
    RotationPeriodType,
    SiteRotation,
)
from apps.imports.models import ImportProfile


FIXTURES = Path(__file__).resolve().parent / "fixtures"

MODULE = "hr/attendance"


class AttendanceImportTestCase(ReusableTenantTestCase):
    """
    Panggung impor presensi di atas schema yang **dipakai ulang**.

    Sebelum TEST-ISO-HR-0C tiap kelas yang menurunkannya membangun
    schema tenant sendiri (~230 tabel, ~90 detik). Pondasinya di bawah
    idempoten karena `build_baseline()` dipanggil sekali per kelas di
    atas schema yang isinya mungkin sudah ada.
    """

    reusable_schema_name = "fast_attendance_import"

    _counter = 0

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "attendance-import"
        tenant.name = "Attendance Import"

    @classmethod
    def build_baseline(cls):
        cls.company, _ = Company.objects.get_or_create(
            code="AIM",
            is_deleted=False,
            defaults={"name": "Attendance Import Co"},
        )

        cls.site, _ = Location.objects.get_or_create(
            code="AIM-SITE",
            is_deleted=False,
            defaults={"company": cls.company, "name": "Site"},
        )

        cls.other_site, _ = Location.objects.get_or_create(
            code="AIM-SITE-B",
            is_deleted=False,
            defaults={"company": cls.company, "name": "Site B"},
        )

        cls.policy, _ = RosterPolicy.objects.get_or_create(
            code="AIM-6-2",
            is_deleted=False,
            defaults={
                "company": cls.company,
                "location": cls.site,
                "name": "Roster 6:2",
                "cycle_work_days": 42,
                "cycle_off_days": 14,
                "default_travel_out_days": 1,
                "default_travel_in_days": 1,
                "rolling_horizon_months": 12,
            },
        )

        cls.office_shift, _ = Shift.objects.get_or_create(
            code="AIM-OFFICE",
            is_deleted=False,
            defaults={
                "name": "Office",
                "start_time": "10:00",
                "end_time": "18:00",
            },
        )

        cls.day_shift, _ = Shift.objects.get_or_create(
            code="AIM-DAY",
            is_deleted=False,
            defaults={
                "name": "Site Day",
                "start_time": "07:00",
                "end_time": "17:00",
            },
        )

        cls.night_shift, _ = Shift.objects.get_or_create(
            code="AIM-NIGHT",
            is_deleted=False,
            defaults={
                "name": "Site Night",
                "start_time": "19:00",
                "end_time": "07:00",
                "crosses_midnight": True,
            },
        )

        cls.no_attendance_group, _ = EmployeeGroup.objects.get_or_create(
            code="AIM-BOARD",
            is_deleted=False,
            defaults={
                "name": "No Attendance Group",
                "attendance_applicable": False,
            },
        )

    # ------------------------------------------------------------------
    # Pabrik data
    # ------------------------------------------------------------------

    @classmethod
    def make_employee(
        cls,
        *,
        number: str | None = None,
        roster: bool = False,
        shift=None,
        group=None,
        location=None,
        user=None,
    ) -> Employee:
        cls._counter += 1

        employee = Employee.objects.create(
            employee_number=number or f"AIM{cls._counter:04d}",
            first_name="Aim",
            last_name=f"Employee {cls._counter}",
            user=user,
        )

        OrganizationAssignment.objects.create(
            employee=employee,
            company=cls.company,
            location=location or cls.site,
            organization_effective_date=date(2026, 1, 1),
        )

        EmploymentAssignment.objects.create(
            employee=employee,
            join_date=date(2025, 1, 1),
            employee_group=group,
            roster_policy=cls.policy if roster else None,
            shift=shift,
        )

        return Employee.objects.get(pk=employee.pk)

    @classmethod
    def make_roster_days(
        cls,
        employee,
        *,
        start: date,
        days: int,
    ) -> RotationPeriod:
        """Satu blok WORK yang benar-benar ada barisnya, bukan rumus."""
        rotation = SiteRotation.objects.create(
            employee=employee,
            company=cls.company,
            location=cls.site,
            cycle_work_days=days,
            cycle_off_days=14,
            cycle_travel_days=0,
            start_date=start,
            cycle_count=1,
        )

        return RotationPeriod.objects.create(
            rotation=rotation,
            employee=employee,
            sequence=1,
            period_type=RotationPeriodType.WORK,
            segment_type=RosterSegmentType.WORK,
            start_date=start,
            end_date=start + timedelta(days=days - 1),
            total_days=days,
            cycle_number=1,
        )

    @classmethod
    def make_device(cls, code: str, *, profile=None) -> AttendanceDevice:
        return AttendanceDevice.objects.create(
            code=code,
            name=code,
            company=cls.company,
            location=cls.site,
            import_profile=profile,
        )

    @classmethod
    def map_device_employee(cls, device, external_id, employee):
        return AttendanceDeviceEmployee.objects.create(
            device=device,
            external_employee_id=external_id,
            employee=employee,
        )

    # ------------------------------------------------------------------
    # Profile
    # ------------------------------------------------------------------

    @classmethod
    def make_profile(cls, code: str, **overrides) -> ImportProfile:
        payload = {
            "module": MODULE,
            "name": code,
            "source_type": "csv",
            "delimiter": ",",
            "encoding": "utf-8-sig",
            "mapping": {},
            "value_mapping": {},
            "datetime_formats": [],
            "defaults": {},
            "options": {},
        }

        payload.update(overrides)

        return ImportProfile.objects.create(code=code, **payload)

    @classmethod
    def daily_profile(cls, code: str, **options_override) -> ImportProfile:
        """
        Profil rekap harian: satu baris = satu tanggal, dua kolom jam.

        Nama kolomnya (`ymd`, `no`, `work1`, `work2`) datang dari sini,
        bukan dari kode importer — itu inti mode ini.
        """
        attendance = {
            "timezone": "Asia/Jakarta",
            "row_mode": "daily_in_out",
            "date_formats": ["%Y/%m/%d"],
            "time_formats": ["%H:%M"],
            "identifier": {"column": "no"},
        }

        attendance.update(options_override)

        return cls.make_profile(
            code,
            delimiter=",",
            mapping={
                "employee_code": ["no"],
                "attendance_date": ["ymd"],
                "check_in": ["work1"],
                "check_out": ["work2"],
                "employee_name": ["name"],
            },
            options={"attendance": attendance},
        )

    @classmethod
    def site_profile(cls, code: str, **options_override) -> ImportProfile:
        """Profil yang menggambarkan file TAB mesin sidik jari."""
        attendance = {
            "timezone": "Asia/Jakarta",
            "event_mode": "raw_tap",
            "identifier": {"column": "No.ID"},
        }

        attendance.update(options_override)

        return cls.make_profile(
            code,
            delimiter="\t",
            mapping={
                "employee_code": ["no.id"],
                "log_time": ["tgl/waktu"],
                "employee_name": ["nama"],
            },
            datetime_formats=["%d/%m/%Y %H.%M.%S"],
            options={"attendance": attendance},
        )
