"""
Regresi cakupan data pada layar Work Calendar dan Holiday.

Dua sifat yang harus berlaku **bersamaan**, dan menjaga salah satunya
saja menghasilkan bug yang berlawanan arah:

* baris yang **berlaku untuk semua** (GLOBAL, `company IS NULL`) harus
  terlihat oleh admin bercakupan — tanpa itu justru libur nasional yang
  hilang dari layar setiap admin site;
* baris **milik perusahaan lain** tetap tidak boleh terbaca.

Yang paling mudah salah adalah cakupan `SELECTED_COMPANIES`: kolom
company-nya juga NULL, jadi kelonggaran yang benar untuk GLOBAL
meloloskannya juga — padahal daftarnya bisa saja tidak memuat
perusahaan pembacanya sama sekali.
"""

from __future__ import annotations

import json
from datetime import date

from django_tenants.test.cases import TenantTestCase
from django_tenants.test.client import TenantClient
from apps.accounts.jwt import TenantRefreshToken as RefreshToken

from apps.accounts.models import (
    AuthorityMode,
    Role,
)
from apps.accounts.services.role_assignment import grant_role
from apps.administration.models import (
    CalendarScope,
    Company,
    Holiday,
    HolidayCompany,
    HolidayScope,
    Location,
    WorkCalendar,
)


WORK_CALENDARS = "/api/administration/calendar/work-calendars/"
HOLIDAYS = "/api/administration/calendar/holidays/"


class _As:
    """Klien HTTP yang selalu membawa token satu orang."""

    def __init__(self, client, user):
        self.client = client
        self.headers = {
            "HTTP_AUTHORIZATION": (
                f"Bearer {RefreshToken.for_user(user).access_token}"
            ),
        }

    def get(self, path):
        return self.client.get(path, **self.headers)


