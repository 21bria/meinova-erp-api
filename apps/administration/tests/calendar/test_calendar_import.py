"""
Regresi import Work Calendar dan Holiday.

Yang dikunci: **file yang menyatakan satu baris GLOBAL menghasilkan
satu record**, dan mengunggah file yang sama dua kali tidak menerbitkan
salinan. Keduanya diperiksa dengan menghitung baris database, bukan
dengan membaca laporan importer — laporan yang benar di atas data yang
terduplikasi tetap duplikasi.

Pipeline-nya dipanggil utuh (`ImportPipelineService.execute`), bukan
`write()` langsung: yang mau diuji termasuk normalisasi header,
validasi, dan resolusi cakupan.
"""

from __future__ import annotations

import csv
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from django_tenants.test.cases import TenantTestCase

from apps.administration.imports.calendar import (
    HolidayImporter,
    WorkCalendarImporter,
)
from apps.administration.models import (
    CalendarScope,
    Company,
    Holiday,
    HolidayCompany,
    HolidayScope,
    HolidaySource,
    HolidaySyncStatus,
    Location,
    WorkCalendar,
)
from apps.framework.imports import ImportPipelineService


class CalendarImportTestCase(TenantTestCase):
    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "calendar-import-test"
        tenant.name = "Calendar Import Test"

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

    def setUp(self):
        super().setUp()

        WorkCalendar.objects.all().delete()
        Holiday.objects.all().delete()

        self._tempdir = TemporaryDirectory()

        self.addCleanup(self._tempdir.cleanup)

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    def write_csv(self, columns, rows) -> Path:
        path = Path(self._tempdir.name) / "import.csv"

        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=columns)

            writer.writeheader()

            for row in rows:
                writer.writerow(row)

        return path

    def run_import(self, importer, columns, rows):
        return ImportPipelineService.execute(
            module=importer,
            file_path=self.write_csv(columns, rows),
            source_type="csv",
        )

    def preview_import(self, importer, columns, rows):
        return ImportPipelineService.preview(
            module=importer,
            file_path=self.write_csv(columns, rows),
            source_type="csv",
        )


# ======================================================================
# WORK CALENDAR
# ======================================================================


WORK_CALENDAR_COLUMNS = list(WorkCalendarImporter.template_columns)


