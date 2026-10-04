"""
Siklus Visitor Request yang berlaku hari ini (BT-1): alur persetujuan
lewat engine yang ada, kedatangan di pos jaga, dan kartu tamu.

Alurnya dari seed sungguhan `HR-VISITOR-REQUEST` (Atasan Langsung →
HRGA). Jalur kotak masuk generik ikut dikunci: di sanalah status
dokumen paling mudah tertinggal, dan gagalnya diam.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError

from apps.hr.api.visitor.services import (
    VisitorPassService,
    VisitorRequestService,
)
from apps.hr.models import (
    VisitorArrivalStatus,
    VisitorPass,
    VisitorPassStatus,
    VisitorRequestStatus,
)
from apps.workflow.models import InstanceStatus, WorkflowDefinition
from apps.workflow.registry import completion_handler
from apps.workflow.services.workflow_service import WorkflowService

from .base import VisitorTestCase


class VisitorWorkflowContractTests(VisitorTestCase):
    def setUp(self):
        super().setUp()

        self.manager = self.make_employee()
        self.hrga = self.make_employee(roles=["HRGA"])
        self.requester = self.make_employee(reports_to=self.manager)

    def submitted(self, **extra):
        request = self.make_request(requester=self.requester, **extra)

        workflow = VisitorRequestService.submit(
            request=request,
            user=self.requester.user,
        )

        request.refresh_from_db()

        return request, workflow

    # ------------------------------------------------------------------

    def test_seed_defines_manager_then_hrga(self):
        definition = WorkflowDefinition.objects.get(
            code="HR-VISITOR-REQUEST",
            is_deleted=False,
        )

        self.assertEqual(
            (definition.module, definition.document_type),
            ("hr", "visitor_request"),
        )

    def test_completion_handler_is_registered(self):
        self.assertIsNotNone(
            completion_handler(module="hr", document_type="visitor_request"),
        )

    def test_submit_creates_manager_and_hrga_desks(self):
        request, workflow = self.submitted()

        self.assertEqual(request.status, VisitorRequestStatus.SUBMITTED)

        rows = list(workflow.approvals.order_by("sequence"))

        self.assertEqual(
            [row.approver_employee_id for row in rows],
            [self.manager.pk, self.hrga.pk],
        )

    def test_double_submit_is_rejected(self):
        request, _ = self.submitted()

        with self.assertRaises(ValidationError):
            VisitorRequestService.submit(request=request)

    def test_first_decision_moves_to_under_review(self):
        request, workflow = self.submitted()

        VisitorRequestService.decide(
            request=request,
            approved=True,
            user=self.manager.user,
        )

        request.refresh_from_db()
        workflow.refresh_from_db()

        self.assertEqual(workflow.status, InstanceStatus.PENDING)
        self.assertEqual(request.status, VisitorRequestStatus.UNDER_REVIEW)

    def test_final_decision_approves(self):
        request, _ = self.submitted()

        for approver in (self.manager, self.hrga):
            VisitorRequestService.decide(
                request=request,
                approved=True,
                user=approver.user,
            )

        request.refresh_from_db()

        self.assertEqual(request.status, VisitorRequestStatus.APPROVED)

    def test_rejection_makes_the_document_editable_again(self):
        request, _ = self.submitted()

        VisitorRequestService.decide(
            request=request,
            approved=False,
            user=self.manager.user,
        )

        request.refresh_from_db()

        self.assertEqual(request.status, VisitorRequestStatus.REJECTED)
        self.assertTrue(request.is_editable)

    def test_withdraw_returns_to_draft(self):
        request, _ = self.submitted()

        VisitorRequestService.withdraw(
            request=request,
            user=self.requester.user,
        )

        request.refresh_from_db()

        self.assertEqual(request.status, VisitorRequestStatus.DRAFT)

    def test_generic_inbox_path_reaches_approved_through_the_handler(self):
        """
        Keputusan dari kotak masuk generik memindahkan status di meja
        terakhir lewat handler terdaftar — kotak masuk
        (`apps/workflow/api/approval/views.py`) mengoper
        `completion_handler(module, document_type)` sebagai
        `on_complete`, persis seperti di sini. `WorkflowService` sendiri
        **tidak** mencari handler kalau callback-nya kosong.

        Meja di tengah **tidak** memindahkannya ke UNDER_REVIEW: engine
        tidak punya hook per-step (perilaku yang didokumentasikan).
        """
        request, workflow = self.submitted()

        handler = completion_handler(
            module="hr",
            document_type="visitor_request",
        )

        WorkflowService.approve(
            instance=workflow,
            user=self.manager.user,
            on_complete=handler,
        )

        request.refresh_from_db()
        self.assertEqual(request.status, VisitorRequestStatus.SUBMITTED)

        workflow.refresh_from_db()
        WorkflowService.approve(
            instance=workflow,
            user=self.hrga.user,
            on_complete=handler,
        )

        request.refresh_from_db()
        self.assertEqual(request.status, VisitorRequestStatus.APPROVED)

    def test_legacy_internal_draft_cannot_be_submitted(self):
        """
        BT-2A: draft internal lama tidak diteruskan ke alur — tidak ada
        instance workflow yang terbit, statusnya tetap DRAFT.
        """
        request = self.make_legacy_internal(
            requester=self.requester,
            employee=self.make_employee(location=self.site),
        )

        with self.assertRaises(ValidationError) as caught:
            VisitorRequestService.submit(
                request=request,
                user=self.requester.user,
            )

        self.assertIn("visitor_type", caught.exception.message_dict)

        request.refresh_from_db()
        self.assertEqual(request.status, VisitorRequestStatus.DRAFT)
        self.assertIsNone(VisitorRequestService.workflow_for(request))


class VisitorArrivalContractTests(VisitorTestCase):
    def setUp(self):
        super().setUp()

        self.requester = self.make_employee()
        self.guard = self.make_employee(location=self.site)

    def approved(self, **extra):
        """Status disetel langsung: yang diuji kedatangan, bukan alurnya."""
        request = self.make_request(requester=self.requester, **extra)

        request.status = VisitorRequestStatus.APPROVED
        request.save(update_fields=["status"])

        return request

    def test_check_in_requires_approved(self):
        request = self.make_request(requester=self.requester)

        with self.assertRaises(ValidationError) as caught:
            VisitorRequestService.check_in(request=request)

        self.assertIn("status", caught.exception.message_dict)

    def test_check_in_marks_arrival_and_issues_one_pass(self):
        request = self.approved()

        request = VisitorRequestService.check_in(
            request=request,
            user=self.guard.user,
            gate="Gate 1",
        )

        self.assertEqual(request.arrival_status, VisitorArrivalStatus.CHECKED_IN)
        self.assertIsNotNone(request.checked_in_at)
        self.assertEqual(request.check_in_gate, "Gate 1")

        passes = VisitorPass.objects.filter(request=request, is_deleted=False)

        self.assertEqual(passes.count(), 1)
        self.assertTrue(passes.first().pass_number.startswith("VP"))

    def test_second_check_in_is_rejected(self):
        request = self.approved()

        VisitorRequestService.check_in(request=request)

        with self.assertRaises(ValidationError) as caught:
            VisitorRequestService.check_in(request=request)

        self.assertIn("arrival_status", caught.exception.message_dict)

    def test_issue_returns_the_pass_already_held(self):
        request = self.approved()

        first = VisitorPassService.issue(request=request)
        second = VisitorPassService.issue(request=request)

        self.assertEqual(first.pk, second.pk)

    def test_pass_validity_defaults_to_the_visit_dates(self):
        request = self.approved()

        issued = VisitorPassService.issue(request=request)

        self.assertEqual(issued.valid_from, request.visit_start_date)
        self.assertEqual(issued.valid_until, request.visit_end_date)

    def test_pass_is_not_issued_for_a_draft(self):
        request = self.make_request(requester=self.requester)

        with self.assertRaises(ValidationError):
            VisitorPassService.issue(request=request)

    def test_check_out_completes_the_visit_and_returns_passes(self):
        request = self.approved()

        VisitorRequestService.check_in(request=request)

        request = VisitorRequestService.check_out(request=request)

        self.assertEqual(request.status, VisitorRequestStatus.COMPLETED)
        self.assertEqual(
            request.arrival_status,
            VisitorArrivalStatus.CHECKED_OUT,
        )

        self.assertFalse(
            VisitorPass.objects.filter(
                request=request,
                status=VisitorPassStatus.ISSUED,
            ).exists(),
        )

    def test_check_out_before_check_in_is_rejected(self):
        request = self.approved()

        with self.assertRaises(ValidationError):
            VisitorRequestService.check_out(request=request)

    def test_internal_visit_finishes_its_lifecycle(self):
        """
        Dokumen internal lama yang sudah disetujui tetap bisa
        check-in/out sampai COMPLETED — BT-2A hanya menutup pembuatan,
        suntingan, dan pengajuan baru, bukan menyelesaikan yang lama.
        """
        request = self.make_legacy_internal(
            requester=self.requester,
            employee=self.make_employee(location=self.site),
            status=VisitorRequestStatus.APPROVED,
        )

        VisitorRequestService.check_in(request=request)
        request = VisitorRequestService.check_out(request=request)

        self.assertEqual(request.status, VisitorRequestStatus.COMPLETED)

    def test_no_show_keeps_the_document_approved(self):
        """No Show bukan pembatalan: dokumennya tetap APPROVED."""
        request = self.approved()

        request = VisitorRequestService.mark_no_show(request=request)

        self.assertEqual(request.arrival_status, VisitorArrivalStatus.NO_SHOW)
        self.assertEqual(request.status, VisitorRequestStatus.APPROVED)

    def test_no_show_after_check_in_is_rejected(self):
        request = self.approved()

        # `check_in` mengunci dan mengembalikan instance baru; `mark_no_show`
        # menilai instance yang dioper **tanpa** membaca ulang database
        # (layar mengoper `get_object()` yang segar). Instance lama yang
        # masih berbunyi "belum check-in" akan lolos.
        request = VisitorRequestService.check_in(request=request)

        with self.assertRaises(ValidationError):
            VisitorRequestService.mark_no_show(request=request)

    def test_no_show_is_currently_accepted_on_a_draft(self):
        """
        PERILAKU SAAT INI, bukan persyaratan: `mark_no_show` tidak
        memeriksa status dokumen, jadi dokumen DRAFT pun bisa ditandai
        No Show. Dilaporkan di BT-1; kalau nanti sengaja diperketat,
        ubah test ini bersama perubahannya.
        """
        request = self.make_request(requester=self.requester)

        request = VisitorRequestService.mark_no_show(request=request)

        self.assertEqual(request.status, VisitorRequestStatus.DRAFT)
        self.assertEqual(request.arrival_status, VisitorArrivalStatus.NO_SHOW)
