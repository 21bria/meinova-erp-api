"""Posting engine dan pembalikan — inti yang tidak boleh salah."""

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError

from apps.accounts.models import User
from apps.finance.models import (
    JournalLine,
    JournalStatus,
    JournalType,
    PeriodStatus,
)
from apps.finance.services import (
    FinancePostingService,
    FinanceReversalService,
    JournalLineService,
    JournalService,
)

from .base import AS_OF, FinanceTestCase


class PostingTests(FinanceTestCase):
    def test_posting_stamps_who_and_when(self):
        company = self.make_company()
        self.make_fiscal_year(company)

        expense, payable = self.make_pair(company)

        user = User.objects.create_user(
            username=self.next_code("poster"), password="x",
        )

        journal = self.make_journal(
            company, lines=self.balanced_lines(expense, payable),
        )

        user = self.grant_finance(user, "finance.post_journal")

        result = FinancePostingService.post(journal=journal, user=user)

        posted = result.journal

        self.assertFalse(result.already_posted)
        self.assertEqual(posted.status, JournalStatus.POSTED)
        self.assertEqual(posted.posted_by_id, user.pk)
        self.assertIsNotNone(posted.posted_at)

    def test_posting_is_idempotent(self):
        """
        §9: klik dua kali, retry, atau permintaan yang diulang jaringan
        tidak boleh menghasilkan dampak buku besar yang kedua.

        Permintaan kedua **bukan error** — pemroses kejadian yang
        menerima error akan menandai kejadiannya gagal padahal jurnalnya
        justru sudah terbit.
        """
        company = self.make_company()
        self.make_fiscal_year(company)

        expense, payable = self.make_pair(company)

        journal = self.make_journal(
            company, lines=self.balanced_lines(expense, payable),
        )

        first = FinancePostingService.post(journal=journal)
        second = FinancePostingService.post(journal=journal)
        third = FinancePostingService.post(journal=journal)

        self.assertFalse(first.already_posted)
        self.assertTrue(second.already_posted)
        self.assertTrue(third.already_posted)

        # Yang menentukan: barisnya tetap dua, bukan enam.
        self.assertEqual(
            JournalLine.objects.filter(journal=journal, is_deleted=False).count(),
            2,
        )

        journal.refresh_from_db()

        self.assertEqual(journal.total_debit, Decimal("1000.00"))

    def test_posting_stamps_the_ledger_columns_on_every_line(self):
        company = self.make_company()
        self.make_fiscal_year(company)

        expense, payable = self.make_pair(company)

        journal = self.make_journal(
            company, lines=self.balanced_lines(expense, payable),
        )

        self.assertFalse(
            JournalLine.objects.filter(journal=journal, is_posted=True).exists()
        )

        FinancePostingService.post(journal=journal)

        for line in JournalLine.objects.filter(journal=journal):
            self.assertTrue(line.is_posted)
            self.assertEqual(line.posting_date, journal.posting_date)
            self.assertEqual(
                line.accounting_period_id, journal.accounting_period_id,
            )

    def test_posted_journal_is_immutable(self):
        company = self.make_company()
        self.make_fiscal_year(company)

        expense, payable = self.make_pair(company)

        journal = self.make_journal(
            company, lines=self.balanced_lines(expense, payable),
        )

        FinancePostingService.post(journal=journal)
        journal.refresh_from_db()

        with self.assertRaises(ValidationError):
            JournalService.assert_editable(journal)

        with self.assertRaises(ValidationError):
            JournalService.replace_lines(
                journal=journal,
                lines=self.balanced_lines(expense, payable, "5.00"),
            )

        with self.assertRaises(ValidationError):
            JournalService.soft_delete(instance=journal)

        line = journal.lines.first()

        with self.assertRaises(ValidationError):
            JournalLineService.update(
                instance=line, data={"debit": Decimal("1.00")},
            )

    def test_immutability_survives_a_stale_in_memory_object(self):
        """
        Gerbangnya membaca status dari database, bukan dari objek yang
        dioper.

        `FinancePostingService.post()` bekerja pada baris yang dikunci
        sendiri, jadi objek yang dipegang pemanggil tetap berkata
        `draft` sesudah jurnalnya benar-benar diposting. Tanpa
        pembacaan ulang, setiap pemanggil yang lupa `refresh_from_db()`
        bisa menyunting fakta akuntansi yang sudah masuk buku besar.
        """
        company = self.make_company()
        self.make_fiscal_year(company)

        expense, payable = self.make_pair(company)

        journal = self.make_journal(
            company, lines=self.balanced_lines(expense, payable),
        )

        FinancePostingService.post(journal=journal)

        # **Sengaja tidak** di-refresh.
        self.assertEqual(journal.status, JournalStatus.DRAFT)

        with self.assertRaises(ValidationError):
            JournalService.assert_editable(journal)

    def test_closed_period_blocks_posting(self):
        company = self.make_company()
        self.make_fiscal_year(company)

        expense, payable = self.make_pair(company)

        journal = self.make_journal(
            company, lines=self.balanced_lines(expense, payable),
        )

        self.close_period(self.period_for(company, AS_OF))

        with self.assertRaises(ValidationError) as ctx:
            FinancePostingService.post(journal=journal)

        self.assertIn("accounting_period", ctx.exception.message_dict)

        journal.refresh_from_db()

        # Atomik: statusnya tidak bergeser dan barisnya tidak tertandai.
        self.assertEqual(journal.status, JournalStatus.DRAFT)
        self.assertFalse(
            JournalLine.objects.filter(journal=journal, is_posted=True).exists()
        )

    def test_soft_closed_period_blocks_an_ordinary_operator(self):
        company = self.make_company()
        self.make_fiscal_year(company)

        expense, payable = self.make_pair(company)

        journal = self.make_journal(
            company, lines=self.balanced_lines(expense, payable),
        )

        self.close_period(
            self.period_for(company, AS_OF), status=PeriodStatus.SOFT_CLOSED,
        )

        operator = User.objects.create_user(
            username=self.next_code("op"), password="x",
        )

        # Izin posting dipegang — yang diuji di sini periodenya, bukan
        # wewenang memposting (FIN-B1/B2).
        operator = self.grant_finance(operator, "finance.post_journal")

        with self.assertRaises(ValidationError):
            FinancePostingService.post(journal=journal, user=operator)

    def test_soft_closed_period_allows_the_permitted_user(self):
        company = self.make_company()
        self.make_fiscal_year(company)

        expense, payable = self.make_pair(company)

        journal = self.make_journal(
            company, lines=self.balanced_lines(expense, payable),
        )

        self.close_period(
            self.period_for(company, AS_OF), status=PeriodStatus.SOFT_CLOSED,
        )

        closer = User.objects.create_superuser(
            username=self.next_code("closer"), password="x",
        )

        result = FinancePostingService.post(journal=journal, user=closer)

        self.assertEqual(result.journal.status, JournalStatus.POSTED)

    def test_unbalanced_journal_cannot_be_posted(self):
        company = self.make_company()
        self.make_fiscal_year(company)

        expense, payable = self.make_pair(company)

        journal = self.make_journal(company, lines=[
            {"account": expense, "debit": Decimal("10.00"), "credit": Decimal("0.00")},
            {"account": payable, "debit": Decimal("0.00"), "credit": Decimal("7.00")},
        ])

        with self.assertRaises(ValidationError):
            FinancePostingService.post(journal=journal)

    def test_empty_journal_cannot_be_posted(self):
        company = self.make_company()
        self.make_fiscal_year(company)

        journal = self.make_journal(company)

        with self.assertRaises(ValidationError):
            FinancePostingService.post(journal=journal)

    def test_posting_date_outside_its_period_is_rejected(self):
        """
        Periode diperiksa ulang terhadap tanggal posting saat posting,
        bukan dipercaya dari kolomnya.

        Tanggal boleh berubah sesudah periodenya dipilih, dan jurnal
        yang periodenya tidak lagi memuat tanggalnya akan mendarat di
        bulan yang salah di seluruh laporan.
        """
        company = self.make_company()
        self.make_fiscal_year(company)

        expense, payable = self.make_pair(company)

        journal = self.make_journal(
            company, lines=self.balanced_lines(expense, payable),
        )

        from apps.finance.models import Journal

        # Menggeser tanggalnya langsung di database, meniru PATCH yang
        # menembus service.
        Journal.objects.filter(pk=journal.pk).update(
            posting_date=date(2027, 11, 20),
        )

        journal.refresh_from_db()

        with self.assertRaises(ValidationError) as ctx:
            FinancePostingService.post(journal=journal)

        self.assertIn("posting_date", ctx.exception.message_dict)

    def test_post_many_reports_failures_without_stopping(self):
        company = self.make_company()
        self.make_fiscal_year(company)

        expense, payable = self.make_pair(company)

        good = self.make_journal(
            company, lines=self.balanced_lines(expense, payable),
        )
        bad = self.make_journal(company, lines=[
            {"account": expense, "debit": Decimal("5.00"), "credit": Decimal("0.00")},
            {"account": payable, "debit": Decimal("0.00"), "credit": Decimal("4.00")},
        ])

        result = FinancePostingService.post_many(journals=[good, bad])

        self.assertEqual(result["posted"], 1)
        self.assertEqual(len(result["failed"]), 1)

        good.refresh_from_db()
        bad.refresh_from_db()

        # Satu yang gagal tidak membatalkan yang sah.
        self.assertEqual(good.status, JournalStatus.POSTED)
        self.assertEqual(bad.status, JournalStatus.DRAFT)


