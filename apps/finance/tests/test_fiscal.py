"""Tahun buku dan periode: tanggal, irisan, dan perpindahan status."""

from datetime import date

from django.core.exceptions import ValidationError

from apps.finance.models import FiscalYear, PeriodStatus
from apps.finance.services import (
    AccountingPeriodService,
    FiscalPeriodService,
    FiscalYearService,
)

from .base import FinanceTestCase


class FiscalYearTests(FinanceTestCase):
    def test_end_date_must_follow_start_date(self):
        company = self.make_company()

        with self.assertRaises(ValidationError) as ctx:
            FiscalYearService.create(data={
                "company": company,
                "code": self.next_code("FY"),
                "name": "Backwards",
                "start_date": date(2027, 12, 31),
                "end_date": date(2027, 1, 1),
            })

        self.assertIn("end_date", ctx.exception.message_dict)

    def test_overlapping_fiscal_years_are_rejected(self):
        company = self.make_company()

        self.make_fiscal_year(company, year=2027, periods=0)

        with self.assertRaises(ValidationError) as ctx:
            FiscalYearService.create(data={
                "company": company,
                "code": self.next_code("FY"),
                "name": "Overlapping",
                "start_date": date(2027, 6, 1),
                "end_date": date(2028, 5, 31),
            })

        self.assertIn("start_date", ctx.exception.message_dict)

    def test_other_companies_may_use_the_same_dates(self):
        first = self.make_company()
        second = self.make_company()

        self.make_fiscal_year(first, year=2027, periods=0)

        # Irisan dijaga **per perusahaan**. Satu tenant boleh memuat
        # dua belas badan usaha yang tahun bukunya sama persis.
        self.make_fiscal_year(second, year=2027, periods=0)

        self.assertEqual(
            FiscalYear.objects.filter(
                company__in=[first, second], is_deleted=False,
            ).count(),
            2,
        )

    def test_non_calendar_fiscal_year_works(self):
        """
        §4: 1 April 2026 – 31 Maret 2027 harus berjalan sama saja.

        Ini yang paling gampang salah kalau ada satu baris pun yang
        mengasumsikan Januari–Desember.
        """
        company = self.make_company()

        fiscal_year = FiscalYearService.create(data={
            "company": company,
            "code": self.next_code("FY"),
            "name": "FY2026/27",
            "start_date": date(2026, 4, 1),
            "end_date": date(2027, 3, 31),
        })

        periods = FiscalYearService.generate_periods(
            fiscal_year=fiscal_year, count=12,
        )

        self.assertEqual(len(periods), 12)
        self.assertEqual(periods[0].start_date, date(2026, 4, 1))
        self.assertEqual(periods[-1].end_date, date(2027, 3, 31))

        # Tidak ada tanggal di dalam tahun buku yang jatuh di luar
        # periode mana pun — kalau ada, tanggal itu tidak bisa
        # dibukukan sama sekali dan tidak ada pesan yang menyebutnya.
        resolved = FiscalPeriodService.resolve(
            company=company, posting_date=date(2027, 2, 14),
        )

        self.assertEqual(resolved.fiscal_year_id, fiscal_year.pk)

    def test_quarterly_periods_are_supported(self):
        company = self.make_company()

        fiscal_year = self.make_fiscal_year(company, periods=0)

        periods = FiscalYearService.generate_periods(
            fiscal_year=fiscal_year, count=4,
        )

        self.assertEqual(len(periods), 4)
        self.assertEqual(periods[0].start_date, fiscal_year.start_date)
        self.assertEqual(periods[-1].end_date, fiscal_year.end_date)

    def test_generating_periods_twice_is_rejected(self):
        company = self.make_company()

        fiscal_year = self.make_fiscal_year(company, periods=12)

        with self.assertRaises(ValidationError):
            FiscalYearService.generate_periods(
                fiscal_year=fiscal_year, count=12,
            )

    def test_only_one_fiscal_year_is_current_per_company(self):
        company = self.make_company()

        first = self.make_fiscal_year(company, year=2027, periods=0)
        FiscalYearService.update(instance=first, data={"is_current": True})

        second = FiscalYearService.create(data={
            "company": company,
            "code": self.next_code("FY"),
            "name": "FY2028",
            "start_date": date(2028, 1, 1),
            "end_date": date(2028, 12, 31),
            "is_current": True,
        })

        first.refresh_from_db()

        self.assertFalse(first.is_current)
        self.assertTrue(second.is_current)


