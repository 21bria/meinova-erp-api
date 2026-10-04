"""
ASSET-4 — Asset Return (EMPLOYEE / ORGANIZATION → STORAGE).

Kontraknya `docs/claude/assets.md` §11, §16–§18, §26. Yang dikunci:

* asal dibaca ulang dari custody terbuka — bukan dari klien, bukan dari
  objek basi; aset STORAGE tidak bisa di-Return;
* tujuan = penyimpanan milik company pemilik (lokasi sama atau lain);
* custody hanya berpindah saat `complete`; draft/submit/approve tidak;
* kondisi kembali wajib dan selalu masuk riwayat (RETURN); DAMAGED/
  UNSERVICEABLE tetap kembali ke STORAGE tanpa efek samping, lalu tidak
  ditawarkan/diterima Assignment sampai kondisinya dicatat layak;
* pemesanan lewat authority bersama, dilepas di setiap jalan keluar;
* cakupan = sisi asal ∪ sisi tujuan; `complete` hanya sisi tujuan.
"""

from __future__ import annotations

import json

from datetime import timedelta

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import override_settings
from django.utils import timezone
from django_tenants.test.client import TenantClient
from apps.accounts.jwt import TenantRefreshToken as RefreshToken

from apps.assets.models import (
    AssetAssignment,
    AssetCondition,
    AssetConditionLog,
    AssetCustody,
    AssetOperationReservation,
    AssetOperationType,
    AssetReturn,
    AssetStatus,
    ConditionSource,
    CustodyType,
    ReservationRelease,
    ReturnReason,
    ReturnStatus,
)
from apps.assets.services import (
    AssetAssignmentService,
    AssetCustodyService,
    AssetReservationService,
    AssetReturnService,
    AssetService,
)

from .base import AssetsTestCase


ENDPOINT = "/api/assets/returns/"
IN_USE = "/api/assets/lookup/assets-in-use/"
AVAILABLE = "/api/assets/lookup/available-assets/"

EMPLOYEE = CustodyType.EMPLOYEE
ORGANIZATION = CustodyType.ORGANIZATION
STORAGE = CustodyType.STORAGE


class ReturnTestCase(AssetsTestCase):
    @classmethod
    def build_baseline(cls):
        super().build_baseline()

        # Lokasi ketiga company A — untuk cakupan "bukan asal, bukan tujuan".
        cls.loc_a3 = cls._location(cls.company_a, "AST-A-THIRD", "A Third Site")

    @staticmethod
    def open_custody(asset):
        return AssetCustody.objects.get(
            asset=asset,
            ended_on__isnull=True,
            is_deleted=False,
        )

    @staticmethod
    def run_through(asset_return, condition=AssetCondition.GOOD, **kwargs):
        """Tanpa alur yang cocok: submit → APPROVED, lalu complete."""
        AssetReturnService.submit(asset_return=asset_return)

        return AssetReturnService.complete(
            asset_return=asset_return,
            condition=condition,
            **kwargs,
        )

    @staticmethod
    def reservation_of(asset):
        return (
            AssetOperationReservation.objects
            .filter(asset=asset, released_at__isnull=True)
            .first()
        )

    def assert_invariants(self):
        self.assertEqual(AssetCustodyService.integrity_issues(), [])
        self.assertEqual(AssetReservationService.integrity_issues(), [])


# ======================================================================
# Employee Return
# ======================================================================