class ReversalTests(FinanceTestCase):
    def _posted(self, company, amount="1000.00"):
        expense, payable = self.make_pair(company)

        journal = self.make_journal(
            company, lines=self.balanced_lines(expense, payable, amount),
        )

        FinancePostingService.post(journal=journal)
        journal.refresh_from_db()

        return journal, expense, payable

    def test_reversal_preserves_the_original(self):
        company = self.make_company()
        self.make_fiscal_year(company)

        original, expense, payable = self._posted(company)

        original_number = original.journal_number
        original_lines = list(
            original.lines.order_by("line_number").values(
                "account_id", "debit", "credit",
            )
        )

        reversal = FinanceReversalService.reverse(
            journal=original, reason="salah akun",
        )

        original.refresh_from_db()

        # Barisnya tidak disentuh sama sekali.
        self.assertEqual(
            list(
                original.lines.order_by("line_number").values(
                    "account_id", "debit", "credit",
                )
            ),
            original_lines,
        )
        self.assertEqual(original.journal_number, original_number)
        self.assertEqual(original.status, JournalStatus.REVERSED)

    def test_reversal_inverts_the_amounts(self):
        company = self.make_company()
        self.make_fiscal_year(company)

        original, expense, payable = self._posted(company, "1750.00")

        reversal = FinanceReversalService.reverse(
            journal=original, reason="koreksi",
        )

        by_account = {
            line.account_id: line
            for line in reversal.lines.all()
        }

        self.assertEqual(by_account[expense.pk].credit, Decimal("1750.00"))
        self.assertEqual(by_account[expense.pk].debit, Decimal("0.00"))
        self.assertEqual(by_account[payable.pk].debit, Decimal("1750.00"))
        self.assertEqual(by_account[payable.pk].credit, Decimal("0.00"))

    def test_reversal_relationship_is_two_way(self):
        company = self.make_company()
        self.make_fiscal_year(company)

        original, _, _ = self._posted(company)

        reversal = FinanceReversalService.reverse(
            journal=original, reason="koreksi",
        )

        original.refresh_from_db()

        self.assertEqual(reversal.reversal_of_id, original.pk)
        self.assertEqual(original.reversed_by_id, reversal.pk)
        self.assertEqual(reversal.journal_type, JournalType.REVERSAL)
        self.assertIsNotNone(original.reversed_at)

    def test_reversal_is_posted_and_balances_to_zero(self):
        company = self.make_company()
        self.make_fiscal_year(company)

        original, _, _ = self._posted(company)

        reversal = FinanceReversalService.reverse(
            journal=original, reason="koreksi",
        )

        reversal.refresh_from_db()

        self.assertEqual(reversal.status, JournalStatus.POSTED)
        self.assertEqual(reversal.total_debit, original.total_debit)
        self.assertEqual(reversal.total_credit, original.total_credit)

    def test_reversing_twice_is_rejected(self):
        """
        Membalik dua kali akan membukukan ayatnya kembali seperti
        semula — dan jumlahnya terlihat wajar di setiap layar.
        """
        company = self.make_company()
        self.make_fiscal_year(company)

        original, _, _ = self._posted(company)

        FinanceReversalService.reverse(journal=original, reason="sekali")

        original.refresh_from_db()

        with self.assertRaises(ValidationError):
            FinanceReversalService.reverse(journal=original, reason="dua kali")

    def test_reversal_requires_a_reason(self):
        company = self.make_company()
        self.make_fiscal_year(company)

        original, _, _ = self._posted(company)

        with self.assertRaises(ValidationError) as ctx:
            FinanceReversalService.reverse(journal=original, reason="   ")

        self.assertIn("reason", ctx.exception.message_dict)

    def test_unposted_journal_cannot_be_reversed(self):
        company = self.make_company()
        self.make_fiscal_year(company)

        expense, payable = self.make_pair(company)

        journal = self.make_journal(
            company, lines=self.balanced_lines(expense, payable),
        )

        with self.assertRaises(ValidationError):
            FinanceReversalService.reverse(journal=journal, reason="x")

    def test_reversal_can_land_in_a_later_open_period(self):
        """
        Kesalahan bulan lalu yang ketahuan bulan ini dibalik di bulan
        ini kalau periode lamanya sudah ditutup.
        """
        company = self.make_company()
        self.make_fiscal_year(company)

        original, _, _ = self._posted(company)

        self.close_period(self.period_for(company, AS_OF))

        reversal = FinanceReversalService.reverse(
            journal=original,
            reason="periode lama sudah ditutup",
            posting_date=date(2027, 5, 10),
        )

        self.assertEqual(reversal.posting_date, date(2027, 5, 10))
        self.assertTrue(
            reversal.accounting_period.contains(date(2027, 5, 10))
        )

    def test_reversal_keeps_the_source_document_trail(self):
        """
        Penelusuran dari dokumen sumber harus menemukan **keduanya**.

        Tanpa itu, dokumen sumber terlihat masih membawa dampak yang
        sebenarnya sudah dicabut.
        """
        company = self.make_company()
        self.make_fiscal_year(company)

        expense, payable = self.make_pair(company)

        journal = JournalService.create(data={
            "company": company,
            "posting_date": AS_OF,
            "source_module": "payroll",
            "source_type": "payroll_run",
            "source_id": "4321",
        })

        JournalService.replace_lines(
            journal=journal, lines=self.balanced_lines(expense, payable),
        )
        journal.refresh_from_db()

        FinancePostingService.post(journal=journal)
        journal.refresh_from_db()

        reversal = FinanceReversalService.reverse(
            journal=journal, reason="run dibatalkan",
        )

        self.assertEqual(reversal.source_module, "payroll")
        self.assertEqual(reversal.source_id, "4321")
