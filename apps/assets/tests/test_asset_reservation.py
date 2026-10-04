"""
ASSET-4 — authority pemesanan bersama (`AssetOperationReservation`).

Yang dikunci:

* satu aset, paling banyak satu pemesanan terbuka — lintas jenis dokumen,
  dijaga database;
* identitas dokumen `(operation_type, document_id)` divalidasi service;
  jenis tanpa dokumen terdaftar ditolak;
* Assignment memakai authority ini dengan lifecycle ASSET-3 yang sama:
  DRAFT tidak memesan; SUBMITTED/APPROVED memesan; reject, cancel,
  dikembalikan ke DRAFT, dan complete melepas — tanpa pemesanan yatim;
* Assignment, Return, dan Transfer (ASSET-5) saling mengecualikan;
* migration memindahkan Assignment yang sedang berjalan ke tabel baru.
"""

from __future__ import annotations

import importlib

from django.apps import apps as django_apps
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.assets.models import (
    AssetAssignment,
    AssetOperationReservation,
    AssetOperationType,
    AssignmentStatus,
    CustodyType,
    ReservationRelease,
    ReturnStatus,
)
from apps.assets.services import (
    AssetAssignmentService,
    AssetReservationService,
    AssetReturnService,
    AssetTransferService,
)

from .base import AssetsTestCase


ASSIGNMENT = AssetOperationType.ASSIGNMENT
RETURN = AssetOperationType.RETURN
TRANSFER = AssetOperationType.TRANSFER


class ReservationTestCase(AssetsTestCase):
    @classmethod
    def draft_assignment(cls, asset, employee=None):
        return AssetAssignmentService.create(data={
            "asset": asset,
            "target_custody_type": CustodyType.EMPLOYEE,
            "employee": employee or cls.make_employee(),
            "location": cls.loc_a1,
        })

    @staticmethod
    def active(asset):
        return AssetOperationReservation.objects.filter(
            asset=asset,
            released_at__isnull=True,
        )

    def assert_clean(self):
        self.assertEqual(AssetReservationService.integrity_issues(), [])


# ======================================================================
# Authority
# ======================================================================


