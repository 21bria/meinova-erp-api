"""
PF-0G — supersesi proyeksi yang belum diposting, dan penjaga pembukuan
pengganti.

Dua operasi Finance yang lahir di PF-0G, diuji tanpa satu pun model
payroll (Finance tidak boleh mengenal payroll):

1. `supersede_unposted_projection(old, new)` — kejadian lama jadi
   SUPERSEDED, jurnalnya dicabut keberlakuannya (CANCELLED), **isinya
   tidak disentuh**, dan buku besar tidak bergerak sama sekali.
2. Penjaga `_assert_predecessor_settled` — jurnal pengganti tidak bisa
   diposting selama ayat yang digantikannya masih hidup di buku besar.

Yang sudah diposting tidak pernah lewat jalur supersesi: sejarah
dikoreksi lewat pembalikan Finance.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError

from apps.finance.models import (
    AccountingEvent,
    AccountingEventStatus,
    AccountingPolicy,
    AccountingPolicyLine,
    AccountingPolicyRule,
    Journal,
    JournalLine,
    JournalStatus,
    PostingSide,
)
from apps.finance.services import (
    POST_JOURNAL_PERMISSION,
    REVERSE_JOURNAL_PERMISSION,
    AccountingEventConflict,
    AccountingEventProcessor,
    AutomaticJournalLocked,
    FinancePostingService,
    FinanceReversalService,
    JournalService,
)

from .base import AS_OF
from .test_automatic_journal import AutomaticJournalTestCase


class SupersessionTestCase(AutomaticJournalTestCase):

    def policy_for(self, company, *, auto_post=False):
        expense, payable = self.make_pair(company)

        event_type = f"PF0G_{self.next_code('T')}"

        policy = AccountingPolicy.objects.create(
            code=self.next_code("POL"), name="PF-0G policy", company=company,
            event_type=event_type, journal_type="automatic",
            auto_post=auto_post,
        )
        rule = AccountingPolicyRule.objects.create(
            policy=policy, sequence=10, name="Both sides", conditions={},
        )
        AccountingPolicyLine.objects.create(
            rule=rule, sequence=1, side=PostingSide.DEBIT,
            account=expense, amount_source="amount",
        )
        AccountingPolicyLine.objects.create(
            rule=rule, sequence=2, side=PostingSide.CREDIT,
            account=payable, amount_source="amount",
        )

        return event_type

    def event_for(
        self, company, event_type, *, amount="1000.00", replaces=None,
        process=True,
    ):
        key = self.next_code("pf0g")

        if not process:
            return AccountingEventProcessor.record(
                event_type=event_type, source_module="test",
                source_type="pf0g", source_id=key, source_reference=f"R-{key}",
                company=company, event_date=AS_OF,
                payload={"amount": amount},
                idempotency_key=f"pf0g:{key}", process=False,
            )

        return AccountingEventProcessor.record_required(
            event_type=event_type, source_module="test", source_type="pf0g",
            source_id=key, source_reference=f"R-{key}", company=company,
            event_date=AS_OF, payload={"amount": amount},
            idempotency_key=f"pf0g:{key}",
            replaces_key=(replaces.idempotency_key if replaces else ""),
        )

    def pair(self, *, auto_post=False):
        """Satu company, kejadian lama + kejadian pengganti."""
        company = self.make_company()
        self.make_fiscal_year(company)

        event_type = self.policy_for(company, auto_post=auto_post)

        old = self.event_for(company, event_type)
        new = self.event_for(company, event_type, amount="1200.00", replaces=old)

        return company, old, new


class SupersedeUnpostedProjectionTests(SupersessionTestCase):

    def test_supersession_retires_the_old_projection_only(self):
        company, old, new = self.pair()

        journal = old.generated_journal
        before = self.content(journal)

        AccountingEventProcessor.supersede_unposted_projection(
            old_event=old, new_event=new,
        )

        old.refresh_from_db()
        journal.refresh_from_db()

        # Kejadian: peran berubah, isinya tidak.
        self.assertEqual(old.status, AccountingEventStatus.SUPERSEDED)
        self.assertEqual(old.superseded_by_id, new.pk)
        self.assertEqual(old.payload, {"amount": "1000.00"})
        self.assertEqual(old.generated_journal_id, journal.pk)

        # Jurnal: status + satu kunci provenance, tidak lebih.
        self.assertEqual(journal.status, JournalStatus.CANCELLED)
        self.assertEqual(journal.metadata["superseded_by_event"], new.pk)
        self.assertEqual(journal.metadata["accounting_event"], old.pk)
        self.assertEqual(before[1], self.content(journal)[1])

        # Buku besar tidak bergerak.
        self.assertFalse(
            JournalLine.objects.filter(journal=journal, is_posted=True).exists(),
        )
        self.assertIsNone(journal.posted_at)

        # Penggantinya tetap DRAFT — PF-0G tidak memposting apa pun.
        self.assertEqual(
            new.generated_journal.status, JournalStatus.DRAFT,
        )

    def test_projection_still_verifies_after_supersession(self):
        """Jejaknya tetap terbaca: jurnal lama tetap proyeksi payload lama."""
        _, old, new = self.pair()

        AccountingEventProcessor.supersede_unposted_projection(
            old_event=old, new_event=new,
        )

        self.assertTrue(
            AccountingEventProcessor.verify_projection(old)["matches"],
        )

    def test_same_pair_is_idempotent(self):
        _, old, new = self.pair()

        first = AccountingEventProcessor.supersede_unposted_projection(
            old_event=old, new_event=new,
        )
        again = AccountingEventProcessor.supersede_unposted_projection(
            old_event=old, new_event=new,
        )

        self.assertEqual(first.pk, again.pk)
        self.assertEqual(again.superseded_by_id, new.pk)

    def test_a_different_superseding_event_fails_closed(self):
        company, old, new = self.pair()

        AccountingEventProcessor.supersede_unposted_projection(
            old_event=old, new_event=new,
        )

        other = self.event_for(
            company, new.event_type, amount="1300.00", replaces=old,
        )

        with self.assertRaises(AccountingEventConflict) as caught:
            AccountingEventProcessor.supersede_unposted_projection(
                old_event=old, new_event=other,
            )

        self.assertEqual(caught.exception.error_code, "supersede_conflict")

        old.refresh_from_db()
        self.assertEqual(old.superseded_by_id, new.pk)

    def test_self_supersession_is_refused(self):
        _, old, _ = self.pair()

        with self.assertRaises(AccountingEventConflict) as caught:
            AccountingEventProcessor.supersede_unposted_projection(
                old_event=old, new_event=old,
            )

        self.assertEqual(caught.exception.error_code, "supersede_self")

    def test_posted_projection_is_never_superseded(self):
        """Case B: yang sudah di buku besar dikoreksi lewat pembalikan."""
        company, old, new = self.pair(auto_post=True)

        self.assertEqual(
            old.generated_journal.status, JournalStatus.POSTED,
        )

        with self.assertRaises(AccountingEventConflict) as caught:
            AccountingEventProcessor.supersede_unposted_projection(
                old_event=old, new_event=new,
            )

        self.assertEqual(
            caught.exception.error_code, "supersede_posted_journal",
        )

        old.refresh_from_db()
        self.assertEqual(old.status, AccountingEventStatus.PROCESSED)
        self.assertEqual(old.generated_journal.status, JournalStatus.POSTED)

    def test_replacement_must_have_produced_its_journal(self):
        company = self.make_company()
        self.make_fiscal_year(company)
        event_type = self.policy_for(company)

        old = self.event_for(company, event_type)
        pending = self.event_for(company, event_type, process=False)

        with self.assertRaises(AccountingEventConflict) as caught:
            AccountingEventProcessor.supersede_unposted_projection(
                old_event=old, new_event=pending,
            )

        self.assertEqual(
            caught.exception.error_code, "supersede_replacement_missing",
        )

    def test_cross_company_supersession_is_refused(self):
        _, old, _ = self.pair()

        elsewhere = self.make_company()
        self.make_fiscal_year(elsewhere)
        other_type = self.policy_for(elsewhere)
        foreign = self.event_for(elsewhere, other_type)

        with self.assertRaises(AccountingEventConflict) as caught:
            AccountingEventProcessor.supersede_unposted_projection(
                old_event=old, new_event=foreign,
            )

        self.assertEqual(caught.exception.error_code, "supersede_company")

    def test_an_event_reference_is_what_makes_a_journal_a_projection(self):
        """
        Penjagaan "jurnalnya harus proyeksi" ada di
        `supersede_unposted_projection`, tapi **tidak bisa dipicu lewat
        jalur biasa**: jurnal yang ditunjuk `generated_journal` sebuah
        kejadian sudah otomatis dikendalikan sumbernya menurut definisi
        FIN-AJ1. Yang diuji di sini definisinya, bukan cabang yang
        mustahil itu — cabangnya dibiarkan sebagai jaring pengaman kalau
        definisinya kelak menyempit.
        """
        company, journal = self.stage()

        self.assertFalse(JournalService.is_source_controlled(journal))

        event_type = self.policy_for(company)
        new = self.event_for(company, event_type)

        old = AccountingEvent.objects.create(
            event_type="MANUAL_TEST", source_module="test", source_id="x",
            company=company, event_date=AS_OF,
            idempotency_key=self.next_code("man"),
            status=AccountingEventStatus.PROCESSED,
            generated_journal=journal,
        )

        self.assertTrue(JournalService.is_source_controlled(journal))

        AccountingEventProcessor.supersede_unposted_projection(
            old_event=old, new_event=new,
        )

        journal.refresh_from_db()

        self.assertEqual(journal.status, JournalStatus.CANCELLED)


class SupersededLifecycleTests(SupersessionTestCase):

    def superseded(self):
        company, old, new = self.pair()

        AccountingEventProcessor.supersede_unposted_projection(
            old_event=old, new_event=new,
        )

        old.refresh_from_db()

        return company, old, new

    def test_superseded_event_cannot_be_retried(self):
        company, old, _ = self.superseded()

        user = self.make_scoped_user(
            companies=[company],
            permissions=["finance.change_accountingevent"],
        )

        with self.assertRaises(ValidationError):
            AccountingEventProcessor.retry(event=old, user=user)

        old.refresh_from_db()
        self.assertEqual(old.status, AccountingEventStatus.SUPERSEDED)

    def test_superseded_event_is_never_processed_again(self):
        company, old, _ = self.superseded()

        journal_count = Journal.objects.filter(company=company).count()

        again = AccountingEventProcessor.process(event=old)

        self.assertEqual(again.status, AccountingEventStatus.SUPERSEDED)
        self.assertEqual(
            Journal.objects.filter(company=company).count(), journal_count,
        )

    def test_retired_journal_cannot_be_submitted_or_posted(self):
        company, old, _ = self.superseded()

        journal = old.generated_journal
        poster = self.holder(company, POST_JOURNAL_PERMISSION)

        with self.assertRaises(ValidationError):
            FinancePostingService.post(journal=journal, user=poster)

        with self.assertRaises(ValidationError):
            JournalService.submit(
                journal=journal,
                user=self.finance_user(company),
            )

        journal.refresh_from_db()
        self.assertEqual(journal.status, JournalStatus.CANCELLED)

    def test_retired_journal_content_is_still_locked(self):
        """FIN-AJ1 tidak dibuka sedikit pun oleh supersesi."""
        company, old, _ = self.superseded()

        journal = old.generated_journal
        user = self.finance_user(company)
        before = self.content(journal)

        with self.assertRaises(AutomaticJournalLocked):
            JournalService.update(
                instance=journal, data={"description": "x"}, user=user,
            )

        with self.assertRaises(AutomaticJournalLocked):
            JournalService.replace_lines(journal=journal, lines=[], user=user)

        self.assertEqual(self.content(journal), before)


class ReplacementPostingGuardTests(SupersessionTestCase):

    def posted_original(self):
        """Kejadian lama yang jurnalnya **sudah** diposting + penggantinya."""
        company = self.make_company()
        self.make_fiscal_year(company)
        event_type = self.policy_for(company)

        old = self.event_for(company, event_type)

        FinancePostingService.post(
            journal=old.generated_journal,
            user=self.holder(company, POST_JOURNAL_PERMISSION),
        )

        new = self.event_for(
            company, event_type, amount="1200.00", replaces=old,
        )

        return company, old, new

    def test_replacement_cannot_post_while_the_original_is_live(self):
        company, old, new = self.posted_original()

        poster = self.holder(company, POST_JOURNAL_PERMISSION)

        with self.assertRaises(ValidationError) as caught:
            FinancePostingService.post(
                journal=new.generated_journal, user=poster,
            )

        self.assertIn(
            "correction_predecessor_not_reversed",
            caught.exception.message_dict,
        )

        new.generated_journal.refresh_from_db()
        old.generated_journal.refresh_from_db()

        self.assertEqual(new.generated_journal.status, JournalStatus.DRAFT)
        self.assertEqual(old.generated_journal.status, JournalStatus.POSTED)

    def test_replacement_posts_once_the_original_is_reversed(self):
        company, old, new = self.posted_original()

        reversal = FinanceReversalService.reverse(
            journal=old.generated_journal,
            user=self.holder(company, REVERSE_JOURNAL_PERMISSION),
            reason="digantikan koreksi",
        )

        old.generated_journal.refresh_from_db()

        self.assertEqual(old.generated_journal.status, JournalStatus.REVERSED)
        self.assertNotEqual(reversal.pk, new.generated_journal_id)
        self.assertEqual(reversal.reversal_of_id, old.generated_journal_id)

        result = FinancePostingService.post(
            journal=new.generated_journal,
            user=self.holder(company, POST_JOURNAL_PERMISSION),
        )

        self.assertEqual(result.journal.status, JournalStatus.POSTED)

    def test_reversal_lines_negate_the_original(self):
        company, old, _ = self.posted_original()

        original = old.generated_journal

        reversal = FinanceReversalService.reverse(
            journal=original,
            user=self.holder(company, REVERSE_JOURNAL_PERMISSION),
            reason="koreksi",
        )

        def sides(journal):
            return sorted(
                journal.lines.values_list("account_id", "debit", "credit"),
            )

        flipped = sorted(
            (account, credit, debit)
            for account, debit, credit in original.lines.values_list(
                "account_id", "debit", "credit",
            )
        )

        self.assertEqual(sides(reversal), flipped)
        self.assertEqual(
            reversal.total_debit, original.total_credit,
        )

    def test_repeat_reversal_creates_no_duplicate(self):
        company, old, _ = self.posted_original()

        user = self.holder(company, REVERSE_JOURNAL_PERMISSION)

        FinanceReversalService.reverse(
            journal=old.generated_journal, user=user, reason="koreksi",
        )

        with self.assertRaises(ValidationError):
            FinanceReversalService.reverse(
                journal=old.generated_journal, user=user, reason="lagi",
            )

        self.assertEqual(
            Journal.objects.filter(
                reversal_of=old.generated_journal_id,
            ).count(),
            1,
        )

    def test_guard_passes_when_the_predecessor_was_superseded(self):
        """Case A: pendahulunya dicabut, bukan diposting — tidak menghalangi."""
        _, old, new = self.pair()

        AccountingEventProcessor.supersede_unposted_projection(
            old_event=old, new_event=new,
        )

        company = new.company

        result = FinancePostingService.post(
            journal=new.generated_journal,
            user=self.holder(company, POST_JOURNAL_PERMISSION),
        )

        self.assertEqual(result.journal.status, JournalStatus.POSTED)

    def test_journal_without_replacement_link_is_unaffected(self):
        company, journal = self.stage()

        result = FinancePostingService.post(
            journal=journal, user=self.holder(company, POST_JOURNAL_PERMISSION),
        )

        self.assertEqual(result.journal.status, JournalStatus.POSTED)
        self.assertNotIn("replaces_event", journal.metadata or {})
        self.assertEqual(
            Decimal(result.journal.total_debit), Decimal("1000.00"),
        )
