"""
Rebuildability dan regresi dari verifikasi E2E Finance Core.

Dua kelompok, dan keduanya lahir dari bukti yang sebelumnya hanya ada
di tenant `demo`:

* **Rebuildability.** `Account.path/level` dan kolom posting pada
  `JournalLine` adalah turunan. Klaim itu hanya berarti kalau
  merusaknya lalu membangunnya ulang menghasilkan nilai yang **persis
  sama**. Dibuktikan di sini, di schema test — tenant bersama tidak
  pernah dirusak sengaja lagi.
* **Regresi lima bug** yang ditemukan saat E2E, plus alur yang
  membuktikannya: submit → alur jurnal → approve → post, dan valas.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import StringIO

from django.contrib.auth import get_user_model
from django.core.management import call_command

from apps.accounts.models import Role
from apps.administration.models import Currency
from apps.finance.models import (
    Account,
    AccountingEventStatus,
    AccountType,
    Journal,
    JournalLine,
    JournalStatus,
)
from apps.finance.services import (
    AccountingEventProcessor,
    AccountService,
    FinancePostingService,
    JournalService,
)
from apps.finance.tests.base import AS_OF, FinanceTestCase


def _derived_lines(journal):
    return list(
        JournalLine.objects
        .filter(journal=journal)
        .order_by("pk")
        .values_list("pk", "is_posted", "posting_date", "accounting_period_id")
    )


class AccountTreeRebuildTests(FinanceTestCase):
    def test_corrupted_paths_are_restored_exactly(self):
        company = self.make_company()

        root = self.make_account(
            company, account_type=AccountType.EXPENSE, posting_allowed=False,
        )
        middle = self.make_account(
            company, account_type=AccountType.EXPENSE,
            parent=root, posting_allowed=False,
        )
        leaf = self.make_account(
            company, account_type=AccountType.EXPENSE, parent=middle,
        )

        ids = [root.pk, middle.pk, leaf.pk]

        before = list(
            Account.objects.filter(pk__in=ids)
            .order_by("pk").values_list("pk", "path", "level")
        )

        self.assertEqual(
            before,
            [
                (root.pk, f"/{root.pk}/", 0),
                (middle.pk, f"/{root.pk}/{middle.pk}/", 1),
                (leaf.pk, f"/{root.pk}/{middle.pk}/{leaf.pk}/", 2),
            ],
        )

        # Rusak sengaja — hanya di schema test.
        Account.objects.filter(pk__in=ids).update(path="", level=9)

        out = StringIO()
        call_command("rebuild_finance_account_tree", stdout=out)

        after = list(
            Account.objects.filter(pk__in=ids)
            .order_by("pk").values_list("pk", "path", "level")
        )

        self.assertEqual(after, before)

        # Rebuild kedua tidak menemukan apa pun yang perlu diubah untuk
        # cabang ini — turunannya stabil.
        self.assertEqual(AccountService.rebuild_tree(company_id=company.pk), 0)


class LedgerDenormRebuildTests(FinanceTestCase):
    def test_corrupted_posting_columns_are_restored_exactly(self):
        company = self.make_company()
        self.make_fiscal_year(company)
        expense, payable = self.make_pair(company)

        posted = self.make_journal(
            company, lines=self.balanced_lines(expense, payable, "750.00"),
        )
        FinancePostingService.post(journal=posted)

        draft = self.make_journal(
            company, lines=self.balanced_lines(expense, payable, "10.00"),
        )

        expected_posted = _derived_lines(posted)
        expected_draft = _derived_lines(draft)

        period_id = self.period_for(company, AS_OF).pk

        self.assertTrue(
            all(
                row[1:] == (True, AS_OF, period_id)
                for row in expected_posted
            )
        )
        self.assertTrue(
            all(row[1:] == (False, None, None) for row in expected_draft)
        )

        facts_before = list(
            JournalLine.objects.filter(journal__in=[posted, draft])
            .order_by("pk")
            .values_list("pk", "account_id", "debit", "credit",
                         "base_debit", "base_credit")
        )

        # Dua arah kerusakan: baris terposting kehilangan tandanya, dan
        # baris draf diberi tanda basi.
        JournalLine.objects.filter(journal=posted).update(
            is_posted=False, posting_date=None, accounting_period=None,
        )
        JournalLine.objects.filter(journal=draft).update(
            is_posted=True, posting_date=date(2000, 1, 1),
        )

        call_command("rebuild_finance_ledger_denorm", stdout=StringIO())

        self.assertEqual(_derived_lines(posted), expected_posted)
        self.assertEqual(_derived_lines(draft), expected_draft)

        # Angka tidak disentuh sama sekali.
        facts_after = list(
            JournalLine.objects.filter(journal__in=[posted, draft])
            .order_by("pk")
            .values_list("pk", "account_id", "debit", "credit",
                         "base_debit", "base_credit")
        )
        self.assertEqual(facts_after, facts_before)

    def test_dry_run_writes_nothing(self):
        company = self.make_company()
        self.make_fiscal_year(company)
        expense, payable = self.make_pair(company)

        journal = self.make_journal(
            company, lines=self.balanced_lines(expense, payable),
        )
        FinancePostingService.post(journal=journal)

        JournalLine.objects.filter(journal=journal).update(is_posted=False)
        corrupted = _derived_lines(journal)

        call_command(
            "rebuild_finance_ledger_denorm", "--dry-run", stdout=StringIO(),
        )

        self.assertEqual(_derived_lines(journal), corrupted)


class WorkflowJournalTests(FinanceTestCase):
    """
    Bug #2 (company id vs instance di `scope`) dan bug #3
    (`approved_by` mencatat pengaju), lewat alur yang sama dengan
    `FIN-JOURNAL-STD`: satu meja Role FINANCE-MANAGER bercakupan
    company.
    """

    def make_user(self, *, roles=(), company=None):
        from apps.hr.models import Employee, OrganizationAssignment

        User = get_user_model()
        code = self.next_code("wf")

        user = User.objects.create_user(
            username=f"fin.{code}".lower(),
            email=f"{code}@example.test".lower(),
            password="Test-Only#Pw1",
            first_name="Finance",
            last_name=code,
        )

        # `grant_role`, bukan `user.roles.set()`: yang kedua memberi
        # role tanpa kewenangan data, dan penugasan tanpa kewenangan
        # tidak melihat — dan tidak boleh memposting — apa pun. Bentuk
        # kewenangannya sama dengan seed `FINANCE-MANAGER`: sebatas
        # company penempatannya.
        from apps.accounts.models import AuthorityMode
        from apps.accounts.services.role_assignment import grant_role

        for role in Role.objects.filter(code__in=roles):
            grant_role(
                user, role, mode=AuthorityMode.PLACEMENT, level="company",
            )

        if company is not None:
            employee = Employee.objects.create(
                employee_number=f"FIN-{code}",
                first_name="Finance",
                last_name=code,
                user=user,
            )
            OrganizationAssignment.objects.create(
                employee=employee,
                company=company,
                organization_effective_date=date(2020, 1, 1),
            )

        return user

    def make_definition(self, company):
        from apps.workflow.models import (
            ApproverScope,
            ApproverType,
            WorkflowDefinition,
            WorkflowStatus,
            WorkflowStep,
        )

        role, _ = Role.objects.get_or_create(
            code="FINANCE-MANAGER",
            is_deleted=False,
            defaults={"name": "Finance Manager"},
        )

        definition = WorkflowDefinition.objects.create(
            code=self.next_code("FIN-JOURNAL-"),
            name="Journal — Standar",
            module="finance",
            document_type="journal",
            company=company,
            status=WorkflowStatus.ACTIVE,
        )

        WorkflowStep.objects.create(
            definition=definition,
            sequence=1,
            name="Approved By (Finance Manager)",
            approver_type=ApproverType.ROLE,
            approver_role=role,
            approver_scope=ApproverScope.COMPANY,
        )

        return definition

    def test_submit_approve_post_records_the_real_approver(self):
        from apps.workflow.models import InstanceStatus
        from apps.workflow.registry import completion_handler
        from apps.workflow.services.workflow_service import WorkflowService

        company = self.make_company()
        self.make_fiscal_year(company)
        expense, payable = self.make_pair(company)
        self.make_definition(company)

        # FIN-B1/B2: pengaju memegang `change_journal`, approver (meja
        # FINANCE-MANAGER) juga `post_journal` — seperti seed-nya.
        submitter = self.grant_finance(
            self.make_user(), "finance.change_journal",
        )
        approver = self.grant_finance(
            self.make_user(roles=["FINANCE-MANAGER"], company=company),
            "finance.post_journal",
        )

        journal = self.make_journal(
            company,
            lines=self.balanced_lines(expense, payable),
            user=submitter,
        )

        # Bug #2: mengirim id ke `scope` gagal `Cannot assign "1"`.
        instance = JournalService.submit(journal=journal, user=submitter)

        self.assertIsNotNone(instance)
        self.assertEqual(instance.company_id, company.pk)
        self.assertEqual(instance.status, InstanceStatus.PENDING)

        journal.refresh_from_db()
        self.assertEqual(journal.status, JournalStatus.SUBMITTED)
        self.assertEqual(journal.submitted_by, submitter)

        # Jalur kotak masuk generik: callback dicari lewat registry,
        # persis seperti `apps/workflow/api/approval/views.py`.
        handler = completion_handler(module="finance", document_type="journal")
        self.assertIsNotNone(handler, "workflow_handlers belum terdaftar")

        WorkflowService.approve(
            instance=instance, user=approver, on_complete=handler,
        )

        journal.refresh_from_db()
        self.assertEqual(journal.status, JournalStatus.APPROVED)

        # Bug #3: dulu `approved_by == submitter`.
        self.assertEqual(journal.approved_by, approver)
        self.assertNotEqual(journal.approved_by, submitter)

        result = FinancePostingService.post(journal=journal, user=approver)

        self.assertFalse(result.already_posted)
        self.assertEqual(result.journal.status, JournalStatus.POSTED)
        self.assertEqual(result.journal.posted_by, approver)

    def test_submit_without_matching_definition_approves_directly(self):
        company = self.make_company()
        self.make_fiscal_year(company)
        expense, payable = self.make_pair(company)

        journal = self.make_journal(
            company, lines=self.balanced_lines(expense, payable),
        )

        self.assertIsNone(JournalService.submit(journal=journal))

        journal.refresh_from_db()
        self.assertEqual(journal.status, JournalStatus.APPROVED)


class MultiCurrencyTests(FinanceTestCase):
    """Bug #4 dan konversi valas: 100 USD × 16.000 = 1.600.000 IDR."""

    def usd(self):
        currency, _ = Currency.objects.get_or_create(
            code="USD",
            is_deleted=False,
            defaults={"name": "US Dollar", "symbol": "$", "decimal_places": 2},
        )
        return currency

    def make_usd_journal(self, company, expense, payable):
        journal = JournalService.create(
            data={
                "company": company,
                "posting_date": AS_OF,
                "currency": self.usd(),
                "exchange_rate": Decimal("16000"),
                "description": "USD journal",
            },
        )

        JournalService.replace_lines(
            journal=journal,
            lines=self.balanced_lines(expense, payable, "100.00"),
        )
        journal.refresh_from_db()

        return journal

    def test_base_amount_is_converted_and_transaction_amount_kept(self):
        company = self.make_company()
        self.make_fiscal_year(company)
        expense, payable = self.make_pair(company)

        journal = self.make_usd_journal(company, expense, payable)

        self.assertEqual(journal.currency.code, "USD")
        self.assertEqual(journal.base_currency, self.currency)
        self.assertEqual(journal.total_debit, Decimal("100.00"))
        self.assertEqual(journal.base_total_debit, Decimal("1600000.00"))

        FinancePostingService.post(journal=journal)

        for line in journal.lines.all():
            self.assertEqual(line.transaction_currency.code, "USD")
            self.assertEqual(line.exchange_rate, Decimal("16000"))
            self.assertEqual(
                (line.debit, line.credit, line.base_debit, line.base_credit)
                in {
                    (Decimal("100.00"), Decimal("0.00"),
                     Decimal("1600000.00"), Decimal("0.00")),
                    (Decimal("0.00"), Decimal("100.00"),
                     Decimal("0.00"), Decimal("1600000.00")),
                },
                True,
            )

    def test_foreign_currency_draft_can_be_edited_without_resending_rate(self):
        company = self.make_company()
        self.make_fiscal_year(company)
        expense, payable = self.make_pair(company)

        journal = self.make_usd_journal(company, expense, payable)

        # Bug #4: PATCH yang cuma mengubah keterangan dulu ditolak
        # "harus menyebutkan kursnya".
        JournalService.update(
            instance=journal, data={"description": "Edited"},
        )

        journal.refresh_from_db()
        self.assertEqual(journal.description, "Edited")
        self.assertEqual(journal.currency.code, "USD")
        self.assertEqual(journal.exchange_rate, Decimal("16000"))
        self.assertEqual(journal.base_total_debit, Decimal("1600000.00"))