class ReservationAuthorityTests(ReservationTestCase):
    def test_database_allows_one_active_reservation_per_asset_across_types(self):
        asset = self.make_active_asset()

        AssetOperationReservation.objects.create(
            asset=asset,
            operation_type=ASSIGNMENT,
            document_id=1,
            reserved_at=timezone.now(),
        )

        for operation_type, document_id in (
            (RETURN, 2),
            (TRANSFER, 3),
            (ASSIGNMENT, 4),
        ):
            with self.subTest(operation_type=operation_type):
                with self.assertRaises(IntegrityError):
                    with transaction.atomic():
                        AssetOperationReservation.objects.create(
                            asset=asset,
                            operation_type=operation_type,
                            document_id=document_id,
                            reserved_at=timezone.now(),
                        )

    def test_released_reservations_do_not_block_and_stay_as_history(self):
        asset = self.make_active_asset()
        now = timezone.now()

        for document_id in (1, 2, 3):
            AssetOperationReservation.objects.create(
                asset=asset,
                operation_type=ASSIGNMENT,
                document_id=document_id,
                reserved_at=now,
                released_at=now,
                release_reason=ReservationRelease.CANCELLED,
            )

        AssetOperationReservation.objects.create(
            asset=asset,
            operation_type=RETURN,
            document_id=4,
            reserved_at=now,
        )

        self.assertEqual(
            AssetOperationReservation.objects.filter(asset=asset).count(),
            4,
        )
        self.assertEqual(self.active(asset).count(), 1)

    def test_database_enforces_document_identity_and_release_shape(self):
        first = self.make_active_asset()
        second = self.make_active_asset()
        now = timezone.now()

        AssetOperationReservation.objects.create(
            asset=first,
            operation_type=RETURN,
            document_id=77,
            reserved_at=now,
        )

        bad_rows = [
            # Satu dokumen, dua pemesanan terbuka.
            {"asset": second, "operation_type": RETURN, "document_id": 77},
            # Jenis di luar kosakata.
            {"asset": second, "operation_type": "MAINTENANCE", "document_id": 1},
            # Dilepas tanpa alasan.
            {
                "asset": second,
                "operation_type": ASSIGNMENT,
                "document_id": 2,
                "released_at": now,
            },
            # Alasan tanpa dilepas.
            {
                "asset": second,
                "operation_type": ASSIGNMENT,
                "document_id": 3,
                "release_reason": ReservationRelease.COMPLETED,
            },
        ]

        for row in bad_rows:
            with self.subTest(row=row):
                with self.assertRaises(IntegrityError):
                    with transaction.atomic():
                        AssetOperationReservation.objects.create(
                            reserved_at=now,
                            **row,
                        )

    def test_document_identity_is_validated_by_the_service(self):
        asset = self.make_active_asset()
        other = self.make_active_asset()
        assignment = self.draft_assignment(asset)

        # Dokumen ada, tapi untuk aset lain.
        with self.assertRaises(ValidationError):
            AssetReservationService.acquire(
                asset_id=other.pk,
                operation_type=ASSIGNMENT,
                document_id=assignment.pk,
            )

        # Dokumen tidak ada.
        with self.assertRaises(ValidationError):
            AssetReservationService.acquire(
                asset_id=asset.pk,
                operation_type=ASSIGNMENT,
                document_id=999_999_999,
            )

        # Transfer yang tidak ada.
        with self.assertRaises(ValidationError):
            AssetReservationService.acquire(
                asset_id=asset.pk,
                operation_type=TRANSFER,
                document_id=999_999_999,
            )

        # Dokumen yang sudah dihapus tidak bisa memesan.
        AssetAssignmentService.soft_delete(instance=assignment)

        with self.assertRaises(ValidationError):
            AssetReservationService.acquire(
                asset_id=asset.pk,
                operation_type=ASSIGNMENT,
                document_id=assignment.pk,
            )

        self.assertFalse(self.active(asset).exists())

    def test_release_without_a_reservation_is_refused(self):
        assignment = self.draft_assignment(self.make_active_asset())

        with self.assertRaises(ValidationError):
            AssetReservationService.release(
                operation_type=ASSIGNMENT,
                document_id=assignment.pk,
                reason=ReservationRelease.CANCELLED,
            )

    def test_cross_type_reservations_exclude_each_other(self):
        """Assignment vs Transfer vs Return — siapa pun duluan memegang."""
        in_storage = self.make_active_asset()
        in_use = self.hand_over(self.make_active_asset())

        # Assignment memegang → Transfer STORAGE→STORAGE ditolak.
        assignment = self.draft_assignment(in_storage)
        relocation = self.make_transfer(
            in_storage,
            to=CustodyType.STORAGE,
            location=self.loc_a2,
        )
        AssetAssignmentService.submit(assignment=assignment)

        with self.assertRaises(ValidationError) as caught:
            AssetTransferService.submit(transfer=relocation)

        self.assertIn(
            assignment.document_number,
            str(caught.exception.message_dict["asset"]),
        )

        # Transfer memegang → Return ditolak dengan pesan yang menyebut
        # pemesannya.
        handover = self.make_transfer(in_use, target_employee=self.make_employee())
        asset_return = self.make_return(in_use)
        AssetTransferService.submit(transfer=handover)

        with self.assertRaises(ValidationError) as caught:
            AssetReturnService.submit(asset_return=asset_return)

        self.assertIn(
            f"Transfer {handover.document_number}",
            str(caught.exception.message_dict["asset"]),
        )

        asset_return.refresh_from_db()
        self.assertEqual(asset_return.status, ReturnStatus.DRAFT)

        # Transfer dibatalkan → Return boleh.
        AssetTransferService.cancel(transfer=handover)
        AssetReturnService.submit(asset_return=asset_return)

        self.assertEqual(self.active(in_use).get().operation_type, RETURN)
        self.assert_clean()

    def test_unregistered_operation_type_is_refused(self):
        from unittest import mock

        from apps.assets.services.operations.reservation import RESERVABLE_DOCUMENTS

        asset = self.make_active_asset()
        transfer = self.make_transfer(asset, to=CustodyType.STORAGE, location=self.loc_a2)

        registry = {
            name: document
            for name, document in RESERVABLE_DOCUMENTS.items()
            if name != TRANSFER
        }

        with mock.patch.dict(RESERVABLE_DOCUMENTS, registry, clear=True):
            with self.assertRaises(ValidationError):
                AssetReservationService.acquire(
                    asset_id=asset.pk,
                    operation_type=TRANSFER,
                    document_id=transfer.pk,
                )

        self.assertFalse(self.active(asset).exists())

    def test_integrity_issues_detect_orphans_and_missing_reservations(self):
        orphaned = self.draft_assignment(self.make_active_asset())
        missing = self.draft_assignment(self.make_active_asset())

        # Pemesanan untuk dokumen DRAFT = yatim.
        AssetOperationReservation.objects.create(
            asset_id=orphaned.asset_id,
            operation_type=ASSIGNMENT,
            document_id=orphaned.pk,
            reserved_at=timezone.now(),
        )
        # Dokumen berjalan tanpa pemesanan.
        AssetAssignment.objects.filter(pk=missing.pk).update(
            status=AssignmentStatus.SUBMITTED,
        )

        problems = {
            (issue["document"], issue["problem"])
            for issue in AssetReservationService.integrity_issues()
        }

        self.assertIn(
            (
                f"ASSIGNMENT#{orphaned.pk}",
                "pemesanan yatim: dokumennya tidak sedang berjalan",
            ),
            problems,
        )
        self.assertIn(
            (
                f"ASSIGNMENT#{missing.pk}",
                "dokumen berjalan tanpa pemesanan aktif",
            ),
            problems,
        )


