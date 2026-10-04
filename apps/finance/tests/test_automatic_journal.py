"""
FIN-AJ1 — jurnal yang dikendalikan sumbernya.

Jurnal yang diterbitkan `AccountingEventProcessor` adalah **proyeksi**
kejadiannya: payload + kebijakan + pemetaan. Kalau isinya bisa disunting
atau dibatalkan dari layar jurnal, payload kejadian, penanda idempotensi,
digest payroll, dan jurnalnya berhenti saling cocok — diam-diam.

Yang diuji di sini:

* jurnal **manual** tetap bisa disunting seperti sebelumnya;
* jurnal **proyeksi** menolak setiap perubahan isi — kepala, baris,
  dimensi, provenance, penghapusan, penggantian baris, pembatalan — di
  service **dan** API, di status DRAFT, REJECTED, dan sesudah ditarik,
  oleh siapa pun termasuk superuser;
* perpindahan status tetap berjalan: ajukan → setujui → posting;
* retry dan pencatatan ulang tidak menerbitkan proyeksi kedua;
* `verify_projection()` membuktikan jurnal = proyeksi payload-nya.

Setiap penolakan memeriksa `content()` — sidik isi jurnal — tidak berubah.
"""

from decimal import Decimal

from django.core.exceptions import ValidationError

from apps.accounts.models import User
from apps.administration.models import Location
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
    AUTOMATIC_JOURNAL_ERROR_CODE,
    CHANGE_JOURNAL_PERMISSION,
    POST_JOURNAL_PERMISSION,
    AccountingEventProcessor,
    AutomaticJournalLocked,
    JournalLineService,
    JournalService,
)

from .base import AS_OF
from .test_journal_authorization import (
    PAYROLL_PERMISSIONS,
    JournalAuthorizationTestCase,
)


EVENT_DATE = AS_OF

FULL_JOURNAL_PERMISSIONS = (
    "finance.view_journal",
    "finance.add_journal",
    "finance.change_journal",
    "finance.delete_journal",
    "finance.view_journalline",
    "finance.add_journalline",
    "finance.change_journalline",
    "finance.delete_journalline",
    "finance.post_journal",
    "finance.reverse_journal",
)


