"""
Lapisan integrasi: kejadian, kebijakan, dan pemetaan akun.

Yang diuji di sini adalah janji yang paling penting dari seluruh modul
Finance: **satu kejadian tidak pernah menerbitkan dua jurnal**, dan
konfigurasi yang tidak lengkap gagal dengan aman alih-alih menebak akun.
"""

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError

from apps.finance.models import (
    AccountType,
    AccountingEvent,
    AccountingEventStatus,
    AccountingPolicy,
    AccountingPolicyLine,
    AccountingPolicyRule,
    Journal,
    JournalStatus,
    PostingSide,
)
from apps.finance.services import (
    AccountMappingService,
    AccountingEventProcessor,
    MappingAmbiguous,
    MappingContext,
    MappingNotFound,
)

from .base import FinanceTestCase


EVENT_DATE = date(2027, 3, 31)


class AccountingEventTestCase(FinanceTestCase):
    """Panggung bersama: satu kebijakan gaji yang sederhana tapi utuh."""

    def build_stage(self, company):
        expense = self.make_account(
            company, name="Salary Expense", account_type=AccountType.EXPENSE,
        )
        payable = self.make_account(
            company, name="Payroll Payable", account_type=AccountType.LIABILITY,
        )

        AccountMappingService.create(data={
            "code": self.next_code("MAP"),
            "name": "Salary expense",
            "mapping_key": "SALARY_EXPENSE",
            "company": company,
            "event_type": "PAYROLL_POSTED",
            "selectors": {"category": "EARNING"},
            "account": expense,
        })

        AccountMappingService.create(data={
            "code": self.next_code("MAP"),
            "name": "Payroll payable",
            "mapping_key": "PAYROLL_PAYABLE",
            "company": company,
            "event_type": "PAYROLL_POSTED",
            "selectors": {},
            "account": payable,
        })

        policy = AccountingPolicy.objects.create(
            code=self.next_code("POL"),
            name="Payroll posting",
            company=company,
            event_type="PAYROLL_POSTED",
            journal_type="automatic",
        )

        earning = AccountingPolicyRule.objects.create(
            policy=policy,
            sequence=10,
            name="Earnings",
            conditions={"field": "category", "op": "eq", "value": "EARNING"},
            iterate_over="components",
        )

        AccountingPolicyLine.objects.create(
            rule=earning,
            sequence=1,
            side=PostingSide.DEBIT,
            mapping_key="SALARY_EXPENSE",
            amount_source="amount",
        )

        net = AccountingPolicyRule.objects.create(
            policy=policy,
            sequence=20,
            name="Net pay",
            conditions={"field": "category", "op": "eq", "value": "NET_PAY"},
            iterate_over="components",
        )

        AccountingPolicyLine.objects.create(
            rule=net,
            sequence=1,
            side=PostingSide.CREDIT,
            mapping_key="PAYROLL_PAYABLE",
            amount_source="amount",
        )

        return expense, payable, policy

    def payload(self, amount="5000000.00"):
        return {
            "run": 99,
            "components": [
                {
                    "name": "Basic Salary",
                    "category": "EARNING",
                    "amount": amount,
                },
                {
                    "name": "Net Pay",
                    "category": "NET_PAY",
                    "amount": amount,
                },
            ],
        }

    def record(self, company, *, key=None, payload=None, **extra):
        return AccountingEventProcessor.record(
            event_type="PAYROLL_POSTED",
            source_module="payroll",
            source_type="payroll_run",
            source_id="99",
            company=company,
            event_date=EVENT_DATE,
            payload=payload if payload is not None else self.payload(),
            idempotency_key=key or self.next_code("payroll:run:"),
            **extra,
        )


