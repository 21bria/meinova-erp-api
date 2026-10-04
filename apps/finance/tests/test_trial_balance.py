"""Neraca saldo dan buku besar akun."""

from datetime import date
from decimal import Decimal

from apps.finance.models import AccountType
from apps.finance.services import (
    AccountLedgerQueryService,
    FinancePostingService,
    LedgerFilters,
    TrialBalanceQueryService,
)

from .base import FinanceTestCase


class TrialBalanceTests(FinanceTestCase):
    def _post(self, company, debit_account, credit_account, amount, when):
        journal = self.make_journal(
            company,
            posting_date=when,
            lines=self.balanced_lines(debit_account, credit_account, amount),
        )

        FinancePostingService.post(journal=journal)

        return journal

    def _filters(self, company, start, end, **extra):
        return LedgerFilters(
            company_id=company.pk,
            date_from=start,
            date_to=end,
            **extra,
        )

    def test_debit_and_credit_totals_reconcile(self):
        company = self.make_company()
        self.make_fiscal_year(company)

        expense, payable = self.make_pair(company)

        self._post(company, expense, payable, "1000.00", date(2027, 3, 5))
        self._post(company, expense, payable, "250.50", date(2027, 3, 20))

        report = TrialBalanceQueryService.build(
            self._filters(company, date(2027, 3, 1), date(2027, 3, 31))
        )

        self.assertTrue(report["is_balanced"])
        self.assertEqual(report["difference"], Decimal("0.00"))
        self.assertEqual(report["totals"]["debit"], Decimal("1250.50"))
        self.assertEqual(report["totals"]["credit"], Decimal("1250.50"))

    def test_movement_columns_are_period_bound(self):
        company = self.make_company()
        self.make_fiscal_year(company)

        expense, payable = self.make_pair(company)

        self._post(company, expense, payable, "400.00", date(2027, 2, 10))
        self._post(company, expense, payable, "600.00", date(2027, 3, 10))

        report = TrialBalanceQueryService.build(
            self._filters(company, date(2027, 3, 1), date(2027, 3, 31))
        )

        rows = {row["account_id"]: row for row in report["rows"]}

        # Hanya mutasi Maret.
        self.assertEqual(rows[expense.pk]["debit"], Decimal("600.00"))
        self.assertEqual(rows[payable.pk]["credit"], Decimal("600.00"))

    def test_balance_sheet_accounts_carry_their_opening_balance(self):
        company = self.make_company()
        self.make_fiscal_year(company)

        cash = self.make_account(
            company, name="Cash", account_type=AccountType.ASSET,
        )
        payable = self.make_account(
            company, name="Payable", account_type=AccountType.LIABILITY,
        )

        self._post(company, cash, payable, "900.00", date(2027, 1, 15))
        self._post(company, cash, payable, "100.00", date(2027, 3, 15))

        report = TrialBalanceQueryService.build(
            self._filters(company, date(2027, 3, 1), date(2027, 3, 31))
        )

        rows = {row["account_id"]: row for row in report["rows"]}

        # Kas per 1 Maret adalah kas yang ada sejak awal pembukuan.
        self.assertEqual(rows[cash.pk]["beginning_debit"], Decimal("900.00"))
        self.assertEqual(rows[cash.pk]["debit"], Decimal("100.00"))
        self.assertEqual(rows[cash.pk]["ending_debit"], Decimal("1000.00"))

        self.assertEqual(rows[payable.pk]["beginning_credit"], Decimal("900.00"))
        self.assertEqual(rows[payable.pk]["ending_credit"], Decimal("1000.00"))

    def test_income_statement_accounts_restart_each_fiscal_year(self):
        """
        Beban Januari **ikut** ke saldo awal Maret tahun yang sama, tapi
        tidak ikut ke tahun buku berikutnya.

        Menyamakan perlakuannya dengan akun neraca adalah kesalahan yang
        neraca saldonya **tetap seimbang** — debit dan kredit sama-sama
        salah dengan besar yang sama — jadi ia tidak pernah ketahuan
        dari total.
        """
        company = self.make_company()
        self.make_fiscal_year(company, year=2027)

        expense, payable = self.make_pair(company)

        self._post(company, expense, payable, "500.00", date(2027, 1, 20))

        report = TrialBalanceQueryService.build(
            self._filters(company, date(2027, 3, 1), date(2027, 3, 31))
        )

        rows = {row["account_id"]: row for row in report["rows"]}

        # Dalam tahun buku yang sama: terbawa.
        self.assertEqual(rows[expense.pk]["beginning_debit"], Decimal("500.00"))

        # Tahun buku berikutnya: mulai dari nol lagi.
        self.make_fiscal_year(company, year=2028)

        next_year = TrialBalanceQueryService.build(
            self._filters(company, date(2028, 3, 1), date(2028, 3, 31))
        )

        next_rows = {row["account_id"]: row for row in next_year["rows"]}

        self.assertNotIn(expense.pk, next_rows)

    def test_reversal_nets_the_account_to_zero(self):
        company = self.make_company()
        self.make_fiscal_year(company)

        expense, payable = self.make_pair(company)

        journal = self._post(
            company, expense, payable, "1000.00", date(2027, 3, 5),
        )

        from apps.finance.services import FinanceReversalService

        journal.refresh_from_db()

        FinanceReversalService.reverse(journal=journal, reason="koreksi")

        report = TrialBalanceQueryService.build(
            self._filters(company, date(2027, 3, 1), date(2027, 3, 31))
        )

        self.assertTrue(report["is_balanced"])

        net = sum(
            row["ending_debit"] - row["ending_credit"]
            for row in report["rows"]
        )

        self.assertEqual(net, Decimal("0.00"))

    def test_draft_journals_never_reach_the_trial_balance(self):
        company = self.make_company()
        self.make_fiscal_year(company)

        expense, payable = self.make_pair(company)

        # Dibuat tapi tidak diposting.
        self.make_journal(
            company,
            posting_date=date(2027, 3, 5),
            lines=self.balanced_lines(expense, payable),
        )

        report = TrialBalanceQueryService.build(
            self._filters(company, date(2027, 3, 1), date(2027, 3, 31))
        )

        self.assertEqual(report["rows"], [])
        self.assertEqual(report["totals"]["debit"], Decimal("0.00"))

    def test_another_company_is_never_included(self):
        first = self.make_company()
        second = self.make_company()

        self.make_fiscal_year(first)
        self.make_fiscal_year(second)

        a_expense, a_payable = self.make_pair(first)
        b_expense, b_payable = self.make_pair(second)

        self._post(first, a_expense, a_payable, "100.00", date(2027, 3, 5))
        self._post(second, b_expense, b_payable, "999.00", date(2027, 3, 5))

        report = TrialBalanceQueryService.build(
            self._filters(first, date(2027, 3, 1), date(2027, 3, 31))
        )

        account_ids = {row["account_id"] for row in report["rows"]}

        self.assertNotIn(b_expense.pk, account_ids)
        self.assertEqual(report["totals"]["debit"], Decimal("100.00"))

    def test_account_hierarchy_filter_uses_the_materialised_path(self):
        company = self.make_company()
        self.make_fiscal_year(company)

        group = self.make_account(
            company, name="Operating Expenses",
            account_type=AccountType.EXPENSE, posting_allowed=False,
        )
        inside = self.make_account(
            company, name="Salary", parent=group,
            account_type=AccountType.EXPENSE,
        )
        outside = self.make_account(
            company, name="Interest", account_type=AccountType.EXPENSE,
        )
        payable = self.make_account(
            company, name="Payable", account_type=AccountType.LIABILITY,
        )

        self._post(company, inside, payable, "300.00", date(2027, 3, 5))
        self._post(company, outside, payable, "700.00", date(2027, 3, 5))

        report = TrialBalanceQueryService.build(
            self._filters(
                company, date(2027, 3, 1), date(2027, 3, 31),
                account_root_id=group.pk,
            )
        )

        account_ids = {row["account_id"] for row in report["rows"]}

        self.assertIn(inside.pk, account_ids)
        self.assertNotIn(outside.pk, account_ids)

    def test_a_range_is_required(self):
        from django.core.exceptions import ValidationError

        company = self.make_company()

        with self.assertRaises(ValidationError):
            TrialBalanceQueryService.build(
                LedgerFilters(company_id=company.pk)
            )