class AutomaticJournalTestCase(JournalAuthorizationTestCase):

    # ------------------------------------------------------------------
    # Panggung
    # ------------------------------------------------------------------

    def generated(self, *, company=None, auto_post=False):
        """Satu kejadian PROCESSED + jurnal proyeksinya (DRAFT)."""
        if company is None:
            company = self.make_company()
            self.make_fiscal_year(company)

        expense, payable = self.make_pair(company)

        event_type = f"AJ1_{self.next_code('T')}"

        policy = AccountingPolicy.objects.create(
            code=self.next_code("POL"),
            name="AJ1 policy",
            company=company,
            event_type=event_type,
            journal_type="automatic",
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

        key = self.next_code("aj1")

        event = AccountingEventProcessor.record(
            event_type=event_type,
            source_module="test",
            source_type="aj1",
            source_id=key,
            source_reference=f"REF-{key}",
            company=company,
            event_date=EVENT_DATE,
            payload={"amount": "1000.00"},
            idempotency_key=f"aj1:{key}",
        )

        self.assertEqual(event.status, AccountingEventStatus.PROCESSED)

        journal = event.generated_journal

        return company, event, journal

    def content(self, journal) -> tuple:
        """Sidik isi akuntansi: kepala + provenance + baris + dimensi."""
        journal = Journal.objects.get(pk=journal.pk)

        header = (
            journal.company_id, journal.posting_date,
            journal.accounting_period_id, journal.journal_type,
            journal.description, journal.source_module, journal.source_type,
            journal.source_id, journal.source_reference,
            tuple(sorted((journal.metadata or {}).items())),
            journal.is_deleted, str(journal.total_debit),
            str(journal.total_credit),
        )

        lines = tuple(
            JournalLine.objects.filter(journal=journal).order_by("id")
            .values_list(
                "id", "account_id", "debit", "credit", "description",
                "is_deleted", "branch_id", "location_id", "division_id",
                "department_id", "section_id", "cost_center_id",
            )
        )

        return header, lines

    def finance_user(self, company):
        """Setara FINANCE-MANAGER: seluruh izin jurnal + baris + posting."""
        return self.make_scoped_user(
            companies=[company], permissions=FULL_JOURNAL_PERMISSIONS,
        )

    def superuser(self):
        name = self.next_code("root")

        return User.objects.create_superuser(
            username=name, email=f"{name}@finance.test", password="x",
        )

    def assert_locked(self, response_or_callable, journal, before):
        """400 ber-`automatic_journal` (API) atau `AutomaticJournalLocked`."""
        if callable(response_or_callable):
            with self.assertRaises(AutomaticJournalLocked) as caught:
                response_or_callable()

            self.assertEqual(
                caught.exception.error_code, AUTOMATIC_JOURNAL_ERROR_CODE,
            )
        else:
            response = response_or_callable

            self.assertEqual(response.status_code, 400, response.content)
            self.assertIn("automatic_journal", response.json()["errors"])

        self.assertEqual(self.content(journal), before)

    def patch_journal(self, user, journal, data):
        return self.api(user).patch(
            f"/api/finance/journals/{journal.pk}/", data, format="json",
        )

    def patch_line(self, user, line, data):
        return self.api(user).patch(
            f"/api/finance/journal-lines/{line.pk}/", data, format="json",
        )


# ======================================================================
# Manual tetap bisa disunting
# ======================================================================


class ManualJournalStaysEditableTests(AutomaticJournalTestCase):

    def test_manual_draft_header_is_editable(self):
        """#1"""
        company, journal = self.stage()

        response = self.patch_journal(
            self.finance_user(company), journal, {"description": "edited"},
        )

        self.assertEqual(response.status_code, 200, response.content)

        journal.refresh_from_db()
        self.assertEqual(journal.description, "edited")

    def test_manual_draft_lines_are_editable(self):
        """#2 — lewat API baris, `replace_lines`, dan hapus baris."""
        company, journal = self.stage()
        user = self.finance_user(company)

        line = journal.lines.order_by("line_number").first()

        response = self.patch_line(user, line, {"description": "edited"})
        self.assertEqual(response.status_code, 200, response.content)

        expense, payable = self.make_pair(company)

        JournalService.replace_lines(
            journal=journal,
            lines=self.balanced_lines(expense, payable, "250.00"),
            user=user,
        )

        journal.refresh_from_db()
        self.assertEqual(journal.total_debit, Decimal("250.00"))

        line = journal.lines.order_by("line_number").first()
        JournalLineService.soft_delete(instance=line, user=user)

        self.assertTrue(JournalLine.objects.get(pk=line.pk).is_deleted)

    def test_manual_journal_type_automatic_is_not_source_controlled(self):
        """`journal_type` bukan bukti asal — jenis itu bisa dipilih di form."""
        company, journal = self.stage()
        Journal.objects.filter(pk=journal.pk).update(journal_type="automatic")

        self.assertFalse(JournalService.is_source_controlled(journal))

        response = self.patch_journal(
            self.finance_user(company), journal, {"description": "still mine"},
        )

        self.assertEqual(response.status_code, 200, response.content)

    def test_manual_draft_can_still_be_cancelled(self):
        company, journal = self.stage()

        JournalService.cancel(
            journal=journal, user=self.holder(company, CHANGE_JOURNAL_PERMISSION),
            reason="salah",
        )

        journal.refresh_from_db()
        self.assertEqual(journal.status, JournalStatus.CANCELLED)

    def test_manual_journal_cannot_claim_event_provenance(self):
        """Kunci provenance hanya ditulis pemroses kejadian."""
        company, journal = self.stage()
        _, event, _ = self.generated(company=company)
        user = self.finance_user(company)

        response = self.patch_journal(
            user, journal, {"metadata": {"accounting_event": event.pk}},
        )

        self.assertEqual(response.status_code, 400, response.content)
        self.assertIn("metadata", response.json()["errors"])

        with self.assertRaises(ValidationError):
            JournalService.create(data={
                "company": company,
                "posting_date": AS_OF,
                "description": "spoof",
                "metadata": {"accounting_event": event.pk},
            })

        journal.refresh_from_db()
        self.assertNotIn("accounting_event", journal.metadata or {})


# ======================================================================
# Proyeksi menolak perubahan isi
# ======================================================================


class AutomaticJournalContentTests(AutomaticJournalTestCase):

    def test_generated_journal_is_source_controlled(self):
        _, event, journal = self.generated()

        self.assertEqual(journal.status, JournalStatus.DRAFT)
        self.assertTrue(JournalService.is_source_controlled(journal))
        self.assertEqual(journal.metadata["accounting_event"], event.pk)

    def test_header_fields_cannot_be_changed(self):
        """#3, #22, #23 — kepala, provenance, sumber."""
        company, _, journal = self.generated()
        user = self.finance_user(company)
        other = self.make_company()
        before = self.content(journal)

        for data in (
            {"description": "rewritten"},
            {"posting_date": "2027-03-20"},
            {"journal_type": "manual"},
            {"company": other.pk},
            {"source_module": "manual", "source_id": "X"},
            {"source_reference": "FAKE"},
            {"metadata": {}},
            {"metadata": {"accounting_event": 999999}},
        ):
            with self.subTest(data=data):
                self.assert_locked(
                    self.patch_journal(user, journal, data), journal, before,
                )

        self.assert_locked(
            lambda: JournalService.update(
                instance=journal, data={"description": "x"}, user=user,
            ),
            journal, before,
        )

    def test_line_cannot_be_added(self):
        """#4"""
        company, _, journal = self.generated()
        user = self.finance_user(company)
        expense, _ = self.make_pair(company)
        before = self.content(journal)

        self.assert_locked(
            lambda: JournalLineService.create(
                data={
                    "journal": journal, "account": expense,
                    "debit": Decimal("1.00"), "credit": Decimal("0.00"),
                },
                user=user,
            ),
            journal, before,
        )

    def test_line_cannot_be_edited(self):
        """#5, #24 — nilai, akun, keterangan, dimensi."""
        company, _, journal = self.generated()
        user = self.finance_user(company)
        expense, _ = self.make_pair(company)
        site = Location.objects.create(
            company=company, code=self.next_code("LOC"), name="Site",
        )
        line = journal.lines.order_by("line_number").first()
        before = self.content(journal)

        for data in (
            {"debit": "1.00"},
            {"credit": "5.00"},
            {"account": expense.pk},
            {"description": "rewritten"},
            {"location": site.pk},
        ):
            with self.subTest(data=data):
                self.assert_locked(
                    self.patch_line(user, line, data), journal, before,
                )

        self.assert_locked(
            lambda: JournalLineService.update(
                instance=line, data={"debit": Decimal("1.00")}, user=user,
            ),
            journal, before,
        )

    def test_line_cannot_be_deleted(self):
        """#6"""
        company, _, journal = self.generated()
        user = self.finance_user(company)
        line = journal.lines.order_by("line_number").first()
        before = self.content(journal)

        self.assert_locked(
            self.api(user).delete(f"/api/finance/journal-lines/{line.pk}/"),
            journal, before,
        )
        self.assert_locked(
            self.api(user).post(
                "/api/finance/journal-lines/bulk-delete/",
                {"ids": [line.pk]}, format="json",
            ),
            journal, before,
        )
        self.assert_locked(
            lambda: JournalLineService.soft_delete(instance=line, user=user),
            journal, before,
        )

    def test_lines_cannot_be_bulk_replaced(self):
        """#7 — `replace_lines` dan `line_items` pada PATCH."""
        company, _, journal = self.generated()
        user = self.finance_user(company)
        expense, payable = self.make_pair(company)
        before = self.content(journal)

        self.assert_locked(
            lambda: JournalService.replace_lines(
                journal=journal,
                lines=self.balanced_lines(expense, payable, "5.00"),
                user=user,
            ),
            journal, before,
        )

        response = self.patch_journal(user, journal, {"line_items": [
            {"account": expense.pk, "debit": "5.00", "credit": "0.00"},
            {"account": payable.pk, "debit": "0.00", "credit": "5.00"},
        ]})

        self.assert_locked(response, journal, before)

    def test_journal_cannot_be_deleted(self):
        company, _, journal = self.generated()
        user = self.finance_user(company)
        before = self.content(journal)

        self.assert_locked(
            self.api(user).delete(f"/api/finance/journals/{journal.pk}/"),
            journal, before,
        )
        self.assert_locked(
            lambda: JournalService.soft_delete(instance=journal, user=user),
            journal, before,
        )

    def test_trusted_generation_path_cannot_refill_a_projection(self):
        """`write_generated_lines` tertutup begitu jurnalnya berisi."""
        company, event, journal = self.generated()
        expense, payable = self.make_pair(company)
        before = self.content(journal)

        self.assert_locked(
            lambda: JournalService.write_generated_lines(
                journal=journal, event=event,
                lines=self.balanced_lines(expense, payable, "9.00"),
            ),
            journal, before,
        )


# ======================================================================
# Pembatalan
# ======================================================================


class AutomaticJournalCancelTests(AutomaticJournalTestCase):

    def test_generated_draft_cannot_be_cancelled(self):
        """#8 — kejadiannya tetap PROCESSED dan menunjuk jurnal yang hidup."""
        company, event, journal = self.generated()
        user = self.finance_user(company)
        before = self.content(journal)

        response = self.api(user).post(
            f"/api/finance/journals/{journal.pk}/cancel/",
            {"reason": "tidak mau"}, format="json",
        )

        self.assert_locked(response, journal, before)
        self.assert_locked(
            lambda: JournalService.cancel(journal=journal, user=user, reason="x"),
            journal, before,
        )

        journal.refresh_from_db()
        event.refresh_from_db()

        self.assertEqual(journal.status, JournalStatus.DRAFT)
        self.assertIsNone(journal.cancelled_by_id)
        self.assertEqual(event.status, AccountingEventStatus.PROCESSED)
        self.assertEqual(event.generated_journal_id, journal.pk)

    def test_unauthorized_cancel_is_still_a_permission_error(self):
        """FIN-B1/B2 tetap lebih dulu: tanpa izin = 403, bukan pesan asal."""
        _, _, journal = self.generated()
        before = self.content(journal)

        from rest_framework.exceptions import PermissionDenied

        with self.assertRaises(PermissionDenied):
            JournalService.cancel(journal=journal, user=self.bare_user())

        self.assertEqual(self.content(journal), before)


# ======================================================================
# Siapa pun — izin bukan jalan keluarnya
# ======================================================================


class NobodyOverridesTests(AutomaticJournalTestCase):

    def attempts(self, journal, user):
        line = journal.lines.order_by("line_number").first()

        return {
            "update": lambda: JournalService.update(
                instance=journal, data={"description": "x"}, user=user,
            ),
            "line update": lambda: JournalLineService.update(
                instance=line, data={"description": "x"}, user=user,
            ),
            "line delete": lambda: JournalLineService.soft_delete(
                instance=line, user=user,
            ),
            "replace": lambda: JournalService.replace_lines(
                journal=journal, lines=[], user=user,
            ),
            "cancel": lambda: JournalService.cancel(
                journal=journal, user=user, reason="x",
            ),
            "delete": lambda: JournalService.soft_delete(
                instance=journal, user=user,
            ),
        }

    def test_finance_manager_permissions_do_not_unlock(self):
        """#11"""
        company, _, journal = self.generated()
        user = self.finance_user(company)
        before = self.content(journal)

        for label, attempt in self.attempts(journal, user).items():
            with self.subTest(attempt=label):
                self.assert_locked(attempt, journal, before)

    def test_superuser_and_internal_caller_do_not_unlock(self):
        """#12 — superuser lewat API/service, dan `user=None`."""
        company, _, journal = self.generated()
        before = self.content(journal)
        root = self.superuser()

        for user in (root, None):
            for label, attempt in self.attempts(journal, user).items():
                with self.subTest(user=user and "superuser", attempt=label):
                    self.assert_locked(attempt, journal, before)

        self.assert_locked(
            self.patch_journal(root, journal, {"description": "root"}),
            journal, before,
        )

    def test_payroll_permissions_cannot_mutate(self):
        """#13 — izin payroll saja: ditolak lebih awal (403/404)."""
        company, _, journal = self.generated()
        user = self.make_scoped_user(
            companies=[company], permissions=PAYROLL_PERMISSIONS,
        )
        before = self.content(journal)

        response = self.patch_journal(user, journal, {"description": "x"})

        self.assertIn(response.status_code, {403, 404})
        self.assertEqual(self.content(journal), before)


# ======================================================================
# Alur Finance tetap berjalan — dan isinya tetap terkunci di setiap status
# ======================================================================


class AutomaticJournalWorkflowTests(AutomaticJournalTestCase):

    def with_workflow(self):
        company = self.make_company()
        self.make_fiscal_year(company)
        self.make_definition(company)
        approver = self.make_approver(company)

        _, event, journal = self.generated(company=company)

        return company, event, journal, approver

    def test_submit_approve_post_still_work(self):
        """#14, #15, #16"""
        from apps.workflow.registry import completion_handler
        from apps.workflow.services.workflow_service import WorkflowService

        company, _, journal, approver = self.with_workflow()
        before = self.content(journal)

        submitter = self.holder(company, CHANGE_JOURNAL_PERMISSION)

        response = self.call(submitter, journal, "submit")
        self.assertEqual(response.status_code, 200, response.content)

        journal.refresh_from_db()
        self.assertEqual(journal.status, JournalStatus.SUBMITTED)

        instance = WorkflowService.instance_for(
            document=journal, module="finance", document_type="journal",
        )

        WorkflowService.approve(
            instance=instance, user=approver,
            on_complete=completion_handler(
                module="finance", document_type="journal",
            ),
        )

        journal.refresh_from_db()
        self.assertEqual(journal.status, JournalStatus.APPROVED)

        poster = self.holder(company, POST_JOURNAL_PERMISSION)

        response = self.call(poster, journal, "post")
        self.assertEqual(response.status_code, 200, response.content)

        journal.refresh_from_db()
        self.assertEqual(journal.status, JournalStatus.POSTED)
        self.assertEqual(journal.posted_by, poster)

        # Isinya sama persis dengan saat terbit.
        header, lines = self.content(journal)
        self.assertEqual(lines, before[1])
        self.assertEqual(header, before[0])

    def test_rejected_automatic_journal_stays_content_immutable(self):
        """#9"""
        from apps.workflow.registry import completion_handler
        from apps.workflow.services.workflow_service import WorkflowService

        company, _, journal, approver = self.with_workflow()
        user = self.finance_user(company)

        instance = JournalService.submit(
            journal=journal, user=self.holder(company, CHANGE_JOURNAL_PERMISSION),
        )
        WorkflowService.reject(
            instance=instance, user=approver, comment="salah",
            on_complete=completion_handler(
                module="finance", document_type="journal",
            ),
        )

        journal.refresh_from_db()
        self.assertEqual(journal.status, JournalStatus.REJECTED)

        before = self.content(journal)

        self.assert_locked(
            self.patch_journal(user, journal, {"description": "fixed"}),
            journal, before,
        )
        self.assert_locked(
            lambda: JournalService.replace_lines(
                journal=journal, lines=[], user=user,
            ),
            journal, before,
        )
        self.assert_locked(
            lambda: JournalService.cancel(journal=journal, user=user),
            journal, before,
        )

    def test_withdrawn_automatic_journal_stays_content_immutable(self):
        """#10"""
        company, _, journal, _ = self.with_workflow()
        user = self.finance_user(company)
        changer = self.holder(company, CHANGE_JOURNAL_PERMISSION)

        JournalService.submit(journal=journal, user=changer)
        JournalService.withdraw(journal=journal, user=changer)

        journal.refresh_from_db()
        self.assertEqual(journal.status, JournalStatus.DRAFT)

        before = self.content(journal)
        line = journal.lines.order_by("line_number").first()

        self.assert_locked(
            self.patch_line(user, line, {"debit": "2.00"}), journal, before,
        )
        self.assert_locked(
            self.patch_journal(user, journal, {"description": "fixed"}),
            journal, before,
        )

    def test_posted_automatic_journal_is_immutable_and_reversible(self):
        company, _, journal = self.generated(auto_post=True)
        user = self.finance_user(company)

        journal.refresh_from_db()
        self.assertEqual(journal.status, JournalStatus.POSTED)

        before = self.content(journal)

        self.assert_locked(
            self.patch_journal(user, journal, {"description": "x"}),
            journal, before,
        )

        from apps.finance.services import FinanceReversalService

        reversal = FinanceReversalService.reverse(
            journal=journal, user=user, reason="koreksi sumber",
        )

        self.assertEqual(reversal.status, JournalStatus.POSTED)
        self.assertEqual(self.content(journal)[1], before[1])


# ======================================================================
# Retry, idempotensi, verifikasi proyeksi
# ======================================================================


class ProjectionIntegrityTests(AutomaticJournalTestCase):

    def test_retry_of_processed_event_creates_no_second_projection(self):
        """#19"""
        company, event, journal = self.generated()
        before = self.content(journal)

        with self.assertRaises(ValidationError):
            AccountingEventProcessor.retry(
                event=event,
                user=self.make_scoped_user(
                    companies=[company],
                    permissions=["finance.change_accountingevent"],
                ),
            )

        # `process()` langsung pun mengembalikan yang sudah ada.
        again = AccountingEventProcessor.process(event=event)

        self.assertEqual(again.generated_journal_id, journal.pk)
        self.assertEqual(
            Journal.objects.filter(metadata__accounting_event=event.pk).count(),
            1,
        )
        self.assertEqual(self.content(journal), before)

    def test_recording_the_same_event_again_is_idempotent(self):
        """#20 (generik) — penanda sama, isi sama → kejadian & jurnal sama."""
        company, event, journal = self.generated()

        again = AccountingEventProcessor.record(
            event_type=event.event_type,
            source_module=event.source_module,
            source_type=event.source_type,
            source_id=event.source_id,
            source_reference=event.source_reference,
            company=company,
            event_date=event.event_date,
            payload=event.payload,
            idempotency_key=event.idempotency_key,
        )

        self.assertEqual(again.pk, event.pk)
        self.assertEqual(again.generated_journal_id, journal.pk)
        self.assertEqual(
            AccountingEvent.objects.filter(
                idempotency_key=event.idempotency_key,
            ).count(),
            1,
        )

    def test_verify_projection_matches_a_fresh_projection(self):
        """Payload + kebijakan/pemetaan yang sama → isi jurnal yang sama."""
        _, event, _ = self.generated()

        result = AccountingEventProcessor.verify_projection(event)

        self.assertTrue(result["verifiable"])
        self.assertTrue(result["header_matches"])
        self.assertTrue(result["matches"], result)
        self.assertEqual(result["lines_expected"], result["lines_actual"])

    def test_verify_projection_detects_out_of_band_tampering(self):
        """
        #21 — jalur yang didukung tidak bisa mengubah isinya (diuji di
        atas); yang di sini membuktikan perubahan **di luar** jalur itu
        (SQL langsung) terlihat oleh pemeriksanya.
        """
        _, event, journal = self.generated()

        line = journal.lines.order_by("line_number").first()
        JournalLine.objects.filter(pk=line.pk).update(description="tampered")

        self.assertFalse(
            AccountingEventProcessor.verify_projection(event)["matches"],
        )
