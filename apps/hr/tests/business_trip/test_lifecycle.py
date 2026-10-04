"""
BT-2 — siklus Business Trip dan alur persetujuannya.

Dua jalur keputusan dikunci **berdampingan**: layar Business Trip
(`BusinessTripService.decide`) dan kotak masuk generik
(`WorkflowService.approve` + handler terdaftar, persis seperti
`apps/workflow/api/approval/views.py`). Keduanya harus menghasilkan
keadaan yang sama di setiap meja — pembeda Visitor (UNDER_REVIEW yang
dilewati kotak masuk) sengaja tidak ditiru.
"""

from __future__ import annotations

from datetime import timedelta

from django.core.exceptions import ValidationError

from apps.hr.api.business_trip.services import BusinessTripService
from apps.hr.models import (
    BusinessTrip,
    BusinessTripLinkType,
    BusinessTripStatus,
)
from apps.workflow.models import InstanceStatus, WorkflowDefinition
from apps.workflow.registry import completion_handler, document_url
from apps.workflow.services import WorkflowService

from .base import FAR, BusinessTripTestCase, at


class BusinessTripWorkflowTests(BusinessTripTestCase):
    def setUp(self):
        super().setUp()

        self.manager = self.make_employee()
        self.hrga = self.make_employee(roles=["HRGA"])
        self.employee = self.make_employee(reports_to=self.manager)

    def submitted(self, **kwargs):
        trip = self.make_trip(self.employee, **kwargs)

        workflow = BusinessTripService.submit(
            trip=trip,
            user=self.employee.user,
        )

        trip.refresh_from_db()

        return trip, workflow

    # ------------------------------------------------------------------

    def test_seed_defines_the_default_flow(self):
        definition = WorkflowDefinition.objects.get(
            code="HR-BUSINESS-TRIP",
            is_deleted=False,
        )

        self.assertEqual(
            (definition.module, definition.document_type),
            ("hr", "business_trip"),
        )

    def test_handler_and_route_are_registered(self):
        self.assertIsNotNone(
            completion_handler(module="hr", document_type="business_trip"),
        )
        self.assertEqual(
            document_url(
                module="hr",
                document_type="business_trip",
                object_id=7,
            ),
            "/hr/business-trips/7",
        )

    def test_submit_creates_manager_then_hrga_desks(self):
        trip, workflow = self.submitted()

        self.assertEqual(trip.status, BusinessTripStatus.SUBMITTED)
        self.assertIsNotNone(trip.submitted_at)

        self.assertEqual(
            [
                row.approver_employee_id
                for row in workflow.approvals.order_by("sequence")
            ],
            [self.manager.pk, self.hrga.pk],
        )

    def test_submit_twice_is_rejected(self):
        trip, _ = self.submitted()

        with self.assertRaises(ValidationError):
            BusinessTripService.submit(trip=trip)

    def test_screen_path_approves_after_the_last_desk(self):
        trip, _ = self.submitted()

        BusinessTripService.decide(
            trip=trip,
            decision="approve",
            user=self.manager.user,
        )

        trip.refresh_from_db()
        self.assertEqual(trip.status, BusinessTripStatus.SUBMITTED)

        BusinessTripService.decide(
            trip=trip,
            decision="approve",
            user=self.hrga.user,
        )

        trip.refresh_from_db()
        self.assertEqual(trip.status, BusinessTripStatus.APPROVED)
        self.assertIsNotNone(trip.approved_at)

    def test_inbox_path_reaches_the_same_states(self):
        trip, workflow = self.submitted()

        handler = completion_handler(
            module="hr",
            document_type="business_trip",
        )

        WorkflowService.approve(
            instance=workflow,
            user=self.manager.user,
            on_complete=handler,
        )

        trip.refresh_from_db()
        self.assertEqual(trip.status, BusinessTripStatus.SUBMITTED)

        workflow.refresh_from_db()

        WorkflowService.approve(
            instance=workflow,
            user=self.hrga.user,
            on_complete=handler,
        )

        trip.refresh_from_db()
        self.assertEqual(trip.status, BusinessTripStatus.APPROVED)
        self.assertIsNotNone(trip.approved_at)

    def test_rejection_is_editable_and_resubmittable(self):
        trip, _ = self.submitted()

        BusinessTripService.decide(
            trip=trip,
            decision="reject",
            user=self.manager.user,
            notes="Anggaran belum ada",
        )

        trip.refresh_from_db()

        self.assertEqual(trip.status, BusinessTripStatus.REJECTED)
        self.assertTrue(trip.is_editable)

        BusinessTripService.submit(trip=trip, user=self.employee.user)
        trip.refresh_from_db()

        self.assertEqual(trip.status, BusinessTripStatus.SUBMITTED)

    def test_return_sends_it_back_to_draft(self):
        trip, _ = self.submitted()

        BusinessTripService.decide(
            trip=trip,
            decision="return",
            user=self.manager.user,
            notes="Lengkapi tujuan",
        )

        trip.refresh_from_db()

        self.assertEqual(trip.status, BusinessTripStatus.DRAFT)

    def test_withdraw_returns_to_draft(self):
        trip, workflow = self.submitted()

        BusinessTripService.withdraw(trip=trip, user=self.employee.user)

        trip.refresh_from_db()
        workflow.refresh_from_db()

        self.assertEqual(trip.status, BusinessTripStatus.DRAFT)
        self.assertEqual(workflow.status, InstanceStatus.CANCELLED)

    def test_withdraw_of_a_draft_is_rejected(self):
        trip = self.make_trip(self.employee)

        with self.assertRaises(ValidationError):
            BusinessTripService.withdraw(trip=trip)

    def test_decision_on_a_draft_is_rejected(self):
        trip = self.make_trip(self.employee)

        with self.assertRaises(ValidationError):
            BusinessTripService.decide(
                trip=trip,
                decision="approve",
                user=self.manager.user,
            )

    def test_workflow_context_carries_routing_keys(self):
        trip = self.make_trip(self.employee)

        context = BusinessTripService.workflow_context(trip)

        self.assertEqual(context["destination_type"], "internal_location")
        self.assertEqual(context["duration_days"], 5)
        self.assertEqual(context["employee_group_code"], "BT-OFFICE")