# ======================================================================
# Regresi Assignment di atas authority bersama
# ======================================================================


class AssignmentReservationRegressionTests(ReservationTestCase):
    def test_draft_does_not_reserve(self):
        asset = self.make_active_asset()
        self.draft_assignment(asset)
        self.draft_assignment(asset)

        self.assertFalse(self.active(asset).exists())
        self.assert_clean()

    def test_submitted_and_approved_hold_one_reservation(self):
        approver = self.make_user()
        self.make_workflow(approver=approver)

        asset = self.make_active_asset()
        assignment = self.draft_assignment(asset)

        AssetAssignmentService.submit(assignment=assignment)
        assignment.refresh_from_db()
        self.assertEqual(assignment.status, AssignmentStatus.SUBMITTED)

        held = self.active(asset).get()
        self.assertEqual(
            (held.operation_type, held.document_id, held.document_number),
            (ASSIGNMENT, assignment.pk, assignment.document_number),
        )

        AssetAssignmentService.decide(assignment=assignment, approved=True, user=approver)
        assignment.refresh_from_db()
        self.assertEqual(assignment.status, AssignmentStatus.APPROVED)

        self.assertEqual(self.active(asset).get().pk, held.pk)
        self.assert_clean()

    def test_every_exit_releases_with_its_reason(self):
        from apps.workflow.models import InstanceStatus

        approver = self.make_user()
        self.make_workflow(approver=approver)

        asset = self.make_active_asset()

        rejected = self.draft_assignment(asset)
        AssetAssignmentService.submit(assignment=rejected)
        AssetAssignmentService.decide(assignment=rejected, approved=False, user=approver)

        cancelled = self.draft_assignment(asset)
        AssetAssignmentService.submit(assignment=cancelled)
        AssetAssignmentService.cancel(assignment=cancelled)

        sent_back = self.draft_assignment(asset)
        AssetAssignmentService.submit(assignment=sent_back)
        AssetAssignmentService.on_workflow_done(
            assignment=sent_back,
            status=InstanceStatus.RETURNED,
        )
        sent_back.refresh_from_db()
        self.assertEqual(sent_back.status, AssignmentStatus.DRAFT)

        completed = self.draft_assignment(asset)
        AssetAssignmentService.submit(assignment=completed)
        AssetAssignmentService.decide(assignment=completed, approved=True, user=approver)
        AssetAssignmentService.complete(assignment=completed)

        reasons = dict(
            AssetOperationReservation.objects
            .filter(asset=asset)
            .values_list("document_id", "release_reason")
        )

        self.assertEqual(reasons, {
            rejected.pk: ReservationRelease.REJECTED,
            cancelled.pk: ReservationRelease.CANCELLED,
            sent_back.pk: ReservationRelease.RETURNED_TO_DRAFT,
            completed.pk: ReservationRelease.COMPLETED,
        })
        self.assertFalse(self.active(asset).exists())
        self.assert_clean()

    def test_two_assignments_still_cannot_claim_one_asset(self):
        asset = self.make_active_asset()
        first = self.draft_assignment(asset)
        second = self.draft_assignment(asset)

        AssetAssignmentService.submit(assignment=first)

        with self.assertRaises(ValidationError) as caught:
            AssetAssignmentService.submit(assignment=second)

        self.assertIn(first.document_number, str(caught.exception.message_dict["asset"]))

        second.refresh_from_db()
        self.assertEqual(second.status, AssignmentStatus.DRAFT)
        self.assertEqual(self.active(asset).count(), 1)

    def test_complete_requires_holding_the_reservation(self):
        asset = self.make_active_asset()
        assignment = self.draft_assignment(asset)
        AssetAssignmentService.submit(assignment=assignment)

        # Pemesanan hilang di luar jalur (kerusakan data) — complete
        # menolak, bukan memindahkan custody tanpa pemesanan.
        AssetOperationReservation.objects.filter(asset=asset).update(
            released_at=timezone.now(),
            release_reason=ReservationRelease.CANCELLED,
        )

        with self.assertRaises(ValidationError):
            AssetAssignmentService.complete(assignment=assignment)

        asset.refresh_from_db()
        self.assertEqual(asset.current_custody.custody_type, CustodyType.STORAGE)


