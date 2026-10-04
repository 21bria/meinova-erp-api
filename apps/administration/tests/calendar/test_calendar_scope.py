"""
Regresi cakupan kalender: GLOBAL / COMPANY / LOCATION / SELECTED.

Yang dikunci di sini bukan sekadar "resolver mengembalikan baris yang
benar", tapi dua sifat yang menjadi alasan seluruh perubahan ini:

* satu libur nasional = **satu baris database**, berapa pun
  perusahaannya;
* perusahaan yang dibuat **setelah** import tetap mendapatkannya, tanpa
  seed atau import ulang.

Keduanya diperiksa dengan menghitung baris, bukan cuma dengan membaca
hasil resolver — resolver yang benar di atas data yang terduplikasi
tetap berarti duplikasi.
"""

from __future__ import annotations

from datetime import date

from django.core.exceptions import ValidationError
from django_tenants.test.cases import TenantTestCase

from apps.administration.models import (
    CalendarScope,
    Company,
    Holiday,
    HolidayCompany,
    HolidayScope,
    HolidaySyncStatus,
    Location,
    WorkCalendar,
)
from apps.administration.services.calendar_resolver import CalendarResolver


class CalendarScopeTestCase(TenantTestCase):
    """Dua company, tiga lokasi — cukup untuk membedakan ketiga cakupan."""

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "calendar-scope-test"
        tenant.name = "Calendar Scope Test"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.company_a = Company.objects.create(code="MMR", name="Mineral MMR")
        cls.company_b = Company.objects.create(code="MLS", name="Logistik MLS")

        cls.mine = Location.objects.create(
            company=cls.company_a,
            code="SAGEA-MINE",
            name="Sagea Mine",
        )

        cls.port = Location.objects.create(
            company=cls.company_a,
            code="SAGEA-PORT",
            name="Sagea Port",
        )

        cls.jetty = Location.objects.create(
            company=cls.company_b,
            code="SAGEA-JETTY",
            name="Sagea Jetty",
        )

    def setUp(self):
        super().setUp()

        WorkCalendar.objects.all().delete()
        Holiday.objects.all().delete()

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    @staticmethod
    def make_global_calendar(**overrides):
        payload = {
            "scope": CalendarScope.GLOBAL,
            "company": None,
            "location": None,
            "code": "HO-STANDARD",
            "name": "Head Office Standard",
            "monday": True,
            "tuesday": True,
            "wednesday": True,
            "thursday": True,
            "friday": True,
            "saturday": False,
            "sunday": False,
            "is_default": True,
        }

        payload.update(overrides)

        return WorkCalendar.objects.create(**payload)


# ======================================================================
# WORK CALENDAR — presedensi
# ======================================================================