class BusinessTripImmutabilityTests(BusinessTripTestCase):
    def setUp(self):
        super().setUp()
        self.employee = self.make_employee()

    def test_approved_trip_cannot_be_edited(self):
        trip = self.approved_trip(self.employee)

        with self.assertRaises(ValidationError) as caught:
            BusinessTripService.update(
                instance=trip,
                data={"purpose": "Ganti tujuan diam-diam"},
            )

        self.assertIn("status", caught.exception.message_dict)

    def test_submitted_trip_cannot_be_edited(self):
        trip = self.set_status(
            self.make_trip(self.employee),
            BusinessTripStatus.SUBMITTED,
        )

        with self.assertRaises(ValidationError):
            BusinessTripService.update(instance=trip, data={"notes": "x"})

    def test_only_a_draft_can_be_deleted(self):
        trip = self.approved_trip(self.employee)

        with self.assertRaises(ValidationError):
            BusinessTripService.soft_delete(instance=trip)

        draft = self.make_trip(self.employee, start=FAR + timedelta(days=30))

        BusinessTripService.soft_delete(instance=draft)
        draft.refresh_from_db()

        self.assertTrue(draft.is_deleted)

    def test_legs_follow_the_trip_editability(self):
        from apps.hr.api.business_trip.services import BusinessTripLegService

        draft = self.make_trip(self.employee)

        leg = BusinessTripLegService.create(
            data={"trip": draft, "travel_start_date": FAR},
        )

        self.assertEqual(leg.trip_id, draft.pk)

        approved = self.set_status(draft, BusinessTripStatus.APPROVED)

        with self.assertRaises(ValidationError):
            BusinessTripLegService.create(
                data={
                    "trip": approved,
                    "travel_start_date": FAR,
                    "direction": "return",
                },
            )

        with self.assertRaises(ValidationError):
            BusinessTripLegService.update(
                instance=leg,
                data={"ticket_number": "GA-123"},
            )

    def test_replayed_approval_does_not_regress_a_departed_trip(self):
        trip = self.set_status(
            self.make_trip(self.employee),
            BusinessTripStatus.ON_TRIP,
        )

        BusinessTripService.on_workflow_done(
            trip=trip,
            status=InstanceStatus.APPROVED,
        )

        trip.refresh_from_db()

        self.assertEqual(trip.status, BusinessTripStatus.ON_TRIP)

    def test_replayed_approval_on_cancelled_is_ignored(self):
        trip = self.set_status(
            self.make_trip(self.employee),
            BusinessTripStatus.CANCELLED,
        )

        BusinessTripService.on_workflow_done(
            trip=trip,
            status=InstanceStatus.APPROVED,
        )

        trip.refresh_from_db()

        self.assertEqual(trip.status, BusinessTripStatus.CANCELLED)