class PayrollEventTests(FinanceTestCase):
    """
    PAYROLL_POSTED → kejadian → kebijakan/pemetaan → jurnal, memakai
    kebijakan yang diseed — dan bug #5: kebijakan yang memetakan dimensi
    `company` tidak boleh bertabrakan dengan company kepala dokumen.

    **Disesuaikan PF-0E.** Payload-nya dulu memakai bentuk demo
    (`category`/`component_type`/`name`) dan jurnalnya terbit `POSTED`.
    Keduanya berubah dengan sengaja: kebijakan gaji sekarang membaca
    kontrak `payroll.posting/v1` dan `auto_post=False`, jadi yang
    lahir jurnal **draft**. Yang diuji kelas ini tidak berubah — satu
    kejadian tetap satu jurnal, dan dimensi `company` tetap tidak
    mengalahkan kepala dokumen.
    """

    def payload(self, company, *, company_dimension=None):
        component = {
            "branch_id": None,
            "location_id": None,
            "division_id": None,
            "department_id": None,
            "section_id": None,
            "cost_center_id": None,
            "detail": "",
            "program": "",
            "reference": "PAY-2027-00001",
        }

        if company_dimension is not None:
            component["company_id"] = company_dimension

        return {
            "schema": "payroll.posting/v1",
            "components": [
                {**component, "semantic": "BASIC_SALARY",
                 "amount": "5000000.00"},
                {**component, "semantic": "EMPLOYEE_INCOME_TAX",
                 "amount": "250000.00"},
                {**component, "semantic": "NET_PAY",
                 "amount": "4750000.00"},
            ],
        }

    def setup_company(self):
        from apps.finance.seeds import seed_chart_of_accounts, seed_payroll_policy

        company = self.make_company()
        self.make_fiscal_year(company)
        seed_chart_of_accounts(company=company)
        seed_payroll_policy(company=company)

        return company

    def test_payroll_event_creates_one_journal_through_the_mapping(self):
        company = self.setup_company()
        key = f"payroll:payroll_run:{company.pk}:posted"

        event = AccountingEventProcessor.record(
            event_type="PAYROLL_POSTED",
            source_module="payroll",
            source_type="payroll_run",
            source_id=str(company.pk),
            company=company,
            event_date=AS_OF,
            payload=self.payload(company),
            idempotency_key=key,
        )

        self.assertEqual(event.status, AccountingEventStatus.PROCESSED, event.error_message)

        journal = event.generated_journal
        # PF-0E: draft, bukan posted. Yang memposting alur Finance.
        self.assertEqual(journal.status, JournalStatus.DRAFT)
        self.assertEqual(journal.base_total_debit, Decimal("5000000.00"))
        self.assertEqual(journal.base_total_credit, Decimal("5000000.00"))

        by_account = {
            line.account.code: (line.debit, line.credit)
            for line in journal.lines.select_related("account")
        }
        self.assertEqual(by_account["6100"], (Decimal("5000000.00"), Decimal("0.00")))
        self.assertEqual(by_account["2140"], (Decimal("0.00"), Decimal("250000.00")))
        self.assertEqual(by_account["2130"], (Decimal("0.00"), Decimal("4750000.00")))

        again = AccountingEventProcessor.record(
            event_type="PAYROLL_POSTED",
            source_module="payroll",
            source_type="payroll_run",
            source_id=str(company.pk),
            company=company,
            event_date=AS_OF,
            payload=self.payload(company),
            idempotency_key=key,
        )

        self.assertEqual(again.pk, event.pk)
        self.assertEqual(
            Journal.objects.filter(
                source_module="payroll", source_id=str(company.pk),
                company=company,
            ).count(),
            1,
        )

    def test_company_dimension_does_not_collide_with_the_header(self):
        from apps.finance.models import AccountingPolicyLine

        company = self.setup_company()
        other = self.make_company()

        AccountingPolicyLine.objects.filter(
            rule__policy__company=company,
        ).update(dimension_sources={"company": "company_id"})

        event = AccountingEventProcessor.record(
            event_type="PAYROLL_POSTED",
            source_module="payroll",
            source_type="payroll_run",
            source_id=f"dim-{company.pk}",
            company=company,
            event_date=AS_OF,
            payload=self.payload(company, company_dimension=other.pk),
            idempotency_key=f"payroll:dim:{company.pk}",
        )

        self.assertEqual(event.status, AccountingEventStatus.PROCESSED, event.error_message)

        companies = set(
            event.generated_journal.lines.values_list("company_id", flat=True)
        )
        self.assertEqual(companies, {company.pk})

    def test_payroll_module_names_no_finance_accounts(self):
        """Payroll tidak boleh menyebut satu pun akun atau model Finance."""
        from pathlib import Path

        import apps.payroll as payroll

        root = Path(payroll.__file__).parent
        offenders = []

        for path in root.rglob("*.py"):
            if "tests" in path.parts or "migrations" in path.parts:
                continue

            text = path.read_text(encoding="utf-8")

            for needle in ("apps.finance.models", "AccountMapping", "finance.Account"):
                if needle in text:
                    offenders.append(f"{path.relative_to(root)}: {needle}")

        self.assertEqual(offenders, [])