class EmployeeReturnTests(ReturnTestCase):
    def test_employee_laptop_returns_to_storage(self):
        employee = self.make_employee()
        asset = self.hand_over(self.make_active_asset(), employee)
        held = asset.current_custody

        asset_return = self.make_return(asset)

        # Asal dari custody, bukan dari klien.
        self.assertEqual(asset_return.source_custody, held)
        self.assertEqual(asset_return.source_custody_type, EMPLOYEE)
        self.assertEqual(asset_return.source_employee, employee)
        self.assertIsNone(asset_return.source_department)
        self.assertEqual(asset_return.source_location, held.location)
        self.assertEqual(asset_return.company, self.company_a)
        self.assertTrue(asset_return.document_number.startswith("ART"))

        self.run_through(asset_return, note="kembali utuh")

        asset_return.refresh_from_db()
        asset.refresh_from_db()
        held.refresh_from_db()

        storage = self.open_custody(asset)

        self.assertEqual(asset_return.status, ReturnStatus.COMPLETED)
        self.assertEqual(asset_return.resulting_custody, storage)
        self.assertEqual(asset_return.return_date, timezone.localdate())
        self.assertEqual(asset_return.return_condition, AssetCondition.GOOD)

        self.assertEqual(storage.custody_type, STORAGE)
        self.assertIsNone(storage.employee)
        self.assertEqual(storage.opened_by_type, "asset_return")
        self.assertEqual(storage.opened_by_id, str(asset_return.pk))

        self.assertIsNotNone(held.ended_on)
        self.assertEqual(held.closed_by_type, "asset_return")

        self.assertEqual(asset.current_custody, storage)
        self.assertEqual(asset.status, AssetStatus.ACTIVE)
        self.assertEqual(asset.company, self.company_a)

        self.assertIsNone(self.reservation_of(asset))
        self.assert_invariants()

    def test_employee_keeps_other_assets(self):
        employee = self.make_employee()
        laptop = self.hand_over(self.make_active_asset(), employee)
        radio = self.hand_over(self.make_active_asset(), employee)

        self.run_through(self.make_return(laptop))

        self.assertEqual(self.open_custody(laptop).custody_type, STORAGE)

        still_held = self.open_custody(radio)
        self.assertEqual(still_held.custody_type, EMPLOYEE)
        self.assertEqual(still_held.employee, employee)

    def test_cross_company_holder_returns_to_owner_storage(self):
        outsider = self.make_employee(company=self.company_b)
        asset = self.hand_over(
            self.make_active_asset(),
            outsider,
            cross_company_reason="Pinjam holding",
        )

        with self.assertRaises(ValidationError) as caught:
            self.make_return(asset, destination=self.loc_b1)

        self.assertIn("destination_location", caught.exception.message_dict)

        self.run_through(self.make_return(asset, reason=ReturnReason.SEPARATION))

        storage = self.open_custody(asset)
        self.assertEqual(storage.company, self.company_a)
        self.assertEqual(storage.location, self.loc_a1)

    def test_return_to_another_storage_location_syncs_asset_copy(self):
        asset = self.hand_over(self.make_active_asset())

        self.run_through(self.make_return(
            asset,
            destination=self.loc_a2,
            destination_facility=self.fac_a2,
        ))

        asset.refresh_from_db()
        storage = self.open_custody(asset)

        self.assertEqual(
            (storage.location, storage.facility),
            (self.loc_a2, self.fac_a2),
        )
        self.assertEqual(
            (asset.location, asset.facility),
            (self.loc_a2, self.fac_a2),
        )
        self.assert_invariants()


# ======================================================================
# Organizational Return
# ======================================================================


class OrganizationReturnTests(ReturnTestCase):
    def test_department_vehicle_returns_with_pic_snapshot(self):
        vehicles = self.make_category(allow_employee_custody=False)
        pic = self.make_employee()
        asset = self.hand_to_department(
            self.make_active_asset(category=vehicles),
            self.dept_a_mining,
            pic=pic,
            location=self.loc_a2,
        )

        asset_return = self.make_return(asset)

        self.assertEqual(asset_return.source_custody_type, ORGANIZATION)
        self.assertEqual(asset_return.source_department, self.dept_a_mining)
        self.assertEqual(asset_return.source_pic_employee, pic)
        self.assertIsNone(asset_return.source_employee)
        self.assertEqual(asset_return.source_location, self.loc_a2)

        self.run_through(asset_return)

        storage = self.open_custody(asset)
        self.assertEqual(storage.custody_type, STORAGE)
        self.assertIsNone(storage.department)
        self.assertIsNone(storage.pic_employee)

        # PIC sudah tidak memegang apa pun lewat aset ini; riwayatnya tetap.
        self.assertTrue(
            AssetCustody.objects.filter(
                asset=asset,
                pic_employee=pic,
                ended_on__isnull=False,
            ).exists(),
        )

    def test_return_without_pic_and_no_daily_driver_concept(self):
        vehicles = self.make_category(allow_employee_custody=False)
        asset = self.hand_to_department(
            self.make_active_asset(category=vehicles),
            self.dept_a_it,
        )

        asset_return = self.make_return(asset)
        self.assertIsNone(asset_return.source_pic_employee)

        # Sopir/pemakai harian bukan custody — tidak ada kolomnya.
        names = {field.name for field in AssetReturn._meta.get_fields()}
        self.assertFalse({n for n in names if "driver" in n or "operator" in n})

        self.run_through(asset_return)
        self.assertEqual(self.open_custody(asset).custody_type, STORAGE)


# ======================================================================
# Asal dan tujuan yang tidak sah
# ======================================================================