class BusinessTripTravelPhaseTests(BusinessTripTestCase):
    """Berangkat, selesai, batal — relatif terhadap hari ini."""

    def setUp(self):
        super().setUp()

        self.employee = self.make_employee()

        # Kewenangan pembatalan diberikan eksplisit: di tenant test seed
        # izin role tidak dijalankan, jadi role bernama HR-ADMIN pun tidak
        # memegang izin apa pun dengan sendirinya.
        from django.contrib.auth.models import Permission

        from apps.accounts.models import Role

        canceller = Role.objects.create(
            code=f"BT-CANCEL-{self._counter}",
            name="Business Trip canceller",
        )
        canceller.permissions.set(
            Permission.objects.filter(
                content_type__app_label="hr",
                codename="cancel_businesstrip",
            ),
        )

        self.hr = self.make_employee()
        self.hr.user.roles.add(canceller)

    def running(self):
        """Disetujui, berangkat kemarin, pulang besok lusa."""
        return self.approved_trip(
            self.employee,
            start=self.today() - timedelta(days=1),
            days=4,
        )

    def upcoming(self):
        return self.approved_trip(
            self.employee,
            start=self.today() + timedelta(days=10),
        )

    def test_depart_before_the_date_is_rejected(self):
        with self.assertRaises(ValidationError):
            BusinessTripService.depart(trip=self.upcoming())

    def test_depart_marks_on_trip(self):
        trip = BusinessTripService.depart(trip=self.running())

        self.assertEqual(trip.status, BusinessTripStatus.ON_TRIP)
        self.assertIsNotNone(trip.departed_at)
        self.assertEqual(
            trip.actual_departure_datetime,
            trip.departure_datetime,
        )

    def test_depart_twice_is_rejected(self):
        trip = BusinessTripService.depart(trip=self.running())

        with self.assertRaises(ValidationError):
            BusinessTripService.depart(trip=trip)

    def test_early_return_keeps_the_plan(self):
        trip = BusinessTripService.depart(trip=self.running())
        planned = trip.return_datetime
        early = at(self.today(), 12)

        trip = BusinessTripService.complete(trip=trip, actual_return=early)

        self.assertEqual(trip.status, BusinessTripStatus.COMPLETED)
        self.assertEqual(trip.actual_return_datetime, early)
        self.assertEqual(trip.return_datetime, planned)

    def test_returning_later_than_planned_is_an_extension(self):
        trip = BusinessTripService.depart(trip=self.running())

        with self.assertRaises(ValidationError) as caught:
            BusinessTripService.complete(
                trip=trip,
                actual_return=trip.return_datetime + timedelta(days=1),
            )

        self.assertIn("actual_return_datetime", caught.exception.message_dict)

    def test_complete_from_approved_backfills_departure(self):
        trip = BusinessTripService.complete(
            trip=self.running(),
            actual_return=at(self.today(), 9),
        )

        self.assertEqual(trip.status, BusinessTripStatus.COMPLETED)
        self.assertIsNotNone(trip.departed_at)

    def test_employee_cancels_own_trip_before_departure(self):
        trip = BusinessTripService.cancel(
            trip=self.upcoming(),
            user=self.employee.user,
            reason="Rapat dibatalkan",
        )

        self.assertEqual(trip.status, BusinessTripStatus.CANCELLED)
        self.assertEqual(trip.cancelled_by_id, self.employee.user.pk)
        self.assertEqual(trip.cancellation_reason, "Rapat dibatalkan")
        self.assertIsNotNone(trip.cancelled_at)

    def test_employee_cannot_cancel_after_departure(self):
        trip = BusinessTripService.depart(trip=self.running())

        with self.assertRaises(ValidationError):
            BusinessTripService.cancel(
                trip=trip,
                user=self.employee.user,
                reason="Tidak jadi",
            )

    def test_cancel_permission_holder_cancels_after_departure(self):
        trip = BusinessTripService.depart(trip=self.running())

        trip = BusinessTripService.cancel(
            trip=trip,
            user=self.hr.user,
            reason="Perjalanan tidak terjadi",
        )

        self.assertEqual(trip.status, BusinessTripStatus.CANCELLED)

    def test_another_employee_cannot_cancel_without_permission(self):
        stranger = self.make_employee()

        with self.assertRaises(ValidationError):
            BusinessTripService.cancel(
                trip=self.upcoming(),
                user=stranger.user,
                reason="iseng",
            )

    def test_cancel_requires_a_reason(self):
        with self.assertRaises(ValidationError) as caught:
            BusinessTripService.cancel(
                trip=self.upcoming(),
                user=self.employee.user,
            )

        self.assertIn("cancellation_reason", caught.exception.message_dict)

    def test_cancel_twice_is_rejected(self):
        trip = BusinessTripService.cancel(
            trip=self.upcoming(),
            user=self.employee.user,
            reason="Batal",
        )

        with self.assertRaises(ValidationError):
            BusinessTripService.cancel(
                trip=trip,
                user=self.hr.user,
                reason="Batal lagi",
            )

    def test_draft_is_not_cancelled(self):
        with self.assertRaises(ValidationError):
            BusinessTripService.cancel(
                trip=self.make_trip(self.employee),
                user=self.hr.user,
                reason="x",
            )

    def test_advance_departed_is_idempotent(self):
        due = self.running()
        later = self.upcoming()

        self.assertEqual(BusinessTripService.advance_departed(), 1)
        self.assertEqual(BusinessTripService.advance_departed(), 0)

        due.refresh_from_db()
        later.refresh_from_db()

        self.assertEqual(due.status, BusinessTripStatus.ON_TRIP)
        self.assertEqual(later.status, BusinessTripStatus.APPROVED)