class CalendarScopingTests(TenantTestCase):
    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "calendar-scoping-test"
        tenant.name = "Calendar Scoping Test"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        from django.contrib.auth import get_user_model

        User = get_user_model()

        cls.company_a = Company.objects.create(code="MMR", name="Mineral MMR")
        cls.company_b = Company.objects.create(code="MLS", name="Logistik MLS")

        cls.location_b = Location.objects.create(
            company=cls.company_b,
            code="JETTY",
            name="Sagea Jetty",
        )

        # Role bercakupan **Company A saja**. Cakupannya dinyatakan
        # pada penugasan di bawah — `Role` menjawab WHAT saja.
        cls.role = Role.objects.create(
            code="CAL-ADMIN-A",
            name="Calendar Admin (Company A)",
        )

        # Email wajib diisi dan **unik**: dua akun beremail kosong
        # bentrok di `auth_users_email_key`, dan pesannya menyebut
        # constraint database, bukan test yang salah menyiapkan data.
        cls.scoped_user = User.objects.create_user(
            username="scoped-a",
            email="scoped-a@example.test",
            password="x",
        )

        # Kewenangannya **dinyatakan di penugasan** — satu-satunya
        # tempat WHERE disimpan. `.roles.add()` telanjang cuma memberi
        # keanggotaan, tanpa membuka satu baris pun.
        grant_role(
            cls.scoped_user,
            cls.role,
            mode=AuthorityMode.EXPLICIT,
            authorities=[("company", cls.company_a.id)],
        )

    def setUp(self):
        super().setUp()

        WorkCalendar.objects.all().delete()
        Holiday.objects.all().delete()

        self.http = TenantClient(self.tenant)

        self.as_scoped = _As(self.http, self.scoped_user)

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    @staticmethod
    def codes(response) -> set[str]:
        payload = json.loads(response.content)

        # Amplop daftar API ini `{data, meta}` — bukan `results`.
        rows = payload.get("data", payload.get("results", payload))

        return {row["code"] for row in rows}

    # ------------------------------------------------------------------
    # Work Calendar
    # ------------------------------------------------------------------

    def test_scoped_user_sees_global_but_not_other_company(self):
        """(15) Cakupan tetap ditegakkan, GLOBAL tetap terlihat."""
        WorkCalendar.objects.create(
            scope=CalendarScope.GLOBAL,
            code="HO-STANDARD",
            name="Head Office Standard",
        )

        WorkCalendar.objects.create(
            scope=CalendarScope.COMPANY,
            company=self.company_a,
            code="MMR-OPS",
            name="MMR Operational",
        )

        WorkCalendar.objects.create(
            scope=CalendarScope.COMPANY,
            company=self.company_b,
            code="MLS-OPS",
            name="MLS Operational",
        )

        response = self.as_scoped.get(WORK_CALENDARS)

        self.assertEqual(response.status_code, 200)

        codes = self.codes(response)

        self.assertIn("HO-STANDARD", codes)
        self.assertIn("MMR-OPS", codes)

        # Inti test ini.
        self.assertNotIn("MLS-OPS", codes)

    def test_scoped_user_cannot_open_other_company_calendar_by_id(self):
        """
        Daftar yang disaring tidak ada gunanya kalau detailnya tidak.
        Nomor urut tinggal ditebak.
        """
        other = WorkCalendar.objects.create(
            scope=CalendarScope.COMPANY,
            company=self.company_b,
            code="MLS-OPS",
            name="MLS Operational",
        )

        response = self.as_scoped.get(f"{WORK_CALENDARS}{other.id}/")

        self.assertEqual(response.status_code, 404)

    # ------------------------------------------------------------------
    # Holiday
    # ------------------------------------------------------------------

    def test_global_holiday_is_visible_to_scoped_user(self):
        """
        Yang paling mudah rusak: `DATA_SCOPE_INCLUDE_NULL` bawaannya
        False, jadi tanpa `allow_null=True` justru libur nasional yang
        hilang dari layar admin site.
        """
        Holiday.objects.create(
            scope=HolidayScope.GLOBAL,
            date=date(2026, 8, 17),
            code="INDEPENDENCE-2026",
            name="Indonesia Independence Day",
            is_national=True,
        )

        Holiday.objects.create(
            scope=HolidayScope.COMPANY,
            company=self.company_b,
            date=date(2026, 3, 4),
            code="MLS-ANNIV",
            name="MLS Anniversary",
        )

        codes = self.codes(self.as_scoped.get(HOLIDAYS))

        self.assertIn("INDEPENDENCE-2026", codes)
        self.assertNotIn("MLS-ANNIV", codes)

    def test_location_holiday_of_another_company_is_hidden(self):
        Holiday.objects.create(
            scope=HolidayScope.LOCATION,
            company=self.company_b,
            location=self.location_b,
            date=date(2026, 7, 1),
            code="JETTY-SAFETY",
            name="Jetty Safety Day",
        )

        self.assertNotIn(
            "JETTY-SAFETY",
            self.codes(self.as_scoped.get(HOLIDAYS)),
        )

    def test_selected_companies_holiday_respects_the_list(self):
        """
        Cakupan SELECTED_COMPANIES menyimpan `company = NULL`, sama
        seperti GLOBAL — jadi kelonggaran yang benar untuk GLOBAL
        meloloskannya juga kalau daftarnya tidak ikut diperiksa.
        """
        mine = Holiday.objects.create(
            scope=HolidayScope.SELECTED_COMPANIES,
            date=date(2026, 12, 24),
            code="CUTI-BERSAMA-A",
            name="Cuti Bersama (A)",
        )

        HolidayCompany.objects.create(holiday=mine, company=self.company_a)

        theirs = Holiday.objects.create(
            scope=HolidayScope.SELECTED_COMPANIES,
            date=date(2026, 12, 26),
            code="CUTI-BERSAMA-B",
            name="Cuti Bersama (B)",
        )

        HolidayCompany.objects.create(holiday=theirs, company=self.company_b)

        codes = self.codes(self.as_scoped.get(HOLIDAYS))

        self.assertIn("CUTI-BERSAMA-A", codes)
        self.assertNotIn("CUTI-BERSAMA-B", codes)

    def test_unrestricted_user_sees_everything(self):
        """
        Penyaringan tambahan untuk SELECTED_COMPANIES tidak boleh ikut
        berlaku bagi yang memang tak bercakupan.
        """
        from django.contrib.auth import get_user_model

        superuser = get_user_model().objects.create_superuser(
            username="root",
            email="root@example.test",
            password="x",
        )

        holiday = Holiday.objects.create(
            scope=HolidayScope.SELECTED_COMPANIES,
            date=date(2026, 12, 26),
            code="CUTI-BERSAMA-B",
            name="Cuti Bersama (B)",
        )

        HolidayCompany.objects.create(holiday=holiday, company=self.company_b)

        codes = self.codes(_As(self.http, superuser).get(HOLIDAYS))

        self.assertIn("CUTI-BERSAMA-B", codes)