# ======================================================================
# Migration
# ======================================================================


class ReservationMigrationTests(ReservationTestCase):
    def test_backfill_moves_inflight_assignments(self):
        migration = importlib.import_module(
            "apps.assets.migrations.0004_asset_return_reservation",
        )

        inflight = self.draft_assignment(self.make_active_asset())
        AssetAssignmentService.submit(assignment=inflight)
        draft = self.draft_assignment(self.make_active_asset())

        # Keadaan sebelum 0004: dokumen berjalan tanpa baris pemesanan.
        AssetOperationReservation.objects.all().delete()

        migration.move_inflight_assignments(django_apps, None)

        row = AssetOperationReservation.objects.get(
            operation_type=ASSIGNMENT,
            document_id=inflight.pk,
        )

        self.assertEqual(row.asset_id, inflight.asset_id)
        self.assertIsNone(row.released_at)
        self.assertFalse(
            AssetOperationReservation.objects.filter(document_id=draft.pk).exists(),
        )
        self.assert_clean()

    def test_old_assignment_only_constraint_is_gone(self):
        names = {
            constraint.name
            for constraint in AssetAssignment._meta.constraints
        }

        self.assertNotIn("uniq_inflight_assets_assignment_asset", names)

        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT indexname FROM pg_indexes WHERE schemaname = %s "
                "AND indexname = 'uniq_inflight_assets_assignment_asset'",
                [connection.schema_name],
            )
            self.assertIsNone(cursor.fetchone())