class BusinessTripLinkTests(BusinessTripTestCase):
    """Pengganti sebelum berangkat dan perpanjangan."""

    def setUp(self):
        super().setUp()

        self.manager = self.make_employee()
        self.hrga = self.make_employee(roles=["HRGA"])
        self.employee = self.make_employee(reports_to=self.manager)

    def test_replacement_requires_the_original_cancelled(self):
        original = self.approved_trip(self.employee)

        with self.assertRaises(ValidationError) as caught:
            self.make_trip(
                self.employee,
                start=FAR + timedelta(days=2),
                supersedes=original,
                supersede_type=BusinessTripLinkType.REPLACEMENT,
            )

        self.assertIn("supersedes", caught.exception.message_dict)

    def test_replacement_is_traceable_to_the_original(self):
        original = self.approved_trip(self.employee)

        BusinessTripService.cancel(
            trip=original,
            user=self.employee.user,
            reason="Jadwal bergeser dua hari",
        )

        replacement = self.make_trip(
            self.employee,
            start=FAR + timedelta(days=2),
            supersedes=original,
            supersede_type=BusinessTripLinkType.REPLACEMENT,
        )

        original.refresh_from_db()

        self.assertEqual(replacement.supersedes_id, original.pk)
        self.assertEqual(
            list(original.superseded_by.values_list("pk", flat=True)),
            [replacement.pk],
        )
        # Dokumen lama tidak disentuh selain statusnya.
        self.assertEqual(original.status, BusinessTripStatus.CANCELLED)
        self.assertEqual(original.departure_datetime, at(FAR, 7))

    def test_second_live_replacement_is_rejected(self):
        original = self.set_status(
            self.make_trip(self.employee),
            BusinessTripStatus.CANCELLED,
        )

        self.make_trip(
            self.employee,
            start=FAR + timedelta(days=2),
            supersedes=original,
            supersede_type=BusinessTripLinkType.REPLACEMENT,
        )

        with self.assertRaises(ValidationError):
            self.make_trip(
                self.employee,
                start=FAR + timedelta(days=20),
                supersedes=original,
                supersede_type=BusinessTripLinkType.REPLACEMENT,
            )

    def test_link_must_name_its_type(self):
        original = self.set_status(
            self.make_trip(self.employee),
            BusinessTripStatus.CANCELLED,
        )

        with self.assertRaises(ValidationError) as caught:
            self.make_trip(
                self.employee,
                start=FAR + timedelta(days=2),
                supersedes=original,
            )

        self.assertIn("supersede_type", caught.exception.message_dict)

    def test_link_to_another_employee_is_rejected(self):
        other = self.make_employee()
        original = self.set_status(
            self.make_trip(other),
            BusinessTripStatus.CANCELLED,
        )

        with self.assertRaises(ValidationError) as caught:
            self.make_trip(
                self.employee,
                supersedes=original,
                supersede_type=BusinessTripLinkType.REPLACEMENT,
            )

        self.assertIn("supersedes", caught.exception.message_dict)

    def test_extension_requires_an_approved_original(self):
        draft = self.make_trip(self.employee)

        with self.assertRaises(ValidationError):
            self.make_trip(
                self.employee,
                start=FAR + timedelta(days=5),
                supersedes=draft,
                supersede_type=BusinessTripLinkType.EXTENSION,
            )

    def test_extension_starting_on_the_last_day_overlaps(self):
        original = self.approved_trip(self.employee)
        last_day = FAR + timedelta(days=4)

        extension = self.make_trip(
            self.employee,
            start=last_day,
            days=3,
            supersedes=original,
            supersede_type=BusinessTripLinkType.EXTENSION,
        )

        with self.assertRaises(ValidationError) as caught:
            BusinessTripService.submit(trip=extension)

        self.assertIn("departure_datetime", caught.exception.message_dict)

    def test_extension_starting_the_next_day_is_accepted(self):
        original = self.approved_trip(self.employee)

        extension = self.make_trip(
            self.employee,
            start=FAR + timedelta(days=5),
            days=3,
            supersedes=original,
            supersede_type=BusinessTripLinkType.EXTENSION,
        )

        BusinessTripService.submit(trip=extension, user=self.employee.user)
        extension.refresh_from_db()

        self.assertEqual(extension.status, BusinessTripStatus.SUBMITTED)
        self.assertEqual(extension.supersedes_id, original.pk)
        self.assertEqual(
            extension.supersede_type,
            BusinessTripLinkType.EXTENSION,
        )

    def test_linkage_survives_as_a_chain(self):
        original = self.approved_trip(self.employee)

        extension = self.make_trip(
            self.employee,
            start=FAR + timedelta(days=5),
            supersedes=original,
            supersede_type=BusinessTripLinkType.EXTENSION,
        )

        self.assertEqual(
            BusinessTrip.objects.get(pk=extension.pk).supersedes.pk,
            original.pk,
        )