class InvalidReturnTests(ReturnTestCase):
    def test_storage_asset_cannot_be_returned(self):
        with self.assertRaises(ValidationError) as caught:
            self.make_return(self.make_active_asset())

        self.assertIn("asset", caught.exception.message_dict)

        with self.assertRaises(ValidationError):
            self.make_return(self.make_asset())  # DRAFT

    def test_source_cannot_be_supplied_by_the_client(self):
        asset = self.hand_over(self.make_active_asset())
        stranger = self.make_employee()

        for field, value in (
            ("source_employee", stranger),
            ("source_department", self.dept_a_it),
            ("source_location", self.loc_a2),
            ("source_custody_type", ORGANIZATION),
            ("status", ReturnStatus.APPROVED),
            ("return_condition", AssetCondition.GOOD),
        ):
            with self.subTest(field=field):
                with self.assertRaises(ValidationError) as caught:
                    self.make_return(asset, **{field: value})

                self.assertIn(field, caught.exception.message_dict)

    def test_stale_asset_object_does_not_leak_into_the_source(self):
        asset = self.make_active_asset()
        stale = type(asset).objects.get(pk=asset.pk)  # masih STORAGE di memori

        employee = self.make_employee()
        self.hand_over(asset, employee)

        asset_return = self.make_return(stale)
        self.assertEqual(asset_return.source_employee, employee)
        self.assertEqual(asset_return.source_custody_id, asset.current_custody_id)

    def test_stale_return_is_rejected(self):
        asset = self.hand_over(self.make_active_asset())

        winner = self.make_return(asset)
        stale = self.make_return(asset)

        self.run_through(winner)

        with self.assertRaises(ValidationError):
            AssetReturnService.submit(asset_return=stale)

        stale.refresh_from_db()
        self.assertEqual(stale.status, ReturnStatus.DRAFT)

        # Aset diserahkan lagi: draft lama tetap basi (custody lain).
        self.hand_over(asset)

        with self.assertRaises(ValidationError):
            AssetReturnService.submit(asset_return=stale)

    def test_destination_must_be_owner_storage(self):
        asset = self.hand_over(self.make_active_asset())

        with self.assertRaises(ValidationError) as caught:
            self.make_return(asset, destination=self.loc_b1)
        self.assertIn("destination_location", caught.exception.message_dict)

        with self.assertRaises(ValidationError) as caught:
            self.make_return(
                asset,
                destination=self.loc_a1,
                destination_facility=self.fac_a2,
            )
        self.assertIn("destination_facility", caught.exception.message_dict)

        draft = self.make_return(asset)

        with self.assertRaises(ValidationError):
            AssetReturnService.update(
                instance=draft,
                data={"destination_location": self.loc_b1},
            )

    def test_completed_return_is_immutable(self):
        done = self.run_through(self.make_return(self.hand_over(self.make_active_asset())))

        for attempt in (
            lambda: AssetReturnService.update(instance=done, data={"notes": "x"}),
            lambda: AssetReturnService.soft_delete(instance=done),
            lambda: AssetReturnService.complete(
                asset_return=done,
                condition=AssetCondition.GOOD,
            ),
            lambda: AssetReturnService.cancel(asset_return=done),
        ):
            with self.assertRaises(ValidationError):
                attempt()

        done.refresh_from_db()
        self.assertEqual(done.status, ReturnStatus.COMPLETED)
        self.assertFalse(done.is_deleted)

    def test_database_enforces_return_shapes(self):
        asset = self.hand_over(self.make_active_asset())
        asset_return = self.make_return(asset)

        for change in (
            {"source_employee": None},
            {"source_department": self.dept_a_it},
            {"source_custody_type": ORGANIZATION},
            {"status": ReturnStatus.COMPLETED},
        ):
            with self.subTest(change=change):
                with self.assertRaises(IntegrityError):
                    with transaction.atomic():
                        AssetReturn.objects.filter(pk=asset_return.pk).update(**change)


# ======================================================================
# Workflow
# ======================================================================


