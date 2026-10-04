"""
PF-0F — `AccountingEventProcessor.record_required()`, kontrak generiknya.

Satu-satunya pemakainya hari ini Finalize payroll, tapi tidak satu baris
pun di sini menyebut payroll: yang diuji janji Finance kepada modul
sumber mana pun yang menjadikan jurnalnya **syarat** transaksinya sendiri.

1. Berhasil hanya kalau kejadiannya berakhir PROCESSED dengan jurnal.
2. Kembaran identik dikembalikan; kembaran berbeda ditolak.
3. Kegagalan apa pun **tidak meninggalkan baris** — bahkan tanpa transaksi
   milik pemanggil, karena `record_required()` membungkus dirinya sendiri.
4. `auto_post` kebijakan tetap yang menentukan posting.
"""

from datetime import date

from apps.finance.models import (
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
    AccountingEventConflict,
    AccountingEventNotProcessed,
    AccountingEventProcessor,
    AccountMappingService,
)

from .base import FinanceTestCase


EVENT_DATE = date(2027, 3, 31)


class RecordRequiredTests(FinanceTestCase):

    def stage(self, *, auto_post=False, with_policy=True, mapped=True):
        company = self.make_company()
        self.make_fiscal_year(company)
        expense, payable = self.make_pair(company)

        event_type = f"REQ_{self.next_code('T')}"

        if with_policy:
            policy = AccountingPolicy.objects.create(
                code=self.next_code("POL"),
                name="Required policy",
                company=company,
                event_type=event_type,
                journal_type="automatic",
                auto_post=auto_post,
            )

            rule = AccountingPolicyRule.objects.create(
                policy=policy,
                sequence=10,
                name="Items",
                conditions={"field": "kind", "op": "eq", "value": "ITEM"},
                iterate_over="rows",
            )

            AccountingPolicyLine.objects.create(
                rule=rule, sequence=1, side=PostingSide.DEBIT,
                mapping_key="REQ_EXPENSE", amount_source="amount",
            )
            AccountingPolicyLine.objects.create(
                rule=rule, sequence=2, side=PostingSide.CREDIT,
                account=payable, amount_source="amount",
            )

        if mapped:
            AccountMappingService.create(data={
                "code": self.next_code("MAP"),
                "name": "Required expense",
                "mapping_key": "REQ_EXPENSE",
                "company": company,
                "event_type": event_type,
                "selectors": {},
                "account": expense,
            })

        return company, event_type

    def call(self, company, event_type, *, key, payload=None):
        return AccountingEventProcessor.record_required(
            event_type=event_type,
            source_module="test",
            source_type="required",
            source_id=key,
            company=company,
            event_date=EVENT_DATE,
            idempotency_key=f"pf0f:req:{key}",
            payload=payload or {
                "rows": [{"kind": "ITEM", "amount": "500.00"}],
            },
        )

    def rows_for(self, key):
        return (
            AccountingEvent.objects.filter(
                idempotency_key=f"pf0f:req:{key}",
            ).count(),
            Journal.objects.filter(
                source_module="test", source_id=key,
            ).count(),
        )

    # ------------------------------------------------------------------
    # Berhasil
    # ------------------------------------------------------------------

    def test_processed_event_returns_with_its_journal(self):
        company, event_type = self.stage()
        key = self.next_code("K")

        event = self.call(company, event_type, key=key)

        self.assertEqual(event.status, AccountingEventStatus.PROCESSED)
        self.assertIsNotNone(event.generated_journal_id)
        self.assertEqual(self.rows_for(key), (1, 1))

    def test_policy_auto_post_false_leaves_draft(self):
        company, event_type = self.stage(auto_post=False)

        event = self.call(company, event_type, key=self.next_code("K"))

        self.assertEqual(event.generated_journal.status, JournalStatus.DRAFT)

    def test_policy_auto_post_true_posts(self):
        company, event_type = self.stage(auto_post=True)

        event = self.call(company, event_type, key=self.next_code("K"))

        self.assertEqual(event.generated_journal.status, JournalStatus.POSTED)

    # ------------------------------------------------------------------
    # Idempotensi
    # ------------------------------------------------------------------

    def test_identical_replay_returns_the_same_event(self):
        company, event_type = self.stage()
        key = self.next_code("K")

        first = self.call(company, event_type, key=key)
        second = self.call(company, event_type, key=key)

        self.assertEqual(first.pk, second.pk)
        self.assertEqual(first.generated_journal_id, second.generated_journal_id)
        self.assertEqual(self.rows_for(key), (1, 1))

    def test_key_order_does_not_count_as_a_difference(self):
        company, event_type = self.stage()
        key = self.next_code("K")

        self.call(company, event_type, key=key, payload={
            "rows": [{"kind": "ITEM", "amount": "500.00"}], "z": 1, "a": 2,
        })

        again = self.call(company, event_type, key=key, payload={
            "a": 2, "z": 1, "rows": [{"amount": "500.00", "kind": "ITEM"}],
        })

        self.assertEqual(again.status, AccountingEventStatus.PROCESSED)
        self.assertEqual(self.rows_for(key), (1, 1))

    def test_same_key_different_payload_is_a_conflict(self):
        company, event_type = self.stage()
        key = self.next_code("K")

        original = self.call(company, event_type, key=key)

        with self.assertRaises(AccountingEventConflict) as caught:
            self.call(company, event_type, key=key, payload={
                "rows": [{"kind": "ITEM", "amount": "999.00"}],
            })

        self.assertEqual(caught.exception.error_code, "accounting_event_conflict")

        original.refresh_from_db()

        self.assertEqual(
            original.payload, {"rows": [{"kind": "ITEM", "amount": "500.00"}]},
        )
        self.assertEqual(self.rows_for(key), (1, 1))

    def test_same_key_different_company_is_a_conflict(self):
        company, event_type = self.stage()
        other = self.make_company()
        key = self.next_code("K")

        self.call(company, event_type, key=key)

        with self.assertRaises(AccountingEventConflict):
            self.call(other, event_type, key=key)

        self.assertEqual(self.rows_for(key), (1, 1))

    # ------------------------------------------------------------------
    # Gagal = tidak ada baris
    # ------------------------------------------------------------------

    def test_missing_policy_leaves_no_row(self):
        company, event_type = self.stage(with_policy=False)
        key = self.next_code("K")

        with self.assertRaises(AccountingEventNotProcessed) as caught:
            self.call(company, event_type, key=key)

        self.assertEqual(caught.exception.error_code, "accounting_policy_missing")
        self.assertEqual(self.rows_for(key), (0, 0))

    def test_policy_without_matching_lines_leaves_no_row(self):
        company, event_type = self.stage()
        key = self.next_code("K")

        with self.assertRaises(AccountingEventNotProcessed) as caught:
            self.call(company, event_type, key=key, payload={
                "rows": [{"kind": "SOMETHING_ELSE", "amount": "500.00"}],
            })

        self.assertEqual(
            caught.exception.error_code, "accounting_no_journal_lines",
        )
        self.assertEqual(self.rows_for(key), (0, 0))

    def test_missing_mapping_leaves_no_row(self):
        """
        Pemetaan hilang → `process()` menandai FAILED, lalu
        `record_required()` melempar — dan transaksinya sendiri membatalkan
        baris FAILED itu. Tidak ada kejadian setengah jadi yang menunggu
        `retry()` untuk sumber yang menuntut jurnalnya sekarang juga.
        """
        company, event_type = self.stage(mapped=False)
        key = self.next_code("K")

        with self.assertRaises(AccountingEventNotProcessed) as caught:
            self.call(company, event_type, key=key)

        self.assertEqual(caught.exception.error_code, "accounting_journal_failed")
        self.assertIn("REQ_EXPENSE", str(caught.exception))
        self.assertEqual(self.rows_for(key), (0, 0))

    def test_existing_failed_event_is_processed_again_once_fixed(self):
        """
        Kejadian FAILED yang ditinggalkan `record()` biasa (dunia retry)
        dan kini dikirim ulang lewat `record_required()` dengan isi yang
        sama: diproses ulang, bukan dicatat kedua kalinya.
        """
        company, event_type = self.stage(mapped=False)
        key = self.next_code("K")

        failed = AccountingEventProcessor.record(
            event_type=event_type,
            source_module="test",
            source_type="required",
            source_id=key,
            company=company,
            event_date=EVENT_DATE,
            idempotency_key=f"pf0f:req:{key}",
            payload={"rows": [{"kind": "ITEM", "amount": "500.00"}]},
        )

        self.assertEqual(failed.status, AccountingEventStatus.FAILED)

        expense = self.make_account(company, name="Late expense")

        AccountMappingService.create(data={
            "code": self.next_code("MAP"),
            "name": "Late mapping",
            "mapping_key": "REQ_EXPENSE",
            "company": company,
            "event_type": event_type,
            "selectors": {},
            "account": expense,
        })

        event = self.call(company, event_type, key=key)

        self.assertEqual(event.pk, failed.pk)
        self.assertEqual(event.status, AccountingEventStatus.PROCESSED)
        self.assertEqual(self.rows_for(key), (1, 1))