class WorkCalendarImportTests(CalendarImportTestCase):
    GLOBAL_ROW = {
        "code": "HO-STANDARD",
        "name": "Head Office Standard",
        "scope": "GLOBAL",
        "company": "",
        "location": "",
        "monday": "Y",
        "tuesday": "Y",
        "wednesday": "Y",
        "thursday": "Y",
        "friday": "Y",
        "saturday": "N",
        "sunday": "N",
        "is_default": "Y",
        "is_active": "Y",
    }

    def test_global_import_creates_one_row(self):
        """(14) Import Work Calendar GLOBAL tidak membuat duplicate."""
        result = self.run_import(
            WorkCalendarImporter,
            WORK_CALENDAR_COLUMNS,
            [self.GLOBAL_ROW],
        )

        self.assertEqual(result["created_rows"], 1)
        self.assertEqual(result["invalid_rows"], 0)

        # Dua company di tenant ini, tetap satu baris.
        self.assertEqual(WorkCalendar.objects.count(), 1)

        calendar = WorkCalendar.objects.get()

        self.assertEqual(calendar.scope, CalendarScope.GLOBAL)
        self.assertIsNone(calendar.company_id)
        self.assertIsNone(calendar.location_id)
        self.assertTrue(calendar.monday)
        self.assertFalse(calendar.saturday)

    def test_reimport_is_idempotent(self):
        """(13) Re-import mendeteksi baris yang sudah ada."""
        self.run_import(
            WorkCalendarImporter,
            WORK_CALENDAR_COLUMNS,
            [self.GLOBAL_ROW],
        )

        second = self.run_import(
            WorkCalendarImporter,
            WORK_CALENDAR_COLUMNS,
            [self.GLOBAL_ROW],
        )

        self.assertEqual(second["created_rows"], 0)
        self.assertEqual(second["updated_rows"], 1)

        self.assertEqual(WorkCalendar.objects.count(), 1)

    def test_update_is_visible_in_preview(self):
        """Penimpaan tidak pernah diam — preview menyebutnya UPDATE."""
        self.run_import(
            WorkCalendarImporter,
            WORK_CALENDAR_COLUMNS,
            [self.GLOBAL_ROW],
        )

        preview = self.preview_import(
            WorkCalendarImporter,
            WORK_CALENDAR_COLUMNS,
            [self.GLOBAL_ROW],
        )

        self.assertEqual(preview["rows"][0]["action"], "UPDATE")

        fresh = self.preview_import(
            WorkCalendarImporter,
            WORK_CALENDAR_COLUMNS,
            [{**self.GLOBAL_ROW, "code": "OTHER"}],
        )

        self.assertEqual(fresh["rows"][0]["action"], "NEW")

    def test_global_row_with_company_is_rejected(self):
        result = self.run_import(
            WorkCalendarImporter,
            WORK_CALENDAR_COLUMNS,
            [{**self.GLOBAL_ROW, "company": "MMR"}],
        )

        self.assertEqual(result["created_rows"], 0)
        self.assertEqual(result["skipped_rows"], 1)
        self.assertEqual(WorkCalendar.objects.count(), 0)

        self.assertIn(
            "company",
            result["error_rows"][0]["errors"],
        )

    def test_company_scope_requires_company(self):
        result = self.run_import(
            WorkCalendarImporter,
            WORK_CALENDAR_COLUMNS,
            [{**self.GLOBAL_ROW, "scope": "COMPANY", "company": ""}],
        )

        self.assertEqual(result["skipped_rows"], 1)
        self.assertIn("company", result["error_rows"][0]["errors"])

    def test_location_scope_requires_matching_company(self):
        result = self.run_import(
            WorkCalendarImporter,
            WORK_CALENDAR_COLUMNS,
            [
                {
                    **self.GLOBAL_ROW,
                    "code": "SAGEA-MINE",
                    "scope": "LOCATION",
                    # Sagea Mine milik MMR, bukan MLS.
                    "company": "MLS",
                    "location": "SAGEA-MINE",
                },
            ],
        )

        self.assertEqual(result["skipped_rows"], 1)
        self.assertIn("location", result["error_rows"][0]["errors"])

    def test_location_scope_is_imported(self):
        result = self.run_import(
            WorkCalendarImporter,
            WORK_CALENDAR_COLUMNS,
            [
                {
                    **self.GLOBAL_ROW,
                    "code": "SAGEA-MINE",
                    "name": "Sagea Mine",
                    "scope": "LOCATION",
                    "company": "MMR",
                    "location": "SAGEA-MINE",
                    "saturday": "Y",
                    "sunday": "Y",
                    "is_default": "N",
                },
            ],
        )

        self.assertEqual(result["created_rows"], 1)

        calendar = WorkCalendar.objects.get()

        self.assertEqual(calendar.scope, CalendarScope.LOCATION)
        self.assertEqual(calendar.company_id, self.company_a.id)
        self.assertEqual(calendar.location_id, self.mine.id)
        self.assertTrue(calendar.sunday)

    def test_global_and_company_may_share_a_code(self):
        """
        `HO-STANDARD` GLOBAL dan `HO-STANDARD` milik satu perusahaan
        adalah dua master yang berbeda.

        Kalau importer mencocokkan lewat kode saja, baris kedua akan
        **menimpa** yang pertama — dan kalender seluruh tenant berubah
        jadi milik satu perusahaan.
        """
        result = self.run_import(
            WorkCalendarImporter,
            WORK_CALENDAR_COLUMNS,
            [
                self.GLOBAL_ROW,
                {
                    **self.GLOBAL_ROW,
                    "scope": "COMPANY",
                    "company": "MMR",
                    "is_default": "N",
                },
            ],
        )

        self.assertEqual(result["created_rows"], 2)
        self.assertEqual(WorkCalendar.objects.count(), 2)

    def test_all_days_off_is_rejected(self):
        """
        Kalender tanpa satu pun hari kerja membuat setiap cuti memotong
        nol hari dan prorata gaji jadi nol — dan tidak ada layar yang
        menunjukkan sebabnya.
        """
        result = self.run_import(
            WorkCalendarImporter,
            WORK_CALENDAR_COLUMNS,
            [
                {
                    **self.GLOBAL_ROW,
                    **{
                        day: "N"
                        for day in (
                            "monday",
                            "tuesday",
                            "wednesday",
                            "thursday",
                            "friday",
                            "saturday",
                            "sunday",
                        )
                    },
                },
            ],
        )

        self.assertEqual(result["skipped_rows"], 1)
        self.assertEqual(WorkCalendar.objects.count(), 0)

    def test_indonesian_headers_are_accepted(self):
        columns = ["kode", "nama", "cakupan", "senin", "sabtu"]

        result = self.run_import(
            WorkCalendarImporter,
            columns,
            [
                {
                    "kode": "HO-ID",
                    "nama": "Kantor Pusat",
                    "cakupan": "SEMUA",
                    "senin": "Ya",
                    "sabtu": "Tidak",
                },
            ],
        )

        self.assertEqual(result["created_rows"], 1)

        calendar = WorkCalendar.objects.get()

        self.assertEqual(calendar.scope, CalendarScope.GLOBAL)
        self.assertTrue(calendar.monday)
        self.assertFalse(calendar.saturday)