class ReturnWorkflowTests(ReturnTestCase):
    def test_only_complete_moves_custody(self):
        approver = self.make_user()
        self.make_workflow(approver=approver, document_type="asset_return")

        asset = self.hand_over(self.make_active_asset())
        held = asset.current_custody_id

        asset_return = self.make_return(asset)
        self.assertEqual(self.open_custody(asset).pk, held)
        self.assertIsNone(self.reservation_of(asset))

        AssetReturnService.submit(asset_return=asset_return)
        asset_return.refresh_from_db()
        self.assertEqual(asset_return.status, ReturnStatus.SUBMITTED)
        self.assertEqual(self.open_custody(asset).pk, held)
        self.assertEqual(self.reservation_of(asset).operation_type, AssetOperationType.RETURN)

        AssetReturnService.decide(asset_return=asset_return, approved=True, user=approver)
        asset_return.refresh_from_db()
        self.assertEqual(asset_return.status, ReturnStatus.APPROVED)
        self.assertEqual(self.open_custody(asset).pk, held)
        self.assertIsNotNone(self.reservation_of(asset))

        AssetReturnService.complete(
            asset_return=asset_return,
            condition=AssetCondition.FAIR,
        )

        self.assertEqual(self.open_custody(asset).custody_type, STORAGE)
        self.assertIsNone(self.reservation_of(asset))
        self.assert_invariants()

    def test_holder_is_not_an_approver(self):
        approver = self.make_user()
        self.make_workflow(approver=approver, document_type="asset_return")

        holder_user = self.make_user()
        holder = self.make_employee(user=holder_user)
        asset_return = self.make_return(self.hand_over(self.make_active_asset(), holder))
        AssetReturnService.submit(asset_return=asset_return)

        with self.assertRaises((ValidationError, PermissionDenied)):
            AssetReturnService.decide(
                asset_return=asset_return,
                approved=True,
                user=holder_user,
            )

        asset_return.refresh_from_db()
        self.assertEqual(asset_return.status, ReturnStatus.SUBMITTED)

    def test_reject_cancel_and_send_back_release_the_reservation(self):
        from apps.workflow.models import InstanceStatus

        approver = self.make_user()
        self.make_workflow(approver=approver, document_type="asset_return")

        asset = self.hand_over(self.make_active_asset())

        rejected = self.make_return(asset)
        AssetReturnService.submit(asset_return=rejected)
        AssetReturnService.decide(asset_return=rejected, approved=False, user=approver)
        rejected.refresh_from_db()
        self.assertEqual(rejected.status, ReturnStatus.REJECTED)
        self.assertIsNone(self.reservation_of(asset))

        cancelled = self.make_return(asset)
        AssetReturnService.submit(asset_return=cancelled)
        AssetReturnService.cancel(asset_return=cancelled, notes="batal")
        cancelled.refresh_from_db()
        self.assertEqual(cancelled.status, ReturnStatus.CANCELLED)
        self.assertIsNone(self.reservation_of(asset))

        sent_back = self.make_return(asset)
        AssetReturnService.submit(asset_return=sent_back)
        AssetReturnService.on_workflow_done(
            asset_return=sent_back,
            status=InstanceStatus.RETURNED,
        )
        sent_back.refresh_from_db()
        self.assertEqual(sent_back.status, ReturnStatus.DRAFT)
        self.assertIsNone(self.reservation_of(asset))

        self.assertEqual(
            set(
                AssetOperationReservation.objects
                .filter(asset=asset, operation_type=AssetOperationType.RETURN)
                .values_list("release_reason", flat=True)
            ),
            {
                ReservationRelease.REJECTED,
                ReservationRelease.CANCELLED,
                ReservationRelease.RETURNED_TO_DRAFT,
            },
        )

        # Custody tidak pernah bergerak; dokumen berikutnya bisa berjalan.
        self.assertEqual(self.open_custody(asset).custody_type, EMPLOYEE)

        last = self.make_return(asset)
        AssetReturnService.submit(asset_return=last)
        AssetReturnService.decide(asset_return=last, approved=True, user=approver)
        AssetReturnService.complete(asset_return=last, condition=AssetCondition.GOOD)

        self.assertEqual(self.open_custody(asset).custody_type, STORAGE)
        self.assert_invariants()

    def test_two_returns_cannot_claim_one_asset(self):
        asset = self.hand_over(self.make_active_asset())
        first = self.make_return(asset)
        second = self.make_return(asset)

        AssetReturnService.submit(asset_return=first)

        with self.assertRaises(ValidationError) as caught:
            AssetReturnService.submit(asset_return=second)

        self.assertIn(first.document_number, str(caught.exception.message_dict["asset"]))

    def test_cancel_only_applies_to_running_documents(self):
        draft = self.make_return(self.hand_over(self.make_active_asset()))

        with self.assertRaises(ValidationError):
            AssetReturnService.cancel(asset_return=draft)

    def test_submitted_return_cannot_be_edited_or_deleted(self):
        asset_return = self.make_return(self.hand_over(self.make_active_asset()))
        AssetReturnService.submit(asset_return=asset_return)
        asset_return.refresh_from_db()

        with self.assertRaises(ValidationError):
            AssetReturnService.update(instance=asset_return, data={"notes": "x"})

        with self.assertRaises(ValidationError):
            AssetReturnService.soft_delete(instance=asset_return)

    def test_draft_can_be_edited_and_deleted(self):
        asset_return = self.make_return(self.hand_over(self.make_active_asset()))

        AssetReturnService.update(
            instance=asset_return,
            data={"destination_location": self.loc_a2, "reason": ReturnReason.DAMAGE},
        )
        asset_return.refresh_from_db()
        self.assertEqual(asset_return.destination_location, self.loc_a2)

        AssetReturnService.soft_delete(instance=asset_return)
        asset_return.refresh_from_db()
        self.assertTrue(asset_return.is_deleted)

    def test_completion_needs_condition_and_a_valid_date(self):
        asset_return = self.make_return(self.hand_over(self.make_active_asset()))
        AssetReturnService.submit(asset_return=asset_return)

        for kwargs, field in (
            ({"condition": ""}, "condition"),
            ({"condition": "BROKEN"}, "condition"),
            (
                {
                    "condition": AssetCondition.GOOD,
                    "return_date": timezone.localdate() + timedelta(days=1),
                },
                "return_date",
            ),
            (
                {
                    "condition": AssetCondition.GOOD,
                    "return_date": timezone.localdate() - timedelta(days=1),
                },
                "return_date",
            ),
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValidationError) as caught:
                    AssetReturnService.complete(asset_return=asset_return, **kwargs)

                self.assertIn(field, caught.exception.message_dict)

        asset_return.refresh_from_db()
        self.assertEqual(asset_return.status, ReturnStatus.APPROVED)

    def test_service_checks_workflow_action_permissions(self):
        nobody = self.make_user()
        asset_return = self.make_return(self.hand_over(self.make_active_asset()))

        with self.assertRaises(PermissionDenied):
            AssetReturnService.submit(asset_return=asset_return, user=nobody)

        submitter = self.make_user(permissions=("submit_assetreturn",))
        AssetReturnService.submit(asset_return=asset_return, user=submitter)

        with self.assertRaises(PermissionDenied):
            AssetReturnService.complete(
                asset_return=asset_return,
                condition=AssetCondition.GOOD,
                user=submitter,
            )

        with self.assertRaises(PermissionDenied):
            AssetReturnService.cancel(asset_return=asset_return, user=submitter)

        receiver = self.make_user(permissions=("complete_assetreturn",))
        AssetReturnService.complete(
            asset_return=asset_return,
            condition=AssetCondition.GOOD,
            user=receiver,
        )

        asset_return.refresh_from_db()
        self.assertEqual(asset_return.completed_by, receiver)