class EventToJournalTests(AccountingEventTestCase):
    def test_event_produces_the_expected_journal(self):
        company = self.make_company()
        self.make_fiscal_year(company)

        expense, payable, _ = self.build_stage(company)

        event = self.record(company)

        self.assertEqual(event.status, AccountingEventStatus.PROCESSED)
        self.assertIsNotNone(event.generated_journal_id)

        journal = event.generated_journal

        self.assertEqual(journal.status, JournalStatus.POSTED)
        self.assertEqual(journal.total_debit, Decimal("5000000.00"))
        self.assertEqual(journal.total_credit, Decimal("5000000.00"))

        by_account = {line.account_id: line for line in journal.lines.all()}

        self.assertEqual(by_account[expense.pk].debit, Decimal("5000000.00"))
        self.assertEqual(by_account[payable.pk].credit, Decimal("5000000.00"))

        # Jejak dua arah: dari jurnal ke dokumen sumbernya.
        self.assertEqual(journal.source_module, "payroll")
        self.assertEqual(journal.source_id, "99")

    def test_duplicate_event_does_not_produce_a_second_journal(self):
        """
        §29: "duplicate event does not duplicate journal".

        Inilah janji paling penting dari seluruh modul ini.
        """
        company = self.make_company()
        self.make_fiscal_year(company)

        self.build_stage(company)

        key = "payroll:payroll_run:99:posted"

        first = self.record(company, key=key)
        second = self.record(company, key=key)
        third = self.record(company, key=key)

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(first.pk, third.pk)

        self.assertEqual(
            AccountingEvent.objects.filter(idempotency_key=key).count(), 1,
        )

        self.assertEqual(
            Journal.objects.filter(
                source_module="payroll", source_id="99", is_deleted=False,
            ).count(),
            1,
        )

    def test_event_without_an_idempotency_key_is_rejected(self):
        company = self.make_company()

        with self.assertRaises(ValidationError) as ctx:
            AccountingEventProcessor.record(
                event_type="PAYROLL_POSTED",
                source_module="payroll",
                company=company,
                event_date=EVENT_DATE,
                idempotency_key="",
            )

        self.assertIn("idempotency_key", ctx.exception.message_dict)

    def test_missing_policy_is_skipped_not_failed(self):
        """
        Tenant yang memang tidak membukukan kejadian ini tidak punya
        kebijakan untuknya, dan itu keadaan yang sah.

        Membedakannya dari FAILED membuat layar pemantauan hanya berisi
        baris yang benar-benar menuntut perhatian.
        """
        company = self.make_company()
        self.make_fiscal_year(company)

        event = self.record(company)

        self.assertEqual(event.status, AccountingEventStatus.SKIPPED)
        self.assertIsNone(event.generated_journal_id)

    def test_missing_mapping_fails_safely(self):
        """
        Jurnalnya sengaja **tidak** diterbitkan: menebak akun lebih
        berbahaya daripada tidak membukukan sama sekali.
        """
        company = self.make_company()
        self.make_fiscal_year(company)

        expense, payable, policy = self.build_stage(company)

        # Mencabut salah satu pemetaan sesudah kebijakannya berdiri.
        from apps.finance.models import AccountMapping

        AccountMapping.objects.filter(
            mapping_key="SALARY_EXPENSE", company=company,
        ).update(is_deleted=True)

        event = self.record(company)

        self.assertEqual(event.status, AccountingEventStatus.FAILED)
        self.assertIsNone(event.generated_journal_id)
        self.assertIn("SALARY_EXPENSE", event.error_message)

        # Tidak ada jurnal setengah jadi yang tertinggal.
        self.assertFalse(
            Journal.objects.filter(
                source_module="payroll", source_id="99", is_deleted=False,
            ).exists()
        )

    def test_failed_event_can_be_retried_after_the_config_is_fixed(self):
        company = self.make_company()
        self.make_fiscal_year(company)

        expense, payable, _ = self.build_stage(company)

        from apps.finance.models import AccountMapping

        AccountMapping.objects.filter(
            mapping_key="SALARY_EXPENSE", company=company,
        ).update(is_deleted=True)

        event = self.record(company, key="payroll:run:retry")

        self.assertEqual(event.status, AccountingEventStatus.FAILED)

        # Konfigurasinya dibetulkan…
        AccountMapping.objects.filter(
            mapping_key="SALARY_EXPENSE", company=company,
        ).update(is_deleted=False)

        # …lalu diproses ulang **di baris yang sama**, bukan lewat
        # kejadian kedua.
        event = AccountingEventProcessor.retry(event=event)

        self.assertEqual(event.status, AccountingEventStatus.PROCESSED)
        self.assertIsNotNone(event.generated_journal_id)

    def test_processed_event_cannot_be_retried(self):
        company = self.make_company()
        self.make_fiscal_year(company)

        self.build_stage(company)

        event = self.record(company)

        self.assertEqual(event.status, AccountingEventStatus.PROCESSED)

        with self.assertRaises(ValidationError):
            AccountingEventProcessor.retry(event=event)

    def test_closed_period_fails_the_event_without_a_partial_journal(self):
        company = self.make_company()
        self.make_fiscal_year(company)

        self.build_stage(company)

        self.close_period(self.period_for(company, EVENT_DATE))

        event = self.record(company)

        self.assertEqual(event.status, AccountingEventStatus.FAILED)
        self.assertFalse(
            Journal.objects.filter(
                source_module="payroll", is_deleted=False,
            ).exists()
        )

    def test_amount_key_missing_from_payload_fails_loudly(self):
        """
        Nilai yang tidak ada **bukan nol**.

        Membukukannya sebagai nol menerbitkan jurnal yang sisi lawannya
        tetap terbit dengan angkanya sendiri — jurnal yang tidak
        seimbang, atau lebih buruk: seimbang dengan angka yang lebih
        kecil dari seharusnya.
        """
        company = self.make_company()
        self.make_fiscal_year(company)

        self.build_stage(company)

        event = self.record(company, payload={
            "components": [
                {"name": "Basic", "category": "EARNING"},
            ],
        })

        self.assertEqual(event.status, AccountingEventStatus.FAILED)
        self.assertIn("amount", event.error_message)

    def test_negative_component_flips_the_side(self):
        """
        Modul sumber lazim mengirim koreksi sebagai angka negatif, dan
        baris jurnal bernilai negatif ditolak constraint database.
        """
        company = self.make_company()
        self.make_fiscal_year(company)

        expense, payable, _ = self.build_stage(company)

        event = self.record(company, payload={
            "components": [
                {"name": "Correction", "category": "EARNING", "amount": "-100.00"},
                {"name": "Net Pay", "category": "NET_PAY", "amount": "-100.00"},
            ],
        })

        self.assertEqual(event.status, AccountingEventStatus.PROCESSED)

        by_account = {
            line.account_id: line
            for line in event.generated_journal.lines.all()
        }

        self.assertEqual(by_account[expense.pk].credit, Decimal("100.00"))
        self.assertEqual(by_account[payable.pk].debit, Decimal("100.00"))