class AccountingPeriodTests(FinanceTestCase):
    def test_period_must_sit_inside_its_fiscal_year(self):
        company = self.make_company()

        fiscal_year = self.make_fiscal_year(company, periods=0)

        with self.assertRaises(ValidationError) as ctx:
            AccountingPeriodService.create(data={
                "fiscal_year": fiscal_year,
                "period_number": 1,
                "code": "OUT",
                "name": "Outside",
                "start_date": date(2028, 1, 1),
                "end_date": date(2028, 1, 31),
            })

        self.assertIn("start_date", ctx.exception.message_dict)

    def test_overlapping_periods_are_rejected(self):
        company = self.make_company()

        fiscal_year = self.make_fiscal_year(company, periods=12)

        with self.assertRaises(ValidationError) as ctx:
            AccountingPeriodService.create(data={
                "fiscal_year": fiscal_year,
                "period_number": 99,
                "code": "DUP",
                "name": "Overlap",
                "start_date": date(2027, 3, 10),
                "end_date": date(2027, 3, 20),
            })

        self.assertIn("start_date", ctx.exception.message_dict)

    def test_status_transitions_follow_the_map(self):
        company = self.make_company()
        self.make_fiscal_year(company)

        period = self.period_for(company, date(2027, 3, 15))

        self.assertEqual(period.status, PeriodStatus.OPEN)

        period = AccountingPeriodService.change_status(
            period=period, status=PeriodStatus.SOFT_CLOSED,
        )
        self.assertEqual(period.status, PeriodStatus.SOFT_CLOSED)
        self.assertIsNotNone(period.closed_at)

        period = AccountingPeriodService.change_status(
            period=period, status=PeriodStatus.CLOSED,
        )
        self.assertEqual(period.status, PeriodStatus.CLOSED)

        period = AccountingPeriodService.change_status(
            period=period, status=PeriodStatus.LOCKED,
        )
        self.assertEqual(period.status, PeriodStatus.LOCKED)

    def test_locked_period_cannot_jump_straight_to_open(self):
        """
        Dari LOCKED hanya boleh ke CLOSED.

        Membukanya langsung ke OPEN berarti periode yang sudah diaudit
        kembali menerima transaksi harian dalam satu klik.
        """
        company = self.make_company()
        self.make_fiscal_year(company)

        period = self.period_for(company, date(2027, 3, 15))

        for status in (
            PeriodStatus.SOFT_CLOSED,
            PeriodStatus.CLOSED,
            PeriodStatus.LOCKED,
        ):
            period = AccountingPeriodService.change_status(
                period=period, status=status,
            )

        with self.assertRaises(ValidationError) as ctx:
            AccountingPeriodService.change_status(
                period=period,
                status=PeriodStatus.OPEN,
                reason="mau dibuka",
            )

        self.assertIn("status", ctx.exception.message_dict)

    def test_reopening_a_locked_period_requires_a_reason(self):
        company = self.make_company()
        self.make_fiscal_year(company)

        period = self.period_for(company, date(2027, 3, 15))

        for status in (
            PeriodStatus.SOFT_CLOSED,
            PeriodStatus.CLOSED,
            PeriodStatus.LOCKED,
        ):
            period = AccountingPeriodService.change_status(
                period=period, status=status,
            )

        with self.assertRaises(ValidationError) as ctx:
            AccountingPeriodService.change_status(
                period=period, status=PeriodStatus.CLOSED, reason="   ",
            )

        self.assertIn("reason", ctx.exception.message_dict)

        reopened = AccountingPeriodService.change_status(
            period=period,
            status=PeriodStatus.CLOSED,
            reason="Koreksi audit 2027",
        )

        # Jejak penutupan **tidak** dihapus oleh pembukaan. Yang
        # ditanyakan auditor adalah "ditutup kapan, lalu dibuka lagi
        # kapan dan kenapa" — menghapus yang pertama membuang separuh
        # jawabannya.
        self.assertIsNotNone(reopened.closed_at)
        self.assertIsNotNone(reopened.reopened_at)
        self.assertEqual(reopened.reopen_reason, "Koreksi audit 2027")

    def test_resolve_explains_a_missing_fiscal_year(self):
        company = self.make_company()

        with self.assertRaises(ValidationError) as ctx:
            FiscalPeriodService.resolve(
                company=company, posting_date=date(2027, 3, 15),
            )

        message = " ".join(ctx.exception.message_dict["posting_date"])

        self.assertIn("tahun buku", message.lower())

    def test_resolve_distinguishes_missing_periods_from_missing_years(self):
        """
        Dua kegagalan yang berbeda menuntut dua tindakan yang berbeda —
        "buat tahun bukunya" vs "susun periodenya".
        """
        company = self.make_company()

        self.make_fiscal_year(company, periods=0)

        with self.assertRaises(ValidationError) as ctx:
            FiscalPeriodService.resolve(
                company=company, posting_date=date(2027, 3, 15),
            )

        message = " ".join(ctx.exception.message_dict["posting_date"])

        self.assertIn("Generate Periods", message)

    def test_period_holding_posted_journals_cannot_be_deleted(self):
        company = self.make_company()
        self.make_fiscal_year(company)

        expense, payable = self.make_pair(company)

        self.make_journal(
            company, lines=self.balanced_lines(expense, payable),
        )

        period = self.period_for(company, date(2027, 3, 15))

        with self.assertRaises(ValidationError):
            AccountingPeriodService.soft_delete(instance=period)