# ======================================================================
# Kondisi
# ======================================================================


class ReturnConditionTests(ReturnTestCase):
    def returned(self, condition):
        asset = self.hand_over(self.make_active_asset())
        self.run_through(self.make_return(asset), condition=condition, note="cek")
        asset.refresh_from_db()

        return asset

    def test_good_return_is_still_recorded(self):
        asset = self.returned(AssetCondition.GOOD)

        log = AssetConditionLog.objects.get(asset=asset, source=ConditionSource.RETURN)

        self.assertEqual(
            (log.previous_condition, log.new_condition),
            (AssetCondition.GOOD, AssetCondition.GOOD),
        )
        self.assertEqual(asset.condition, AssetCondition.GOOD)

    def test_damaged_and_unserviceable_go_back_to_storage_without_side_effects(self):
        for condition in (AssetCondition.DAMAGED, AssetCondition.UNSERVICEABLE):
            with self.subTest(condition=condition):
                asset = self.returned(condition)

                storage = self.open_custody(asset)
                log = AssetConditionLog.objects.get(
                    asset=asset,
                    source=ConditionSource.RETURN,
                )

                self.assertEqual(asset.condition, condition)
                self.assertEqual(asset.status, AssetStatus.ACTIVE)
                self.assertEqual(storage.custody_type, STORAGE)
                self.assertEqual(storage.start_condition, condition)
                self.assertEqual(log.previous_condition, AssetCondition.GOOD)
                self.assertEqual(log.new_condition, condition)

                # Riwayat sebelumnya tidak ditimpa.
                self.assertEqual(
                    list(
                        AssetConditionLog.objects
                        .filter(asset=asset)
                        .order_by("id")
                        .values_list("source", flat=True)
                    ),
                    [ConditionSource.REGISTRATION, ConditionSource.RETURN],
                )

    def test_unfit_returned_asset_cannot_be_assigned_until_inspected(self):
        asset = self.returned(AssetCondition.DAMAGED)

        with self.assertRaises(ValidationError) as caught:
            AssetAssignmentService.create(data={
                "asset": asset,
                "target_custody_type": EMPLOYEE,
                "employee": self.make_employee(),
                "location": self.loc_a1,
            })

        self.assertIn("asset", caught.exception.message_dict)

        AssetService.record_condition(asset=asset, condition=AssetCondition.FAIR)

        assignment = AssetAssignmentService.create(data={
            "asset": asset,
            "target_custody_type": EMPLOYEE,
            "employee": self.make_employee(),
            "location": self.loc_a1,
        })
        AssetAssignmentService.submit(assignment=assignment)

    def test_condition_dropping_after_draft_blocks_submit(self):
        asset = self.make_active_asset()
        assignment = AssetAssignmentService.create(data={
            "asset": asset,
            "target_custody_type": EMPLOYEE,
            "employee": self.make_employee(),
            "location": self.loc_a1,
        })

        AssetService.record_condition(asset=asset, condition=AssetCondition.UNSERVICEABLE)

        with self.assertRaises(ValidationError):
            AssetAssignmentService.submit(assignment=assignment)

        assignment.refresh_from_db()
        self.assertEqual(assignment.status, "DRAFT")
        self.assertFalse(
            AssetOperationReservation.objects.filter(asset=asset).exists(),
        )