class AccountMappingResolutionTests(FinanceTestCase):
    def test_more_specific_mapping_wins(self):
        company = self.make_company()

        general = self.make_account(company, name="General expense")
        specific = self.make_account(company, name="Site expense")

        from apps.administration.models import Location

        site = Location.objects.create(
            company=company, code=self.next_code("LOC"), name="Site A",
        )

        AccountMappingService.create(data={
            "code": self.next_code("MAP"),
            "name": "General",
            "mapping_key": "EXPENSE",
            "company": company,
            "account": general,
        })

        AccountMappingService.create(data={
            "code": self.next_code("MAP"),
            "name": "Site specific",
            "mapping_key": "EXPENSE",
            "company": company,
            "location": site,
            "account": specific,
        })

        resolved = AccountMappingService.resolve(
            mapping_key="EXPENSE",
            context=MappingContext(company_id=company.pk, location_id=site.pk),
        )

        self.assertEqual(resolved.pk, specific.pk)

        # Tanpa site, yang umum yang menang.
        fallback = AccountMappingService.resolve(
            mapping_key="EXPENSE",
            context=MappingContext(company_id=company.pk),
        )

        self.assertEqual(fallback.pk, general.pk)

    def test_company_specific_wins_over_global(self):
        company = self.make_company()

        global_account = self.make_account(company, name="Global")
        company_account = self.make_account(company, name="Company")

        AccountMappingService.create(data={
            "code": self.next_code("MAP"),
            "name": "Global mapping",
            "mapping_key": "EXPENSE",
            "company": None,
            "account": global_account,
        })

        AccountMappingService.create(data={
            "code": self.next_code("MAP"),
            "name": "Company mapping",
            "mapping_key": "EXPENSE",
            "company": company,
            "account": company_account,
        })

        resolved = AccountMappingService.resolve(
            mapping_key="EXPENSE",
            context=MappingContext(company_id=company.pk),
        )

        self.assertEqual(resolved.pk, company_account.pk)

    def test_missing_mapping_raises_a_named_error(self):
        company = self.make_company()

        with self.assertRaises(MappingNotFound):
            AccountMappingService.resolve(
                mapping_key="NOTHING",
                context=MappingContext(company_id=company.pk),
            )

    def test_ambiguous_mapping_fails_safely(self):
        """
        §29: "ambiguous mapping fails safely".

        Memilih salah satu lewat urutan `id` berarti uang mendarat di
        akun yang ditentukan kebetulan — keputusan yang tidak pernah
        diambil siapa pun dan tidak tercatat di mana pun.
        """
        company = self.make_company()

        first = self.make_account(company, name="First")
        second = self.make_account(company, name="Second")

        # Sama kunci, sama company, `selectors` yang berbeda urutannya
        # saja — constraint database tidak bisa menilainya sama.
        AccountMappingService.create(data={
            "code": self.next_code("MAP"),
            "name": "A",
            "mapping_key": "EXPENSE",
            "company": company,
            "selectors": {"a": "1", "b": "2"},
            "account": first,
        })

        AccountMappingService.create(data={
            "code": self.next_code("MAP"),
            "name": "B",
            "mapping_key": "EXPENSE",
            "company": company,
            "selectors": {"b": "2", "a": "1"},
            "account": second,
        })

        with self.assertRaises(MappingAmbiguous) as ctx:
            AccountMappingService.resolve(
                mapping_key="EXPENSE",
                context=MappingContext(
                    company_id=company.pk,
                    selectors={"a": "1", "b": "2"},
                ),
            )

        message = " ".join(ctx.exception.message_dict["account_mapping"])

        # Pesannya menyebut baris mana yang bertabrakan — "ambigu" tanpa
        # kode memaksa orang mencari sendiri di daftar ratusan baris.
        self.assertIn("ambigu", message.lower())

    def test_conflicts_are_detected_before_a_journal_fails(self):
        company = self.make_company()

        first = self.make_account(company, name="First")
        second = self.make_account(company, name="Second")

        for name, account, selectors in (
            ("A", first, {"a": "1"}),
            ("B", second, {"A": "1"}),
        ):
            AccountMappingService.create(data={
                "code": self.next_code("MAP"),
                "name": name,
                "mapping_key": "EXPENSE",
                "company": company,
                "selectors": selectors,
                "account": account,
            })

        conflicts = AccountMappingService.detect_conflicts(
            company_id=company.pk,
        )

        actionable = [row for row in conflicts if not row["same_account"]]

        self.assertEqual(len(actionable), 1)
        self.assertEqual(actionable[0]["mapping_key"], "EXPENSE")

    def test_selector_key_absent_from_context_does_not_match(self):
        """
        Baris yang menyebut `component_type` dimaksudkan hanya untuk
        kejadian yang punya komponen.
        """
        company = self.make_company()

        account = self.make_account(company)

        AccountMappingService.create(data={
            "code": self.next_code("MAP"),
            "name": "Needs a component",
            "mapping_key": "EXPENSE",
            "company": company,
            "selectors": {"component_type": "BASIC"},
            "account": account,
        })

        with self.assertRaises(MappingNotFound):
            AccountMappingService.resolve(
                mapping_key="EXPENSE",
                context=MappingContext(company_id=company.pk, selectors={}),
            )
