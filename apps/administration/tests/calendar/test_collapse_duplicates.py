"""
Regresi command `collapse_calendar_duplicates`.

Tiga sifat yang dijaga, dan ketiganya adalah cara migrasi data semacam
ini biasanya merusak:

* **FK tidak putus.** `EmploymentAssignment.working_calendar` memakai
  `PROTECT`; kalender yang dihapus sebelum referensinya dipindah akan
  menghentikan perintahnya di tengah, dengan sebagian data sudah
  berubah.
* **Yang tidak identik tidak digabung.** Kesamaan kode saja tidak
  pernah cukup — `LOCATION-DAY-01-2026` di tiga perusahaan menyebut
  tiga lokasi yang berbeda.
* **Dry-run tidak menulis apa pun.**
"""

from __future__ import annotations

from datetime import date
from io import StringIO

from django.core.management import call_command
from django_tenants.test.cases import TenantTestCase

from apps.administration.models import (
    CalendarScope,
    Company,
    Holiday,
    HolidayScope,
    WorkCalendar,
)
from apps.administration.services.calendar_resolver import CalendarResolver


class CollapseDuplicatesTests(TenantTestCase):
    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "collapse-test"
        tenant.name = "Collapse Test"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.companies = [
            Company.objects.create(code=f"C{index}", name=f"Company {index}")
            for index in range(1, 4)
        ]

    def setUp(self):
        super().setUp()

        WorkCalendar.objects.all().delete()
        Holiday.objects.all().delete()

    def run_command(self, *, apply=False, only=None):
        out = StringIO()

        options = {"stdout": out}

        if apply:
            options["apply"] = True

        if only:
            options["only"] = only

        call_command("collapse_calendar_duplicates", **options)

        return out.getvalue()

    # ------------------------------------------------------------------
    # Fixture
    # ------------------------------------------------------------------

    def seed_identical_calendars(self):
        """`OFFICE-2026` di tiga perusahaan, isinya sama persis."""
        return [
            WorkCalendar.objects.create(
                scope=CalendarScope.COMPANY,
                company=company,
                code="OFFICE-2026",
                name="Office Calendar 2026",
                monday=True,
                tuesday=True,
                wednesday=True,
                thursday=True,
                friday=True,
                saturday=False,
                sunday=False,
                is_default=True,
            )
            for company in self.companies
        ]

    def seed_identical_holidays(self):
        return [
            Holiday.objects.create(
                scope=HolidayScope.COMPANY,
                company=company,
                date=date(2026, 8, 17),
                code="INDEPENDENCE-2026",
                name="Indonesia Independence Day",
                is_national=True,
            )
            for company in self.companies
        ]

    # ------------------------------------------------------------------
    # Dry-run
    # ------------------------------------------------------------------

    def test_dry_run_changes_nothing(self):
        self.seed_identical_calendars()
        self.seed_identical_holidays()

        output = self.run_command()

        self.assertIn("DRY-RUN", output)
        self.assertIn("MERGE", output)

        self.assertEqual(
            WorkCalendar.objects.filter(is_deleted=False).count(),
            3,
        )

        self.assertEqual(
            Holiday.objects.filter(is_deleted=False).count(),
            3,
        )

        self.assertFalse(
            WorkCalendar.objects.filter(scope=CalendarScope.GLOBAL).exists(),
        )

    # ------------------------------------------------------------------
    # Penggabungan
    # ------------------------------------------------------------------

    def test_identical_calendars_collapse_to_one_global(self):
        self.seed_identical_calendars()

        self.run_command(apply=True, only="work-calendar")

        live = WorkCalendar.objects.filter(is_deleted=False)

        self.assertEqual(live.count(), 1)

        keeper = live.get()

        self.assertEqual(keeper.scope, CalendarScope.GLOBAL)
        self.assertIsNone(keeper.company_id)

        # Dan setiap company tetap mendapat kalender yang sama seperti
        # sebelum digabung — hari kerjanya tidak berubah untuk siapa pun.
        for company in self.companies:
            self.assertEqual(
                CalendarResolver.resolve_work_calendar(
                    company_id=company.id,
                ),
                keeper,
            )

    def test_identical_holidays_collapse_to_one_global(self):
        self.seed_identical_holidays()

        self.run_command(apply=True, only="holiday")

        live = Holiday.objects.filter(is_deleted=False)

        self.assertEqual(live.count(), 1)
        self.assertEqual(live.get().scope, HolidayScope.GLOBAL)

        for company in self.companies:
            self.assertIn(
                date(2026, 8, 17),
                CalendarResolver.resolve_holidays(
                    company_id=company.id,
                    location_id=None,
                    start=date(2026, 1, 1),
                    end=date(2026, 12, 31),
                ),
            )

    def test_rows_are_soft_deleted_not_erased(self):
        """"Jangan langsung delete data" — barisnya masih bisa dilihat."""
        self.seed_identical_calendars()

        self.run_command(apply=True, only="work-calendar")

        self.assertEqual(WorkCalendar.objects.count(), 3)

        self.assertEqual(
            WorkCalendar.objects.filter(is_deleted=True).count(),
            2,
        )

    # ------------------------------------------------------------------
    # Yang TIDAK boleh digabung
    # ------------------------------------------------------------------

    def test_rows_with_different_behaviour_are_reported_not_merged(self):
        """
        Kode sama, hari kerja berbeda → exception, bukan merge.

        Menggabungkannya akan mengubah hari kerja salah satu perusahaan
        tanpa ada yang memintanya.
        """
        calendars = self.seed_identical_calendars()

        calendars[0].saturday = True
        calendars[0].save(update_fields=["saturday"])

        output = self.run_command(apply=True, only="work-calendar")

        self.assertIn("EXCEPTION", output)

        self.assertEqual(
            WorkCalendar.objects.filter(is_deleted=False).count(),
            3,
        )

    def test_partial_coverage_is_not_promoted_to_global(self):
        """
        Kalender yang cuma dimiliki dua dari tiga perusahaan tidak
        dinaikkan jadi GLOBAL — perusahaan ketiga tidak boleh
        mendapatkannya diam-diam.
        """
        for company in self.companies[:2]:
            WorkCalendar.objects.create(
                scope=CalendarScope.COMPANY,
                company=company,
                code="SHIFT-6-1",
                name="Six Day Week",
                saturday=True,
            )

        output = self.run_command(apply=True, only="work-calendar")

        self.assertIn("SKIP", output)

        self.assertEqual(
            WorkCalendar.objects.filter(
                is_deleted=False,
                code="SHIFT-6-1",
            ).count(),
            2,
        )

    def test_partial_coverage_holiday_becomes_selected_companies(self):
        """
        Holiday **punya** cakupan "sebagian", jadi yang dua-dari-tiga
        digabung jadi satu baris + tabel relasi — bukan dilewati.
        """
        for company in self.companies[:2]:
            Holiday.objects.create(
                scope=HolidayScope.COMPANY,
                company=company,
                date=date(2026, 12, 24),
                code="CUTI-BERSAMA-2026",
                name="Cuti Bersama Natal",
            )

        self.run_command(apply=True, only="holiday")

        live = Holiday.objects.filter(is_deleted=False)

        self.assertEqual(live.count(), 1)

        keeper = live.get()

        self.assertEqual(keeper.scope, HolidayScope.SELECTED_COMPANIES)

        self.assertEqual(
            set(
                keeper.companies
                .filter(is_deleted=False)
                .values_list("company_id", flat=True),
            ),
            {self.companies[0].id, self.companies[1].id},
        )

        # Perusahaan ketiga tetap tidak libur.
        self.assertNotIn(
            date(2026, 12, 24),
            CalendarResolver.resolve_holidays(
                company_id=self.companies[2].id,
                location_id=None,
                start=date(2026, 1, 1),
                end=date(2026, 12, 31),
            ),
        )

    # ------------------------------------------------------------------
    # Kembaran GLOBAL yang sudah ada
    # ------------------------------------------------------------------

    def test_existing_global_twin_is_adopted_not_collided(self):
        """
        Jalur upgrade yang lazim: tenant menjalankan seed baru — yang
        menerbitkan baris GLOBAL — lalu menjalankan perintah ini.

        Tanpa penanganan khusus, mempromosikan keeper ke GLOBAL
        menabrak `uniq_active_holiday_scope_date_code` dan perintahnya
        berhenti di tengah, dengan sebagian grup sudah digabung dan
        sebagian belum. Ditemukan saat UAT, bukan saat menulis kodenya.
        """
        self.seed_identical_holidays()

        twin = Holiday.objects.create(
            scope=HolidayScope.GLOBAL,
            company=None,
            location=None,
            date=date(2026, 8, 17),
            code="INDEPENDENCE-2026",
            name="Indonesia Independence Day",
            is_national=True,
        )

        output = self.run_command(apply=True, only="holiday")

        self.assertIn("ADOPT", output)

        live = Holiday.objects.filter(
            is_deleted=False,
            code="INDEPENDENCE-2026",
        )

        self.assertEqual(live.count(), 1)
        self.assertEqual(live.get().pk, twin.pk)

    def test_existing_global_calendar_twin_is_adopted(self):
        self.seed_identical_calendars()

        twin = WorkCalendar.objects.create(
            scope=CalendarScope.GLOBAL,
            company=None,
            location=None,
            code="OFFICE-2026",
            name="Office Calendar 2026",
            is_default=True,
        )

        output = self.run_command(apply=True, only="work-calendar")

        self.assertIn("ADOPT", output)

        live = WorkCalendar.objects.filter(is_deleted=False, code="OFFICE-2026")

        self.assertEqual(live.count(), 1)
        self.assertEqual(live.get().pk, twin.pk)

    def test_adopted_twin_receives_the_foreign_keys(self):
        """
        Yang diadopsi tetap harus memungut referensinya — kalau tidak,
        penempatan pegawai menunjuk kalender yang sudah dihapus.
        """
        from apps.hr.models import (
            Employee,
            EmploymentAssignment,
            OrganizationAssignment,
        )

        calendars = self.seed_identical_calendars()

        twin = WorkCalendar.objects.create(
            scope=CalendarScope.GLOBAL,
            company=None,
            location=None,
            code="OFFICE-2026",
            name="Office Calendar 2026",
            is_default=True,
        )

        employee = Employee.objects.create(
            employee_number="EMP900",
            first_name="Adopt",
            last_name="Test",
        )

        OrganizationAssignment.objects.create(
            employee=employee,
            company=self.companies[0],
            organization_effective_date=date(2026, 1, 1),
        )

        EmploymentAssignment.objects.create(
            employee=employee,
            working_calendar=calendars[0],
            employment_effective_date=date(2026, 1, 1),
        )

        self.run_command(apply=True, only="work-calendar")

        assignment = EmploymentAssignment.objects.get(employee=employee)

        self.assertEqual(assignment.working_calendar_id, twin.pk)

    # ------------------------------------------------------------------
    # FK
    # ------------------------------------------------------------------

    def test_employment_assignments_are_repointed(self):
        """
        (19) Migrasi tidak memutus FK.

        `working_calendar` memakai `PROTECT`. Kalau referensinya tidak
        dipindah lebih dulu, kalender yang digabung akan meninggalkan
        penempatan yang menunjuk baris terhapus — dan pegawainya
        kehilangan kalender tanpa satu pun pesan.
        """
        from apps.hr.models import (
            Employee,
            EmploymentAssignment,
            OrganizationAssignment,
        )

        calendars = self.seed_identical_calendars()

        employees = []

        for index, calendar in enumerate(calendars):
            employee = Employee.objects.create(
                employee_number=f"EMP{index:03d}",
                first_name="Test",
                last_name=f"Employee {index}",
            )

            OrganizationAssignment.objects.create(
                employee=employee,
                company=self.companies[index],
                organization_effective_date=date(2026, 1, 1),
            )

            EmploymentAssignment.objects.create(
                employee=employee,
                working_calendar=calendar,
                employment_effective_date=date(2026, 1, 1),
            )

            employees.append(employee)

        self.run_command(apply=True, only="work-calendar")

        keeper = WorkCalendar.objects.get(is_deleted=False)

        for employee in employees:
            assignment = EmploymentAssignment.objects.get(employee=employee)

            self.assertEqual(assignment.working_calendar_id, keeper.id)

        # Tidak ada satu pun yang menunjuk kalender yang sudah dihapus.
        self.assertFalse(
            EmploymentAssignment.objects
            .filter(working_calendar__is_deleted=True)
            .exists(),
        )
