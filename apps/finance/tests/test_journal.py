"""Jurnal dan barisnya: keseimbangan, sisi, dan akun yang sah."""

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db.utils import IntegrityError

from apps.finance.models import (
    AccountType,
    Journal,
    JournalLine,
    JournalStatus,
)
from apps.finance.services import JournalLineService, JournalService

from .base import AS_OF, FinanceTestCase


class JournalLineRuleTests(FinanceTestCase):
    def test_balanced_journal_is_accepted(self):
        company = self.make_company()
        self.make_fiscal_year(company)

        expense, payable = self.make_pair(company)

        journal = self.make_journal(
            company, lines=self.balanced_lines(expense, payable, "2500.00"),
        )

        self.assertEqual(journal.total_debit, Decimal("2500.00"))
        self.assertEqual(journal.total_credit, Decimal("2500.00"))
        self.assertTrue(journal.is_balanced)

        # Tidak melempar.
        JournalService.assert_balanced(journal)

    def test_unbalanced_journal_is_rejected(self):
        company = self.make_company()
        self.make_fiscal_year(company)

        expense, payable = self.make_pair(company)

        journal = self.make_journal(company, lines=[
            {"account": expense, "debit": Decimal("1000.00"), "credit": Decimal("0.00")},
            {"account": payable, "debit": Decimal("0.00"), "credit": Decimal("900.00")},
        ])

        with self.assertRaises(ValidationError) as ctx:
            JournalService.assert_balanced(journal)

        message = " ".join(ctx.exception.message_dict["lines"])

        # Selisihnya disebut — "tidak seimbang" tanpa angka memaksa
        # orang menjumlah sendiri kolom yang baru saja diketiknya.
        self.assertIn("100", message)

    def test_line_with_both_sides_is_rejected(self):
        company = self.make_company()
        self.make_fiscal_year(company)

        expense, payable = self.make_pair(company)

        journal = self.make_journal(company)

        with self.assertRaises(ValidationError) as ctx:
            JournalService.replace_lines(journal=journal, lines=[
                {
                    "account": expense,
                    "debit": Decimal("100.00"),
                    "credit": Decimal("100.00"),
                },
            ])

        self.assertIn("credit", ctx.exception.message_dict)

    def test_zero_line_is_rejected(self):
        company = self.make_company()
        self.make_fiscal_year(company)

        expense, _ = self.make_pair(company)

        journal = self.make_journal(company)

        with self.assertRaises(ValidationError) as ctx:
            JournalService.replace_lines(journal=journal, lines=[
                {
                    "account": expense,
                    "debit": Decimal("0.00"),
                    "credit": Decimal("0.00"),
                },
            ])

        self.assertIn("debit", ctx.exception.message_dict)

    def test_negative_amount_is_rejected(self):
        company = self.make_company()
        self.make_fiscal_year(company)

        expense, _ = self.make_pair(company)

        journal = self.make_journal(company)

        with self.assertRaises(ValidationError):
            JournalService.replace_lines(journal=journal, lines=[
                {
                    "account": expense,
                    "debit": Decimal("-100.00"),
                    "credit": Decimal("0.00"),
                },
            ])

    def test_database_rejects_a_zero_line_written_directly(self):
        """
        Aturan satu sisi ditegakkan **database**, bukan cuma `clean()`.

        Importer, seed, perintah manajemen, dan `bulk_create` semuanya
        melewati `full_clean()` — dan satu baris bersaldo nol di tengah
        sepuluh juta baris tidak akan pernah ditemukan siapa pun.
        """
        company = self.make_company()
        self.make_fiscal_year(company)

        expense, _ = self.make_pair(company)

        journal = self.make_journal(company)

        with self.assertRaises(IntegrityError):
            JournalLine.objects.create(
                journal=journal,
                line_number=1,
                account=expense,
                company=company,
                transaction_currency=self.currency,
                debit=Decimal("0.00"),
                credit=Decimal("0.00"),
            )

    def test_account_from_another_company_is_rejected(self):
        first = self.make_company()
        second = self.make_company()

        self.make_fiscal_year(first)

        foreign, _ = self.make_pair(second)
        _, payable = self.make_pair(first)

        journal = self.make_journal(first)

        with self.assertRaises(ValidationError) as ctx:
            JournalService.replace_lines(
                journal=journal,
                lines=self.balanced_lines(foreign, payable),
            )

        self.assertIn("account", ctx.exception.message_dict)

    def test_journal_number_comes_from_the_numbering_master(self):
        company = self.make_company()
        self.make_fiscal_year(company)

        journal = self.make_journal(company)

        self.assertTrue(journal.journal_number.startswith("JV-"))

    def test_period_and_fiscal_year_are_derived_from_the_posting_date(self):
        company = self.make_company()
        fiscal_year = self.make_fiscal_year(company)

        journal = self.make_journal(company, posting_date=date(2027, 7, 4))

        self.assertEqual(journal.fiscal_year_id, fiscal_year.pk)
        self.assertTrue(journal.accounting_period.contains(date(2027, 7, 4)))

    def test_base_amounts_are_computed_not_accepted(self):
        """
        Nilai mata uang buku dihitung, tidak pernah diterima dari klien.

        Kalau dikirim, debit dan kredit bisa seimbang dalam mata uang
        transaksi dan tidak seimbang di buku besar — dan yang dibaca
        laporan justru yang kedua.
        """
        company = self.make_company()
        self.make_fiscal_year(company)

        expense, payable = self.make_pair(company)

        journal = self.make_journal(company)

        JournalService.replace_lines(journal=journal, lines=[
            {
                "account": expense,
                "debit": Decimal("100.00"),
                "credit": Decimal("0.00"),
                # Kiriman yang bohong — harus diabaikan.
                "base_debit": Decimal("999999.00"),
            },
            {
                "account": payable,
                "debit": Decimal("0.00"),
                "credit": Decimal("100.00"),
            },
        ])

        line = journal.lines.order_by("line_number").first()

        self.assertEqual(line.base_debit, Decimal("100.00"))