class WorkCalendarResolutionTests(CalendarScopeTestCase):
    def test_global_calendar_applies_to_company_a(self):
        """(1) GLOBAL Work Calendar berlaku untuk Company A."""
        calendar = self.make_global_calendar()

        resolved = CalendarResolver.resolve_work_calendar(
            company_id=self.company_a.id,
        )

        self.assertEqual(resolved, calendar)

    def test_global_calendar_applies_to_company_b(self):
        """(2) …dan ke Company B, dari **baris yang sama**."""
        calendar = self.make_global_calendar()

        resolved = CalendarResolver.resolve_work_calendar(
            company_id=self.company_b.id,
        )

        self.assertEqual(resolved, calendar)

        # Inti perubahan ini: satu baris, bukan satu per company.
        self.assertEqual(WorkCalendar.objects.count(), 1)

    def test_company_created_later_resolves_global(self):
        """(3) Company baru otomatis resolve GLOBAL — tanpa seed ulang."""
        calendar = self.make_global_calendar()

        newcomer = Company.objects.create(code="NEW", name="Baru Berdiri")

        resolved = CalendarResolver.resolve_work_calendar(
            company_id=newcomer.id,
        )

        self.assertEqual(resolved, calendar)
        self.assertEqual(WorkCalendar.objects.count(), 1)

    def test_company_calendar_overrides_global(self):
        """(4) COMPANY menang atas GLOBAL."""
        self.make_global_calendar()

        company_calendar = WorkCalendar.objects.create(
            scope=CalendarScope.COMPANY,
            company=self.company_a,
            code="MMR-OPS",
            name="MMR Operational",
            saturday=True,
        )

        self.assertEqual(
            CalendarResolver.resolve_work_calendar(
                company_id=self.company_a.id,
            ),
            company_calendar,
        )

        # Company B tidak ikut terpengaruh — ia tetap di GLOBAL.
        self.assertEqual(
            CalendarResolver.resolve_work_calendar(
                company_id=self.company_b.id,
            ).code,
            "HO-STANDARD",
        )

    def test_location_calendar_overrides_company_and_global(self):
        """(5) LOCATION menang atas COMPANY dan GLOBAL."""
        self.make_global_calendar()

        WorkCalendar.objects.create(
            scope=CalendarScope.COMPANY,
            company=self.company_a,
            code="MMR-OPS",
            name="MMR Operational",
            saturday=True,
        )

        mine_calendar = WorkCalendar.objects.create(
            scope=CalendarScope.LOCATION,
            company=self.company_a,
            location=self.mine,
            code="SAGEA-MINE",
            name="Sagea Mine",
            saturday=True,
            sunday=True,
        )

        self.assertEqual(
            CalendarResolver.resolve_work_calendar(
                company_id=self.company_a.id,
                location_id=self.mine.id,
            ),
            mine_calendar,
        )

    def test_location_without_own_calendar_falls_back(self):
        """
        (6) Lokasi tanpa kalender sendiri jatuh ke COMPANY, lalu GLOBAL.

        Ini yang membuat "jangan membuat calendar location kalau cukup
        ikut GLOBAL" benar-benar bisa dijalankan: lokasi yang tidak
        punya baris apa pun tetap punya kalender.
        """
        self.make_global_calendar()

        company_calendar = WorkCalendar.objects.create(
            scope=CalendarScope.COMPANY,
            company=self.company_a,
            code="MMR-OPS",
            name="MMR Operational",
            saturday=True,
        )

        # Port belum punya kalender sendiri → kalender company-nya.
        self.assertEqual(
            CalendarResolver.resolve_work_calendar(
                company_id=self.company_a.id,
                location_id=self.port.id,
            ),
            company_calendar,
        )

        # Jetty milik company B yang tidak punya kalender company →
        # turun sampai GLOBAL.
        self.assertEqual(
            CalendarResolver.resolve_work_calendar(
                company_id=self.company_b.id,
                location_id=self.jetty.id,
            ).code,
            "HO-STANDARD",
        )

    def test_employee_override_wins_over_everything(self):
        """Override pegawai duduk di puncak presedensi."""
        self.make_global_calendar()

        override = WorkCalendar.objects.create(
            scope=CalendarScope.LOCATION,
            company=self.company_a,
            location=self.mine,
            code="SAGEA-MINE",
            name="Sagea Mine",
        )

        self.assertEqual(
            CalendarResolver.resolve_work_calendar(
                company_id=self.company_b.id,
                location_id=self.jetty.id,
                override=override,
            ),
            override,
        )

    def test_inactive_global_calendar_is_ignored(self):
        self.make_global_calendar(is_active=False)

        self.assertIsNone(
            CalendarResolver.resolve_work_calendar(
                company_id=self.company_a.id,
            ),
        )

    def test_location_calendar_of_other_company_does_not_leak(self):
        """Kalender lokasi company A tidak terbaca oleh company B."""
        WorkCalendar.objects.create(
            scope=CalendarScope.LOCATION,
            company=self.company_a,
            location=self.mine,
            code="SAGEA-MINE",
            name="Sagea Mine",
        )

        self.assertIsNone(
            CalendarResolver.resolve_work_calendar(
                company_id=self.company_b.id,
                location_id=self.jetty.id,
            ),
        )


# ======================================================================
# WORK CALENDAR — validasi cakupan
# ======================================================================