# ======================================================================
# Registrasi workflow
# ======================================================================


class ReturnWorkflowRegistrationTests(ReturnTestCase):
    def test_completion_handler_and_route_are_registered(self):
        from apps.assets import workflow_handlers
        from apps.workflow.registry import completion_handler, document_url

        self.assertIs(
            completion_handler(module="assets", document_type="asset_return"),
            workflow_handlers.asset_return_completed,
        )
        self.assertEqual(
            document_url(module="assets", document_type="asset_return", object_id=9),
            "/assets/returns/9",
        )

    def test_decision_from_the_generic_inbox_moves_the_document(self):
        from apps.workflow.registry import completion_handler
        from apps.workflow.services.workflow_service import WorkflowService

        approver = self.make_user()
        self.make_workflow(approver=approver, document_type="asset_return")

        asset_return = self.make_return(self.hand_over(self.make_active_asset()))
        workflow = AssetReturnService.submit(asset_return=asset_return)

        WorkflowService.approve(
            instance=workflow,
            user=approver,
            on_complete=completion_handler(
                module="assets",
                document_type="asset_return",
            ),
        )

        asset_return.refresh_from_db()
        self.assertEqual(asset_return.status, ReturnStatus.APPROVED)
        self.assertIsNotNone(self.reservation_of(asset_return.asset))


# ======================================================================
# API, cakupan, lookup
# ======================================================================