class JournalLineResourceTests(FinanceTestCase):
    """Grid baris jurnal — jalur yang dipakai layar."""

    def test_adding_a_line_renumbers_and_syncs_totals(self):
        company = self.make_company()
        self.make_fiscal_year(company)

        expense, payable = self.make_pair(company)

        journal = self.make_journal(company)

        first = JournalLineService.create(data={
            "journal": journal,
            "account": expense,
            "debit": Decimal("750.00"),
            "credit": Decimal("0.00"),
        })

        second = JournalLineService.create(data={
            "journal": journal,
            "account": payable,
            "debit": Decimal("0.00"),
            "credit": Decimal("750.00"),
        })

        self.assertEqual(first.line_number, 1)
        self.assertEqual(second.line_number, 2)

        journal.refresh_from_db()

        self.assertEqual(journal.total_debit, Decimal("750.00"))
        self.assertEqual(journal.total_credit, Decimal("750.00"))

    def test_deleting_a_line_syncs_totals(self):
        company = self.make_company()
        self.make_fiscal_year(company)

        expense, payable = self.make_pair(company)

        journal = self.make_journal(
            company, lines=self.balanced_lines(expense, payable),
        )

        line = journal.lines.order_by("line_number").first()

        JournalLineService.soft_delete(instance=line)

        journal.refresh_from_db()

        self.assertEqual(journal.total_debit, Decimal("0.00"))
        self.assertEqual(journal.total_credit, Decimal("1000.00"))

    def test_line_cannot_be_moved_to_another_journal(self):
        company = self.make_company()
        self.make_fiscal_year(company)

        expense, payable = self.make_pair(company)

        source = self.make_journal(
            company, lines=self.balanced_lines(expense, payable),
        )
        target = self.make_journal(company)

        line = source.lines.order_by("line_number").first()

        JournalLineService.update(
            instance=line, data={"journal": target},
        )

        line.refresh_from_db()

        # Pindah jurnal adalah penerbitan yang menyamar jadi
        # penyuntingan — dan jurnal tujuannya mungkin sudah diposting.
        self.assertEqual(line.journal_id, source.pk)


class JournalStateTests(FinanceTestCase):
    def test_new_journal_starts_as_a_draft(self):
        company = self.make_company()
        self.make_fiscal_year(company)

        journal = self.make_journal(company)

        self.assertEqual(journal.status, JournalStatus.DRAFT)

    def test_cancel_closes_an_unposted_journal(self):
        company = self.make_company()
        self.make_fiscal_year(company)

        journal = self.make_journal(company)

        JournalService.cancel(journal=journal, reason="salah input")

        journal.refresh_from_db()

        self.assertEqual(journal.status, JournalStatus.CANCELLED)
        self.assertEqual(journal.status_reason, "salah input")
        self.assertIsNotNone(journal.cancelled_at)

    def test_submitting_without_a_workflow_approves_directly(self):
        """
        Tenant yang tidak mewajibkan persetujuan jurnal harus tetap
        bisa memakai Finance.

        Menolak dengan "belum ada alur" membuat modulnya tidak bisa
        dipakai sama sekali sampai seseorang mengonfigurasi approval
        yang tidak ia inginkan.
        """
        company = self.make_company()
        self.make_fiscal_year(company)

        expense, payable = self.make_pair(company)

        journal = self.make_journal(
            company, lines=self.balanced_lines(expense, payable),
        )

        instance = JournalService.submit(journal=journal)

        journal.refresh_from_db()

        self.assertIsNone(instance)
        self.assertEqual(journal.status, JournalStatus.APPROVED)
        self.assertIsNotNone(journal.approved_at)

    def test_unbalanced_journal_cannot_be_submitted(self):
        company = self.make_company()
        self.make_fiscal_year(company)

        expense, payable = self.make_pair(company)

        journal = self.make_journal(company, lines=[
            {"account": expense, "debit": Decimal("10.00"), "credit": Decimal("0.00")},
            {"account": payable, "debit": Decimal("0.00"), "credit": Decimal("5.00")},
        ])

        with self.assertRaises(ValidationError):
            JournalService.submit(journal=journal)

    def test_empty_journal_cannot_be_submitted(self):
        company = self.make_company()
        self.make_fiscal_year(company)

        journal = self.make_journal(company)

        with self.assertRaises(ValidationError) as ctx:
            JournalService.submit(journal=journal)

        self.assertIn("lines", ctx.exception.message_dict)