class WorkCalendarScopeValidationTests(CalendarScopeTestCase):
    def test_global_with_company_is_rejected(self):
        calendar = WorkCalendar(
            scope=CalendarScope.GLOBAL,
            company=self.company_a,
            code="X",
            name="X",
        )

        with self.assertRaises(ValidationError) as ctx:
            calendar.clean()

        self.assertIn("company", ctx.exception.message_dict)

    def test_company_scope_without_company_is_rejected(self):
        calendar = WorkCalendar(
            scope=CalendarScope.COMPANY,
            code="X",
            name="X",
        )

        with self.assertRaises(ValidationError) as ctx:
            calendar.clean()

        self.assertIn("company", ctx.exception.message_dict)

    def test_location_from_another_company_is_rejected(self):
        calendar = WorkCalendar(
            scope=CalendarScope.LOCATION,
            company=self.company_b,
            location=self.mine,
            code="X",
            name="X",
        )

        with self.assertRaises(ValidationError) as ctx:
            calendar.clean()

        self.assertIn("location", ctx.exception.message_dict)

    def test_legacy_create_without_scope_is_normalized(self):
        """
        Kode lama yang tidak menyebut cakupan tetap menghasilkan baris
        yang sah.

        Puluhan test dan seed yang sudah ada memanggil
        `WorkCalendar.objects.create(company=…, location=…)` tanpa
        `scope`. Tanpa penyelarasan di `save()`, barisnya tersimpan
        sebagai COMPANY yang menyebut location — dan resolver tidak
        akan pernah menemukannya sebagai kalender lokasi.
        """
        legacy = WorkCalendar.objects.create(
            company=self.company_a,
            location=self.mine,
            code="LEGACY",
            name="Legacy Location Calendar",
        )

        legacy.refresh_from_db()

        self.assertEqual(legacy.scope, CalendarScope.LOCATION)

        self.assertEqual(
            CalendarResolver.resolve_work_calendar(
                company_id=self.company_a.id,
                location_id=self.mine.id,
            ),
            legacy,
        )


# ======================================================================
# HOLIDAY
# ======================================================================


