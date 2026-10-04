"""
Pabrik data bersama untuk test Travel Request.

Tiap test membuat pegawainya sendiri dan hanya membaca miliknya.
Alasan yang dulu ditulis di sini — bahwa `TenantTestCase` tidak
me-rollback antar test — **keliru** (diukur di TEST-ISO-HR-0B).
Yang memang tidak pernah jalan `setUpTestData()`, dan data yang
dibuat di `setUpClass` tidak ikut di-rollback. Pola yang sama dengan
`apps/hr/tests/roster/test_roster_flow.py` — kalau tidak, urutan
eksekusi yang menentukan hasilnya.
"""

from __future__ import annotations

from datetime import date

from django_tenants.test.cases import TenantTestCase

from apps.administration.models import (
    City,
    Company,
    Country,
    LeaveType,
    Location,
    Province,
    RotationPurpose,
)
from apps.administration.seeds.numbering import seed_numbering
from apps.hr.api.travel_request.services import (
    TravelRequestPurposeService,
    TravelRequestService,
)
from apps.hr.models import (
    Employee,
    EmploymentAssignment,
    OrganizationAssignment,
    RotationPeriod,
    RotationPeriodType,
    SiteRotation,
)


AS_OF = date(2026, 9, 1)


class TravelRequestTestCase(TenantTestCase):
    """Satu company, satu site, dua Travel Purpose (potong / tidak)."""

    _counter = 0

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "travel-request"
        tenant.name = "Travel Request"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        # Tenant test lahir kosong. Tanpa deret nomor, `document_number`
        # terbit kosong — perilaku yang memang benar (dokumen tetap
        # tersimpan), tapi membuat assertion soal nomor TR tidak menguji
        # apa pun.
        seed_numbering()

        cls.company = Company.objects.create(code="TRV", name="Travel Test")

        cls.site = Location.objects.create(
            company=cls.company,
            code="TRSITE",
            name="Gebe Site",
        )

        # Point of Hire wajib menembus Country → Province → City;
        # `master_city.province_id` NOT NULL.
        country = Country.objects.create(
            code="TRID",
            name="Indonesia",
            phone_code="62",
            currency_code="IDR",
        )

        province = Province.objects.create(
            code="TRDKI",
            name="DKI Jakarta",
            country=country,
        )

        cls.point_of_hire = City.objects.create(
            code="TRJKT",
            name="Jakarta",
            province=province,
        )

        cls.leave_type = LeaveType.objects.create(
            code="TR-ANNUAL",
            name="Cuti Tahunan",
        )

        # Dua baris master yang membedakan seluruh perilaku hilir:
        # Field Break adalah blok off rosternya sendiri dan tidak
        # menyentuh saldo, Cuti Tahunan memotong.
        cls.field_break = RotationPurpose.objects.create(
            code="TR-FB",
            name="Field Break",
            deducts_leave=False,
        )

        cls.annual_leave = RotationPurpose.objects.create(
            code="TR-AL",
            name="Cuti Tahunan",
            deducts_leave=True,
            leave_type=cls.leave_type,
        )

    # ------------------------------------------------------------------
    # Pabrik data
    # ------------------------------------------------------------------

    @classmethod
    def make_employee(cls) -> Employee:
        cls._counter += 1

        employee = Employee.objects.create(
            employee_number=f"TRV{cls._counter:04d}",
            first_name="Travel",
            last_name=f"Employee {cls._counter}",
        )

        OrganizationAssignment.objects.create(
            employee=employee,
            company=cls.company,
            location=cls.site,
            organization_effective_date=date(2026, 1, 1),
        )

        EmploymentAssignment.objects.create(
            employee=employee,
            join_date=date(2025, 1, 1),
            point_of_hire=cls.point_of_hire,
        )

        return Employee.objects.get(pk=employee.pk)

    @classmethod
    def make_rotation(
        cls,
        employee,
        *,
        work_days: int = 42,
        off_days: int = 14,
        travel_days: int = 2,
        start_date: date = AS_OF,
    ) -> SiteRotation:
        """
        Jadwal tahunan minimal, dibuat langsung lewat ORM.

        Sengaja tidak lewat generator: yang diuji di sini Travel
        Request, dan generator roster punya berkas testnya sendiri.
        Yang harus benar cuma pola siklusnya, karena dari situlah
        `RotationPeriod.travel_window_*` dihitung.
        """
        return SiteRotation.objects.create(
            employee=employee,
            company=cls.company,
            location=cls.site,
            cycle_work_days=work_days,
            cycle_off_days=off_days,
            cycle_travel_days=travel_days,
            start_date=start_date,
            cycle_count=1,
        )

    @classmethod
    def make_periods(cls, rotation) -> tuple[RotationPeriod, RotationPeriod]:
        """
        Satu putaran: blok kerja, jendela travel keluar, blok off.

        Tanggalnya disusun persis seperti generator: blok off mulai
        `work_end + hari_keluar + 1`, dengan hari keluar `ceil(t/2)`.
        Itu yang membuat `travel_window_*` blok kerja jatuh tepat di
        antara keduanya.
        """
        from datetime import timedelta

        employee = rotation.employee

        work_days = rotation.cycle_work_days
        off_days = rotation.cycle_off_days
        out_days = -(-(rotation.cycle_travel_days or 0) // 2)

        work_start = rotation.start_date
        work_end = work_start + timedelta(days=work_days - 1)

        work = RotationPeriod.objects.create(
            rotation=rotation,
            employee=employee,
            sequence=1,
            period_type=RotationPeriodType.WORK,
            start_date=work_start,
            end_date=work_end,
            total_days=work_days,
            cycle_number=1,
        )

        off_start = work_end + timedelta(days=out_days + 1)
        off_end = off_start + timedelta(days=off_days - 1)

        off = RotationPeriod.objects.create(
            rotation=rotation,
            employee=employee,
            sequence=2,
            period_type=RotationPeriodType.OFF,
            start_date=off_start,
            end_date=off_end,
            total_days=off_days,
            purpose=cls.field_break,
            cycle_number=1,
        )

        return work, off

    @classmethod
    def make_request(
        cls,
        employee=None,
        *,
        start_date: date = date(2026, 10, 13),
        end_date: date = date(2026, 10, 26),
        with_purpose: bool = True,
    ):
        employee = employee or cls.make_employee()

        request = TravelRequestService.create(
            data={
                "employee": employee,
                "company": cls.company,
                "location": cls.site,
                "start_date": start_date,
                "end_date": end_date,
            },
        )

        if with_purpose:
            TravelRequestPurposeService.create(
                data={
                    "request": request,
                    "purpose": cls.field_break,
                    "start_date": start_date,
                    "end_date": end_date,
                },
            )

            request.refresh_from_db()

        return request