@override_settings(
    ENFORCE_MODEL_PERMISSIONS=True,
    ENFORCE_VIEW_PERMISSIONS=True,
)
class ReturnApiTests(ReturnTestCase):
    ALL = (
        "view_assetreturn",
        "add_assetreturn",
        "change_assetreturn",
        "delete_assetreturn",
        "submit_assetreturn",
        "complete_assetreturn",
        "cancel_assetreturn",
        "view_asset",
    )

    def setUp(self):
        super().setUp()

        self.http = TenantClient(self.tenant)

    def call(self, method, path, user, payload=None):
        token = RefreshToken.for_user(user).access_token

        kwargs = {"HTTP_AUTHORIZATION": f"Bearer {token}"}

        if payload is not None:
            kwargs["data"] = json.dumps(payload)
            kwargs["content_type"] = "application/json"

        return getattr(self.http, method)(path, **kwargs)

    @staticmethod
    def body(response):
        return json.loads(response.content) if response.content else None

    def ids(self, response) -> set[int]:
        self.assertEqual(response.status_code, 200, response.content[:500])

        return {row["id"] for row in self.body(response)["data"]}

    # ------------------------------------------------------------------

    def test_full_flow_through_the_api(self):
        clerk = self.make_user(permissions=self.ALL)
        employee = self.make_employee()
        asset = self.hand_over(self.make_active_asset(), employee)

        created = self.call("post", ENDPOINT, clerk, {
            "asset": asset.pk,
            "destination_location": self.loc_a1.pk,
            "reason": ReturnReason.END_OF_USE,
            # Diabaikan: read-only.
            "status": ReturnStatus.COMPLETED,
            "company": self.company_b.pk,
            "source_employee": self.make_employee().pk,
        })
        self.assertEqual(created.status_code, 201, created.content[:500])

        asset_return = AssetReturn.objects.get(asset=asset, is_deleted=False)
        self.assertEqual(asset_return.status, ReturnStatus.DRAFT)
        self.assertEqual(asset_return.company, self.company_a)
        self.assertEqual(asset_return.source_employee, employee)

        submitted = self.call("post", f"{ENDPOINT}{asset_return.pk}/submit/", clerk, {})
        self.assertEqual(submitted.status_code, 200, submitted.content[:500])
        self.assertEqual(self.body(submitted)["data"]["status"], ReturnStatus.APPROVED)

        edited = self.call("patch", f"{ENDPOINT}{asset_return.pk}/", clerk, {"notes": "x"})
        self.assertEqual(edited.status_code, 400)

        missing = self.call("post", f"{ENDPOINT}{asset_return.pk}/complete/", clerk, {})
        self.assertEqual(missing.status_code, 400)

        completed = self.call(
            "post",
            f"{ENDPOINT}{asset_return.pk}/complete/",
            clerk,
            {"condition": AssetCondition.DAMAGED, "note": "layar retak"},
        )
        self.assertEqual(completed.status_code, 200, completed.content[:500])

        data = self.body(completed)["data"]
        self.assertEqual(data["status"], ReturnStatus.COMPLETED)
        self.assertEqual(data["return_condition"], AssetCondition.DAMAGED)

        self.assertEqual(self.open_custody(asset).custody_type, STORAGE)

        deleted = self.call("delete", f"{ENDPOINT}{asset_return.pk}/", clerk)
        self.assertEqual(deleted.status_code, 400)

    def test_no_public_custody_or_reservation_endpoints(self):
        from django.urls import Resolver404, resolve

        for path in (
            "/api/assets/custodies/",
            "/api/assets/reservations/",
            "/api/assets/operation-reservations/",
        ):
            with self.subTest(path=path):
                with self.assertRaises(Resolver404):
                    resolve(path)

    def test_workflow_actions_need_their_own_permissions(self):
        drafter = self.make_user(permissions=(
            "view_assetreturn",
            "add_assetreturn",
            "change_assetreturn",
        ))
        asset_return = self.make_return(self.hand_over(self.make_active_asset()))

        submitted = self.call("post", f"{ENDPOINT}{asset_return.pk}/submit/", drafter, {})
        self.assertIn(submitted.status_code, (403, 404))

        AssetReturnService.submit(asset_return=asset_return)

        completed = self.call(
            "post",
            f"{ENDPOINT}{asset_return.pk}/complete/",
            drafter,
            {"condition": AssetCondition.GOOD},
        )
        self.assertIn(completed.status_code, (403, 404))

        asset_return.refresh_from_db()
        self.assertEqual(asset_return.status, ReturnStatus.APPROVED)

    def test_scope_is_source_or_destination_and_complete_is_destination_only(self):
        # Dipakai di site A2, dikembalikan ke gudang HO A1.
        asset = self.hand_over(self.make_active_asset(), location=self.loc_a2)
        asset_return = self.make_return(asset, destination=self.loc_a1)
        AssetReturnService.submit(asset_return=asset_return)

        def admin(location):
            return self.make_user(
                permissions=self.ALL,
                authorities=[("location", location.pk)],
            )

        source_admin = admin(self.loc_a2)
        destination_admin = admin(self.loc_a1)
        third_admin = admin(self.loc_a3)

        listing = f"{ENDPOINT}?page_size=500"

        self.assertIn(asset_return.pk, self.ids(self.call("get", listing, source_admin)))
        self.assertIn(asset_return.pk, self.ids(self.call("get", listing, destination_admin)))
        self.assertNotIn(asset_return.pk, self.ids(self.call("get", listing, third_admin)))

        detail = f"{ENDPOINT}{asset_return.pk}/"
        self.assertEqual(self.call("get", detail, source_admin).status_code, 200)
        self.assertEqual(self.call("get", detail, third_admin).status_code, 404)

        # Barang diterima di gudang: hanya sisi tujuan.
        complete = f"{ENDPOINT}{asset_return.pk}/complete/"
        payload = {"condition": AssetCondition.GOOD}

        self.assertEqual(self.call("post", complete, source_admin, payload).status_code, 404)

        asset_return.refresh_from_db()
        self.assertEqual(asset_return.status, ReturnStatus.APPROVED)

        done = self.call("post", complete, destination_admin, payload)
        self.assertEqual(done.status_code, 200, done.content[:500])

        # Sesudah complete dokumen tetap terlihat di kedua sisi — scope
        # tidak mengikuti lokasi aset saat ini.
        self.assertIn(asset_return.pk, self.ids(self.call("get", listing, source_admin)))
        self.assertIn(asset_return.pk, self.ids(self.call("get", listing, destination_admin)))

    def test_cancel_is_allowed_from_either_side(self):
        asset = self.hand_over(self.make_active_asset(), location=self.loc_a2)
        asset_return = self.make_return(asset, destination=self.loc_a1)
        AssetReturnService.submit(asset_return=asset_return)

        source_admin = self.make_user(
            permissions=self.ALL,
            authorities=[("location", self.loc_a2.pk)],
        )

        cancelled = self.call(
            "post",
            f"{ENDPOINT}{asset_return.pk}/cancel/",
            source_admin,
            {"notes": "salah aset"},
        )
        self.assertEqual(cancelled.status_code, 200, cancelled.content[:500])
        self.assertIsNone(self.reservation_of(asset))

    def test_holder_gets_no_access_from_being_the_holder(self):
        holder_user = self.make_user()
        holder = self.make_employee(user=holder_user)
        self.make_return(self.hand_over(self.make_active_asset(), holder))

        self.assertEqual(self.call("get", ENDPOINT, holder_user).status_code, 403)

    def test_assets_in_use_lookup(self):
        viewer = self.make_user(permissions=("view_asset",))

        employee = self.make_employee()
        vehicles = self.make_category(allow_employee_custody=False)

        with_employee = self.hand_over(self.make_active_asset(), employee)
        with_department = self.hand_to_department(
            self.make_active_asset(category=vehicles),
            self.dept_a_mining,
        )
        in_storage = self.make_active_asset()
        being_returned = self.hand_over(self.make_active_asset())
        AssetReturnService.submit(asset_return=self.make_return(being_returned))
        draft = self.make_asset()
        damaged = self.hand_over(self.make_active_asset())
        AssetService.record_condition(asset=damaged, condition=AssetCondition.DAMAGED)

        def offered(params=""):
            response = self.call("get", f"{IN_USE}?page_size=1000{params}", viewer)
            self.assertEqual(response.status_code, 200, response.content[:500])

            return {row["value"] for row in self.body(response)["results"]}

        everything = offered()

        self.assertLessEqual({with_employee.pk, with_department.pk, damaged.pk}, everything)
        self.assertNotIn(in_storage.pk, everything)
        self.assertNotIn(being_returned.pk, everything)
        self.assertNotIn(draft.pk, everything)

        self.assertEqual(
            offered(f"&employee_id={employee.pk}") & {with_employee.pk, with_department.pk},
            {with_employee.pk},
        )
        self.assertEqual(
            offered(f"&department_id={self.dept_a_mining.pk}")
            & {with_employee.pk, with_department.pk},
            {with_department.pk},
        )

        by_type = offered(f"&custody_type={ORGANIZATION}")
        self.assertIn(with_department.pk, by_type)
        self.assertNotIn(with_employee.pk, by_type)

        # Tanpa izin baca aset, lookup tertutup: cakupan untuk
        # `view_asset` = denied → kosong (lookup tidak menjawab 403).
        outsider = self.make_user()
        response = self.call("get", f"{IN_USE}?page_size=1000", outsider)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.body(response)["results"], [])

    def test_available_assets_follow_the_condition_rule(self):
        viewer = self.make_user(permissions=("view_asset",))

        good = self.make_active_asset()
        fair = self.make_active_asset()
        AssetService.record_condition(asset=fair, condition=AssetCondition.FAIR)

        damaged = self.returned_as(AssetCondition.DAMAGED)
        unserviceable = self.returned_as(AssetCondition.UNSERVICEABLE)
        returned_good = self.returned_as(AssetCondition.GOOD)

        response = self.call("get", f"{AVAILABLE}?page_size=1000", viewer)
        self.assertEqual(response.status_code, 200, response.content[:500])
        offered = {row["value"] for row in self.body(response)["results"]}

        self.assertLessEqual({good.pk, fair.pk, returned_good.pk}, offered)
        self.assertNotIn(damaged.pk, offered)
        self.assertNotIn(unserviceable.pk, offered)

    def returned_as(self, condition):
        asset = self.hand_over(self.make_active_asset())
        self.run_through(self.make_return(asset), condition=condition)

        return asset

    def test_ui_schema_declares_return_actions(self):
        viewer = self.make_user(permissions=("view_assetreturn",))

        response = self.call("get", f"{ENDPOINT}ui-schema/", viewer)
        self.assertEqual(response.status_code, 200, response.content[:500])

        schema = self.body(response)
        schema = schema.get("data", schema)

        self.assertEqual(schema["endpoint"], ENDPOINT)
        self.assertLessEqual(
            {"submit", "approve", "reject", "complete", "cancel"},
            {item["key"] for item in schema.get("actions", [])},
        )
        self.assertFalse(
            set(schema["fields"]) & {"is_deleted", "deleted_at", "deleted_by"},
        )
        self.assertEqual(
            schema["fields"]["asset"]["lookup_endpoint"]
            if "lookup_endpoint" in schema["fields"]["asset"]
            else schema["fields"]["asset"].get("lookup", {}).get("endpoint"),
            IN_USE,
        )


# ======================================================================
# Batas modul
# ======================================================================


class ReturnBoundaryTests(ReturnTestCase):
    def test_return_does_not_touch_finance_or_scm(self):
        from apps.assets.services.operations import asset_return, reservation

        for module in (asset_return, reservation):
            source = open(module.__file__).read()

            with self.subTest(module=module.__name__):
                self.assertNotIn("apps.finance", source)
                self.assertNotIn("apps.scm", source)
                self.assertNotIn("AccountingEvent", source)

    def test_return_creates_no_assignment_or_accounting_rows(self):
        asset = self.hand_over(self.make_active_asset())
        before = AssetAssignment.objects.count()

        self.run_through(self.make_return(asset), condition=AssetCondition.UNSERVICEABLE)

        self.assertEqual(AssetAssignment.objects.count(), before)