class HolidayScopeTests(CalendarScopeTestCase):
    NATIONAL_DAY = date(2026, 8, 17)

    def make_national(self, **overrides):
        payload = {
            "scope": HolidayScope.GLOBAL,
            "company": None,
            "location": None,
            "date": self.NATIONAL_DAY,
            "code": "INDEPENDENCE-2026",
            "name": "Indonesia Independence Day",
            "country_code": "ID",
            "is_national": True,
        }

        payload.update(overrides)

        return Holiday.objects.create(**payload)

    def resolve(self, company, location=None):
        return CalendarResolver.resolve_holidays(
            company_id=company.id if company else None,
            location_id=location.id if location else None,
            start=date(2026, 1, 1),
            end=date(2026, 12, 31),
        )

    def test_global_holiday_is_a_single_row(self):
        """(7) GLOBAL Holiday hanya satu record di database."""
        self.make_national()

        self.assertEqual(Holiday.objects.count(), 1)

        # Dan tidak menurunkan satu pun baris relasi: cakupan "semua"
        # tidak boleh diwujudkan sebagai daftar yang harus disusul tiap
        # kali ada perusahaan baru.
        self.assertEqual(HolidayCompany.objects.count(), 0)

    def test_global_holiday_applies_to_several_companies(self):
        """(8) …dan berlaku ke beberapa company sekaligus."""
        self.make_national()

        self.assertIn(self.NATIONAL_DAY, self.resolve(self.company_a))
        self.assertIn(self.NATIONAL_DAY, self.resolve(self.company_b))

        self.assertEqual(Holiday.objects.count(), 1)

    def test_company_created_later_gets_global_holiday(self):
        """(9) Company baru mendapatkannya tanpa duplikasi."""
        self.make_national()

        newcomer = Company.objects.create(code="NEW", name="Baru Berdiri")

        self.assertIn(self.NATIONAL_DAY, self.resolve(newcomer))
        self.assertEqual(Holiday.objects.count(), 1)

    def test_company_holiday_does_not_leak(self):
        """(10) Libur khusus company tidak terbaca company lain."""
        anniversary = date(2026, 3, 4)

        Holiday.objects.create(
            scope=HolidayScope.COMPANY,
            company=self.company_a,
            date=anniversary,
            code="MMR-ANNIV",
            name="MMR Anniversary",
        )

        self.assertIn(anniversary, self.resolve(self.company_a))
        self.assertNotIn(anniversary, self.resolve(self.company_b))

    def test_location_holiday_does_not_leak(self):
        """(11) Libur lokasi tidak terbaca lokasi lain."""
        safety_day = date(2026, 7, 1)

        Holiday.objects.create(
            scope=HolidayScope.LOCATION,
            company=self.company_a,
            location=self.port,
            date=safety_day,
            code="SAFETY-PORT",
            name="Sagea Port Operational Safety Day",
        )

        self.assertIn(
            safety_day,
            self.resolve(self.company_a, self.port),
        )

        # Lokasi lain di company yang sama: tidak.
        self.assertNotIn(
            safety_day,
            self.resolve(self.company_a, self.mine),
        )

        # Company lain: apalagi.
        self.assertNotIn(
            safety_day,
            self.resolve(self.company_b, self.jetty),
        )

    def test_national_holiday_still_applies_at_a_location(self):
        """
        Cakupan hari libur **digabung**, bukan dipilih yang paling
        spesifik.

        Kalau resolver memilih satu cakupan saja, lokasi yang kebetulan
        punya Safety Day sendiri akan kehilangan 17 Agustus — dan
        pegawainya tercatat bolos di hari libur nasional.
        """
        self.make_national()

        Holiday.objects.create(
            scope=HolidayScope.LOCATION,
            company=self.company_a,
            location=self.port,
            date=date(2026, 7, 1),
            code="SAFETY-PORT",
            name="Sagea Port Operational Safety Day",
        )

        resolved = self.resolve(self.company_a, self.port)

        self.assertIn(self.NATIONAL_DAY, resolved)
        self.assertIn(date(2026, 7, 1), resolved)

    def test_selected_companies_uses_relation_not_duplicate_rows(self):
        """Satu baris + tabel relasi, bukan tiga baris identik."""
        joint_leave = date(2026, 12, 24)

        holiday = Holiday.objects.create(
            scope=HolidayScope.SELECTED_COMPANIES,
            company=None,
            location=None,
            date=joint_leave,
            code="CUTI-BERSAMA-2026",
            name="Cuti Bersama Natal",
        )

        HolidayCompany.objects.create(holiday=holiday, company=self.company_a)

        self.assertEqual(Holiday.objects.count(), 1)

        self.assertIn(joint_leave, self.resolve(self.company_a))
        self.assertNotIn(joint_leave, self.resolve(self.company_b))

    def test_removed_selected_company_stops_applying(self):
        joint_leave = date(2026, 12, 24)

        holiday = Holiday.objects.create(
            scope=HolidayScope.SELECTED_COMPANIES,
            date=joint_leave,
            code="CUTI-BERSAMA-2026",
            name="Cuti Bersama Natal",
        )

        link = HolidayCompany.objects.create(
            holiday=holiday,
            company=self.company_a,
        )

        link.is_deleted = True
        link.save(update_fields=["is_deleted"])

        self.assertNotIn(joint_leave, self.resolve(self.company_a))

    def test_pending_sync_holiday_is_not_effective(self):
        """
        Gerbang review: hasil sync yang belum dikonfirmasi **tidak**
        menggeser hari kerja siapa pun.

        Ini sifat yang membuat sumber luar aman dipasang nanti — tanpa
        ini, feed yang salah satu tanggalnya keliru langsung mengubah
        perhitungan payroll.
        """
        self.make_national(sync_status=HolidaySyncStatus.PENDING)

        self.assertNotIn(self.NATIONAL_DAY, self.resolve(self.company_a))

        holiday = Holiday.objects.get(code="INDEPENDENCE-2026")
        holiday.sync_status = HolidaySyncStatus.CONFIRMED
        holiday.save(update_fields=["sync_status"])

        self.assertIn(self.NATIONAL_DAY, self.resolve(self.company_a))

    def test_holiday_outside_range_is_not_returned(self):
        self.make_national()

        resolved = CalendarResolver.resolve_holidays(
            company_id=self.company_a.id,
            location_id=None,
            start=date(2026, 1, 1),
            end=date(2026, 6, 30),
        )

        self.assertNotIn(self.NATIONAL_DAY, resolved)

    def test_two_events_may_share_one_date(self):
        """
        Constraint lama `(company, location, date)` membuat ini
        mustahil: satu perusahaan tidak boleh punya dua peristiwa di
        tanggal yang sama, sehingga HUT perusahaan yang jatuh di
        tanggal merah tidak bisa dicatat sama sekali.
        """
        Holiday.objects.create(
            scope=HolidayScope.COMPANY,
            company=self.company_a,
            date=self.NATIONAL_DAY,
            code="MMR-ANNIV",
            name="MMR Anniversary",
        )

        Holiday.objects.create(
            scope=HolidayScope.COMPANY,
            company=self.company_a,
            date=self.NATIONAL_DAY,
            code="MMR-FAMILY-DAY",
            name="MMR Family Day",
        )

        self.assertEqual(
            Holiday.objects.filter(date=self.NATIONAL_DAY).count(),
            2,
        )