class AccountLedgerTests(FinanceTestCase):
    def test_running_balance_accumulates_from_the_opening(self):
        company = self.make_company()
        self.make_fiscal_year(company)

        cash = self.make_account(
            company, name="Cash", account_type=AccountType.ASSET,
        )
        payable = self.make_account(
            company, name="Payable", account_type=AccountType.LIABILITY,
        )

        for amount, when in (
            ("500.00", date(2027, 1, 10)),
            ("200.00", date(2027, 3, 5)),
            ("300.00", date(2027, 3, 18)),
        ):
            journal = self.make_journal(
                company,
                posting_date=when,
                lines=self.balanced_lines(cash, payable, amount),
            )

            FinancePostingService.post(journal=journal)

        report = AccountLedgerQueryService.build(
            LedgerFilters(
                company_id=company.pk,
                account_id=cash.pk,
                date_from=date(2027, 3, 1),
                date_to=date(2027, 3, 31),
            )
        )

        self.assertEqual(report["beginning_balance"], Decimal("500.00"))
        self.assertEqual(report["total_debit"], Decimal("500.00"))
        self.assertEqual(report["ending_balance"], Decimal("1000.00"))

        balances = [row["running_balance"] for row in report["rows"]]

        # Saldo berjalannya menumpuk di atas saldo awal, bukan mulai
        # dari nol lagi.
        self.assertEqual(balances, [Decimal("700.00"), Decimal("1000.00")])

    def test_ledger_rows_carry_the_source_document(self):
        company = self.make_company()
        self.make_fiscal_year(company)

        expense, payable = self.make_pair(company)

        from apps.finance.services import JournalService

        journal = JournalService.create(data={
            "company": company,
            "posting_date": date(2027, 3, 5),
            "source_module": "payroll",
            "source_type": "payroll_run",
            "source_id": "77",
        })

        JournalService.replace_lines(
            journal=journal, lines=self.balanced_lines(expense, payable),
        )
        journal.refresh_from_db()

        FinancePostingService.post(journal=journal)

        report = AccountLedgerQueryService.build(
            LedgerFilters(
                company_id=company.pk,
                account_id=expense.pk,
                date_from=date(2027, 3, 1),
                date_to=date(2027, 3, 31),
            )
        )

        row = report["rows"][0]

        self.assertEqual(row["source_module"], "payroll")
        self.assertEqual(row["source_id"], "77")
        self.assertEqual(row["journal_number"], journal.journal_number)
