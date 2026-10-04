"""
Alur persetujuan lewat engine yang sudah ada — bukan mesin kedua.

Yang dibuktikan: dokumen izin memakai `apps/workflow` apa adanya,
mejanya lahir dari seed (bukan dari rantai yang disalin ke test),
keputusannya berpindah lewat `WorkflowService`, dan status dokumennya
ikut berpindah **juga saat tombolnya ditekan dari kotak masuk generik**
— jalur yang paling mudah lupa didaftarkan, dan yang gagalnya diam.
"""

from __future__ import annotations

from datetime import time

from django.core.exceptions import ValidationError

from apps.hr.api.attendance_permission.services import (
    AttendancePermissionService,
)
from apps.hr.models import (
    AttendancePermissionStatus,
    AttendancePermissionType,
)
from apps.workflow.models import (
    ApprovalStatus,
    InstanceStatus,
    WorkflowDefinition,
)
from apps.workflow.registry import completion_handler

from .base import AttendancePermissionTestCase


class PermissionWorkflowTestCase(AttendancePermissionTestCase):
    def setUp(self):
        super().setUp()

        self.supervisor = self.make_employee()

        self.staff = self.make_employee(reports_to=self.supervisor)

        self.hr = self.make_employee(roles=["HR-ADMIN"])

    def make_submitted(self):
        permission = self.make_permission(
            self.staff,
            permission_type=AttendancePermissionType.LATE_ARRIVAL,
            end_time=time(10, 0),
        )

        workflow = AttendancePermissionService.submit(
            permission=permission,
            user=self.staff.user,
        )

        permission.refresh_from_db()

        return permission, workflow

    # ------------------------------------------------------------------

    def test_seed_creates_the_permission_flow(self):
        definition = WorkflowDefinition.objects.filter(
            code="HR-ATT-PERMISSION",
            is_deleted=False,
        ).first()

        self.assertIsNotNone(definition)

        self.assertEqual(definition.module, "hr")
        self.assertEqual(definition.document_type, "attendance_permission")

    def test_completion_handler_is_registered(self):
        """
        Kalau lupa mendaftarkannya, tombol Approve di kotak masuk
        generik tetap jalan tapi status dokumennya **tidak ikut
        berpindah**, dan gagalnya diam.
        """
        self.assertIsNotNone(
            completion_handler(
                module="hr",
                document_type="attendance_permission",
            ),
        )

    def test_submit_creates_every_approval_row_up_front(self):
        permission, workflow = self.make_submitted()

        self.assertEqual(
            permission.status,
            AttendancePermissionStatus.SUBMITTED,
        )

        self.assertIsNotNone(permission.submitted_at)

        rows = list(workflow.approvals.order_by("sequence"))

        # Dua meja: atasan langsung, lalu HR. Seluruh barisnya lahir
        # saat submit — formulir tercetak harus memperlihatkan semua
        # kotak sejak awal.
        self.assertEqual(len(rows), 2)

        self.assertEqual(rows[0].approver_employee_id, self.supervisor.pk)
        self.assertEqual(rows[1].approver_employee_id, self.hr.pk)

    def test_double_submit_is_rejected(self):
        permission, _ = self.make_submitted()

        with self.assertRaises(ValidationError):
            AttendancePermissionService.submit(permission=permission)

    def test_first_approval_moves_to_in_review(self):
        permission, workflow = self.make_submitted()

        AttendancePermissionService.decide(
            permission=permission,
            approved=True,
            user=self.supervisor.user,
        )

        permission.refresh_from_db()
        workflow.refresh_from_db()

        self.assertEqual(workflow.status, InstanceStatus.PENDING)

        self.assertEqual(
            permission.status,
            AttendancePermissionStatus.IN_REVIEW,
        )

    def test_final_approval_approves_the_document(self):
        permission, workflow = self.make_submitted()

        AttendancePermissionService.decide(
            permission=permission,
            approved=True,
            user=self.supervisor.user,
        )

        AttendancePermissionService.decide(
            permission=permission,
            approved=True,
            user=self.hr.user,
        )

        permission.refresh_from_db()
        workflow.refresh_from_db()

        self.assertEqual(workflow.status, InstanceStatus.APPROVED)

        self.assertEqual(
            permission.status,
            AttendancePermissionStatus.APPROVED,
        )

        self.assertIsNotNone(permission.approved_at)

    def test_rejection_stops_the_flow(self):
        permission, workflow = self.make_submitted()

        AttendancePermissionService.decide(
            permission=permission,
            approved=False,
            user=self.supervisor.user,
            notes="Tidak ada alasan yang mendesak.",
        )

        permission.refresh_from_db()
        workflow.refresh_from_db()

        self.assertEqual(workflow.status, InstanceStatus.REJECTED)

        self.assertEqual(
            permission.status,
            AttendancePermissionStatus.REJECTED,
        )

        self.assertIsNotNone(permission.rejected_at)

        rows = list(workflow.approvals.order_by("sequence"))

        self.assertEqual(rows[0].status, ApprovalStatus.REJECTED)

    def test_cancel_before_approval_returns_to_draft(self):
        """
        Yang belum disetujui kembali ke DRAFT supaya bisa diperbaiki
        dan diajukan ulang. Yang sudah disetujui tidak — ia sudah
        pernah memaafkan sesuatu, dan mengembalikannya ke draft membuat
        dokumen yang pernah berlaku terbaca seolah tidak pernah ada.
        """
        permission, _ = self.make_submitted()

        AttendancePermissionService.cancel(
            permission=permission,
            user=self.staff.user,
        )

        permission.refresh_from_db()

        self.assertEqual(
            permission.status,
            AttendancePermissionStatus.DRAFT,
        )

        self.assertTrue(permission.is_editable)

    def test_inbox_decision_moves_the_document_status(self):
        """
        Jalur kotak masuk generik.

        **Registry-nya dikonsultasi di view, bukan di
        `WorkflowService`** — `_module_callback` di
        `apps/workflow/api/approval/views.py` mencarikan handler modulnya
        lalu mengopernya sebagai `on_complete`. Engine sendiri sengaja
        tidak menyentuh kolom status modul mana pun, jadi
        `WorkflowService.approve()` tanpa `on_complete` memang
        meninggalkan dokumennya di tempat.

        Test ini meniru langkah view itu persis. Yang dibuktikannya:
        handler yang terdaftar benar-benar memindahkan status dokumen
        saat keputusannya datang dari kotak masuk — jalur yang gagal
        diam kalau `@register_completion` lupa ditulis.
        """
        from apps.workflow.services import WorkflowService

        permission, workflow = self.make_submitted()

        handler = completion_handler(
            module=workflow.module,
            document_type=workflow.document_type,
        )

        self.assertIsNotNone(handler)

        for approver in (self.supervisor, self.hr):
            workflow.refresh_from_db()

            WorkflowService.approve(
                instance=workflow,
                user=approver.user,
                on_complete=handler,
            )

        permission.refresh_from_db()

        self.assertEqual(
            permission.status,
            AttendancePermissionStatus.APPROVED,
        )

    def test_workflow_context_carries_the_values_steps_can_read(self):
        permission = self.make_permission(
            self.staff,
            permission_type=AttendancePermissionType.TEMPORARY_OUT,
            start_time=time(13, 0),
            end_time=time(15, 0),
        )

        context = AttendancePermissionService.workflow_context(permission)

        self.assertEqual(
            context["permission_type"],
            AttendancePermissionType.TEMPORARY_OUT,
        )

        self.assertEqual(context["duration_minutes"], 120)