# ======================================================================
# HOLIDAY
# ======================================================================


HOLIDAY_COLUMNS = list(HolidayImporter.template_columns)


class HolidayImportTests(CalendarImportTestCase):
    NATIONAL_ROW = {
        "date": "2026-08-17",
        "code": "INDEPENDENCE-2026",
        "name": "Indonesia Independence Day",
        "scope": "NATIONAL",
        "country_code": "ID",
        "company": "",
        "location": "",
        "is_national": "Y",
        "is_recurring": "N",
        "is_active": "Y",
        "source": "IMPORT",
    }

    def test_global_holiday_import_creates_one_row(self):
        """(12) Import global holiday tidak membuat row per company."""
        result = self.run_import(
            HolidayImporter,
            HOLIDAY_COLUMNS,
            [self.NATIONAL_ROW],
        )

        self.assertEqual(result["created_rows"], 1)

        self.assertEqual(Holiday.objects.count(), 1)
        self.assertEqual(HolidayCompany.objects.count(), 0)

        holiday = Holiday.objects.get()

        self.assertEqual(holiday.scope, HolidayScope.GLOBAL)
        self.assertIsNone(holiday.company_id)
        self.assertEqual(holiday.date, date(2026, 8, 17))
        self.assertEqual(holiday.country_code, "ID")
        self.assertEqual(holiday.source, HolidaySource.IMPORT)

        # Import lewat file **tidak** melewati gerbang review: yang
        # mengunggahnya sudah membaca preview-nya.
        self.assertEqual(holiday.sync_status, HolidaySyncStatus.CONFIRMED)

    def test_reimport_does_not_duplicate_national_holiday(self):
        """(13) Re-import idempotent, tidak menerbitkan salinan."""
        self.run_import(HolidayImporter, HOLIDAY_COLUMNS, [self.NATIONAL_ROW])

        second = self.run_import(
            HolidayImporter,
            HOLIDAY_COLUMNS,
            [self.NATIONAL_ROW],
        )

        self.assertEqual(second["created_rows"], 0)
        self.assertEqual(second["updated_rows"], 1)

        self.assertEqual(Holiday.objects.count(), 1)

    def test_selected_companies_creates_one_row_with_links(self):
        result = self.run_import(
            HolidayImporter,
            HOLIDAY_COLUMNS,
            [
                {
                    **self.NATIONAL_ROW,
                    "date": "2026-12-24",
                    "code": "CUTI-BERSAMA-2026",
                    "name": "Cuti Bersama Natal",
                    "scope": "SELECTED_COMPANIES",
                    "company": "MMR,MLS",
                    "is_national": "N",
                },
            ],
        )

        self.assertEqual(result["created_rows"], 1)

        self.assertEqual(Holiday.objects.count(), 1)

        holiday = Holiday.objects.get()

        self.assertEqual(holiday.scope, HolidayScope.SELECTED_COMPANIES)
        self.assertIsNone(holiday.company_id)

        self.assertEqual(
            set(
                holiday.companies
                .filter(is_deleted=False)
                .values_list("company_id", flat=True),
            ),
            {self.company_a.id, self.company_b.id},
        )

    def test_selected_companies_reimport_removes_dropped_company(self):
        rows = [
            {
                **self.NATIONAL_ROW,
                "date": "2026-12-24",
                "code": "CUTI-BERSAMA-2026",
                "name": "Cuti Bersama Natal",
                "scope": "SELECTED_COMPANIES",
                "company": "MMR,MLS",
                "is_national": "N",
            },
        ]

        self.run_import(HolidayImporter, HOLIDAY_COLUMNS, rows)

        rows[0]["company"] = "MMR"

        self.run_import(HolidayImporter, HOLIDAY_COLUMNS, rows)

        holiday = Holiday.objects.get()

        self.assertEqual(
            set(
                holiday.companies
                .filter(is_deleted=False)
                .values_list("company_id", flat=True),
            ),
            {self.company_a.id},
        )

    def test_unknown_company_is_rejected(self):
        result = self.run_import(
            HolidayImporter,
            HOLIDAY_COLUMNS,
            [
                {
                    **self.NATIONAL_ROW,
                    "scope": "COMPANY",
                    "company": "TIDAK-ADA",
                },
            ],
        )

        self.assertEqual(result["skipped_rows"], 1)
        self.assertEqual(Holiday.objects.count(), 0)

    def test_bad_date_is_rejected_with_a_message(self):
        result = self.run_import(
            HolidayImporter,
            HOLIDAY_COLUMNS,
            [{**self.NATIONAL_ROW, "date": "17 Agustus"}],
        )

        self.assertEqual(result["skipped_rows"], 1)
        self.assertEqual(Holiday.objects.count(), 0)

    def test_national_synonym_maps_to_global_scope(self):
        for value in ("NATIONAL", "GLOBAL", "ALL", "semua"):
            with self.subTest(scope=value):
                Holiday.objects.all().delete()

                self.run_import(
                    HolidayImporter,
                    HOLIDAY_COLUMNS,
                    [{**self.NATIONAL_ROW, "scope": value}],
                )

                self.assertEqual(
                    Holiday.objects.get().scope,
                    HolidayScope.GLOBAL,
                )

    def test_template_has_the_required_columns(self):
        """
        Template harus memuat kolom yang disyaratkan; kolomnya juga
        yang dibaca importer.
        """
        for column in (
            "date",
            "code",
            "name",
            "scope",
            "country_code",
            "company",
            "location",
            "is_national",
            "is_recurring",
            "is_active",
            "source",
        ):
            self.assertIn(column, HolidayImporter.get_template_columns())

        for column in (
            "code",
            "name",
            "scope",
            "company",
            "location",
            "monday",
            "sunday",
            "is_default",
            "is_active",
        ):
            self.assertIn(
                column,
                WorkCalendarImporter.get_template_columns(),
            )
