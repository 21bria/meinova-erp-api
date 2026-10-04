"""
Panggung bersama test Business Trip (BT-2).

Dua company (isolasi cakupan), dua lokasi di company pertama (kantor dan
site), dua Employee Group (Business Trip menyala / mati), alur dari seed
sungguhan `HR-BUSINESS-TRIP`, dan deret nomor dari seed sungguhan.

Tanggal:

* test tumpang-tindih dan aturan dokumen memakai tanggal **tetap** jauh
  di depan (`FAR`), supaya tidak jadi bom waktu;
* test berangkat/selesai/batal yang memang bergantung pada "hari ini"
  memakai tanggal **relatif** terhadap `wall_today()` — jam dinding
  Asia/Jakarta yang sama dengan yang dipakai service.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

from django.contrib.auth import get_user_model

from apps.accounts.models import Role
from apps.administration.models import (
    City,
    Company,
    Country,
    Department,
    LeaveType,
    Location,
    Position,
    Province,
)
from apps.administration.models.references.hr import EmployeeGroup
from apps.administration.seeds.numbering import seed_numbering
from apps.core.testing.tenant import ReusableTenantTestCase
from apps.hr.api.business_trip.overlap import WALL_CLOCK, wall_today
from apps.hr.api.business_trip.services import BusinessTripService
from apps.hr.models import (
    BusinessTripDestinationType,
    BusinessTripPurpose,
    BusinessTripStatus,
    Employee,
    EmploymentAssignment,
    OrganizationAssignment,
)
from apps.workflow.seeds import workflows as workflow_seed


JOIN_DATE = date(2024, 1, 1)

# Jauh di depan, dipatok. Senin.
FAR = date(2031, 3, 3)


def at(day: date, hour: int = 8, minute: int = 0) -> datetime:
    return datetime.combine(day, time(hour, minute), tzinfo=WALL_CLOCK)


class BusinessTripTestCase(ReusableTenantTestCase):
    reusable_schema_name = "fast_business_trip"

    _counter = 0

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "business-trip"
        tenant.name = "Business Trip"

    @classmethod
    def build_baseline(cls):
        seed_numbering()

        cls.company, _ = Company.objects.get_or_create(
            code="BTC",
            is_deleted=False,
            defaults={"name": "Business Trip Co"},
        )

        cls.other_company, _ = Company.objects.get_or_create(
            code="BTX",
            is_deleted=False,
            defaults={"name": "Other Co"},
        )

        cls.head_office, _ = Location.objects.get_or_create(
            code="BTC-HO",
            is_deleted=False,
            defaults={"company": cls.company, "name": "Jakarta HO"},
        )

        cls.site, _ = Location.objects.get_or_create(
            code="BTC-SITE",
            is_deleted=False,
            defaults={"company": cls.company, "name": "Kendari Site"},
        )

        cls.other_office, _ = Location.objects.get_or_create(
            code="BTX-HO",
            is_deleted=False,
            defaults={"company": cls.other_company, "name": "Other HO"},
        )

        cls.department, _ = Department.objects.get_or_create(
            code="BTC-OPS",
            is_deleted=False,
            defaults={"company": cls.company, "name": "Operations"},
        )

        cls.other_department, _ = Department.objects.get_or_create(
            code="BTC-FIN",
            is_deleted=False,
            defaults={"company": cls.company, "name": "Finance"},
        )

        cls.office_group, _ = EmployeeGroup.objects.get_or_create(
            code="BT-OFFICE",
            is_deleted=False,
            defaults={"name": "Office", "business_trip_applicable": True},
        )

        cls.site_group, _ = EmployeeGroup.objects.get_or_create(
            code="BT-SITE",
            is_deleted=False,
            defaults={"name": "Site Crew", "business_trip_applicable": False},
        )

        cls.country, _ = Country.objects.get_or_create(
            code="BTID",
            is_deleted=False,
            defaults={
                "name": "Indonesia",
                "phone_code": "62",
                "currency_code": "IDR",
            },
        )

        cls.abroad, _ = Country.objects.get_or_create(
            code="BTSG",
            is_deleted=False,
            defaults={
                "name": "Singapore",
                "phone_code": "65",
                "currency_code": "SGD",
            },
        )

        province, _ = Province.objects.get_or_create(
            code="BTSUL",
            is_deleted=False,
            defaults={"name": "Sulawesi Tenggara", "country": cls.country},
        )

        cls.city, _ = City.objects.get_or_create(
            code="BTKDI",
            is_deleted=False,
            defaults={"name": "Kendari", "province": province},
        )

        cls.leave_type, _ = LeaveType.objects.get_or_create(
            code="BT-ANNUAL",
            is_deleted=False,
            defaults={"name": "Annual"},
        )

        workflow_seed.seed()

    # ------------------------------------------------------------------
    # Pabrik data
    # ------------------------------------------------------------------

    @classmethod
    def make_employee(
        cls,
        *,
        company=None,
        location=None,
        department=None,
        group=None,
        reports_to=None,
        roles=None,
        with_user: bool = True,
    ) -> Employee:
        User = get_user_model()

        cls._counter += 1
        n = cls._counter

        company = company or cls.company

        user = None

        if with_user:
            username = f"bt.user{n}"

            user = User.objects.create_user(
                username=username,
                email=f"{username}@example.test",
                password="Test-Only#Pw1",
                first_name="Trip",
                last_name=f"Employee {n}",
            )

            if roles:
                user.roles.set(
                    Role.objects.filter(code__in=roles, is_deleted=False),
                )

        employee = Employee.objects.create(
            employee_number=f"BT{n:04d}",
            first_name="Trip",
            last_name=f"Employee {n}",
            user=user,
        )

        position = Position.objects.create(
            company=company,
            code=f"BT-POS{n}",
            name=f"Position {n}",
        )

        OrganizationAssignment.objects.create(
            employee=employee,
            company=company,
            location=location or (
                cls.head_office if company == cls.company else cls.other_office
            ),
            department=department if department is not None else (
                cls.department if company == cls.company else None
            ),
            position=position,
            reports_to=reports_to,
            organization_effective_date=JOIN_DATE,
        )

        EmploymentAssignment.objects.create(
            employee=employee,
            join_date=JOIN_DATE,
            employee_group=group or cls.office_group,
        )

        return Employee.objects.get(pk=employee.pk)

    @classmethod
    def trip_data(
        cls,
        employee=None,
        *,
        start: date = FAR,
        days: int = 5,
        destination=None,
        **extra,
    ) -> dict:
        data = {
            "destination_type": BusinessTripDestinationType.INTERNAL_LOCATION,
            "destination_location": destination or cls.site,
            "purpose_category": BusinessTripPurpose.SITE_VISIT,
            "purpose": "Inspeksi operasional site",
            "departure_datetime": at(start, 7),
            "return_datetime": at(start + timedelta(days=days - 1), 18),
        }

        if employee is not None:
            data["employee"] = employee

        data.update(extra)

        return data

    @classmethod
    def make_trip(cls, employee=None, *, user=None, **kwargs):
        return BusinessTripService.create(
            data=cls.trip_data(employee, **kwargs),
            user=user,
        )

    @staticmethod
    def set_status(trip, status, **extra):
        """Keadaan disetel langsung — untuk test yang bukan soal alurnya."""
        trip.status = status

        for key, value in extra.items():
            setattr(trip, key, value)

        trip.save()
        trip.refresh_from_db()

        return trip

    @classmethod
    def approved_trip(cls, employee, **kwargs):
        return cls.set_status(
            cls.make_trip(employee, **kwargs),
            BusinessTripStatus.APPROVED,
        )

    @staticmethod
    def today() -> date:
        return wall_today()
