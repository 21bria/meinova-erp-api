"""
ASSET-3 — Asset Assignment (STORAGE → EMPLOYEE / ORGANIZATION).

Kontraknya `docs/claude/assets.md` §9, §13–§16, §18, §26. Yang dikunci:

* custody hanya berpindah saat `complete` — draft, submit, dan approve
  tidak menyentuhnya;
* pemesanan mulai SUBMITTED, bertahan APPROVED, lepas saat
  reject/cancel/return; DRAFT tidak memesan;
* satu pegawai boleh memegang banyak aset; satu aset satu custody;
* pegawai lintas company boleh (O-8) — eksplisit, beralasan, kepemilikan
  dan lokasi tetap milik pemilik, penempatan pegawai tidak disentuh;
* penerima adalah subjek, bukan approver (O-4);
* dokumen COMPLETED tidak bisa diubah, dihapus, atau dibatalkan.
"""

from __future__ import annotations

import json

from datetime import timedelta
from unittest import mock

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
    AssetStatus,
    AssignmentStatus,
    ConditionSource,
    CustodyType,
)
from apps.assets.services import (
    AssetAssignmentService,
    AssetCategoryService,
    AssetCustodyService,
)
from apps.hr.models import OrganizationAssignment

from .base import AssetsTestCase


ENDPOINT = "/api/assets/assignments/"
AVAILABLE = "/api/assets/lookup/available-assets/"

EMPLOYEE = CustodyType.EMPLOYEE
ORGANIZATION = CustodyType.ORGANIZATION


class AssignmentTestCase(AssetsTestCase):
    @classmethod
    def assign(cls, asset, *, to=EMPLOYEE, location=None, user=None, **extra):
        data = {
            "asset": asset,
            "target_custody_type": to,
            "location": location or cls.loc_a1,
            **extra,
        }

        return AssetAssignmentService.create(data=data, user=user)

    @classmethod
    def to_employee(cls, asset, employee=None, **extra):
        return cls.assign(
            asset,
            employee=employee or cls.make_employee(),
            **extra,
        )

    @staticmethod
    def run_through(assignment, **complete_kwargs):
        """Tanpa alur yang cocok: submit → APPROVED, lalu complete."""
        AssetAssignmentService.submit(assignment=assignment)

        return AssetAssignmentService.complete(
            assignment=assignment,
            **complete_kwargs,
        )

    @staticmethod
    def open_custody(asset):
        return AssetCustody.objects.get(
            asset=asset,
            ended_on__isnull=True,
            is_deleted=False,
        )


# ======================================================================
# Kapabilitas kategori
# ======================================================================


class CategoryCustodyCapabilityTests(AssignmentTestCase):
    def test_category_must_allow_some_custody_kind(self):
        with self.assertRaises(ValidationError):
            AssetCategoryService.create(data={
                "code": self.next_code(),
                "name": "Nothing",
                "allow_employee_custody": False,
                "allow_organization_custody": False,
            })

    def test_target_kind_must_be_allowed_by_category(self):
        vehicles = self.make_category(allow_employee_custody=False)
        laptops = self.make_category(allow_organization_custody=False)

        with self.assertRaises(ValidationError) as caught:
            self.to_employee(self.make_active_asset(category=vehicles))

        self.assertIn("target_custody_type", caught.exception.message_dict)

        with self.assertRaises(ValidationError) as caught:
            self.assign(
                self.make_active_asset(category=laptops),
                to=ORGANIZATION,
                department=self.dept_a_mining,
            )

        self.assertIn("target_custody_type", caught.exception.message_dict)

        # Kategori yang mengizinkan keduanya (HT, GPS) menerima keduanya.
        both = self.make_category()
        self.to_employee(self.make_active_asset(category=both))
        self.assign(
            self.make_active_asset(category=both),
            to=ORGANIZATION,
            department=self.dept_a_mining,
        )


# ======================================================================
# Pegawai
# ======================================================================


class EmployeeAssignmentTests(AssignmentTestCase):
    def test_laptop_to_employee_moves_custody_only_on_complete(self):
        employee = self.make_employee(location=self.loc_a1, department=self.dept_a_it)
        placement = OrganizationAssignment.objects.get(employee=employee)
        asset = self.make_active_asset(location=self.loc_a1, facility=self.fac_a1)
        storage = asset.current_custody

        assignment = self.to_employee(asset, employee, location=self.loc_a2)

        self.assertEqual(assignment.status, AssignmentStatus.DRAFT)
        self.assertTrue(assignment.document_number.startswith("AAS-"))
        self.assertEqual(assignment.company, self.company_a)
        self.assertEqual(assignment.source_custody, storage)
        self.assertEqual(self.open_custody(asset), storage)

        AssetAssignmentService.submit(assignment=assignment)
        assignment.refresh_from_db()

        # Tanpa alur yang cocok: langsung APPROVED — dan custody tetap.
        self.assertEqual(assignment.status, AssignmentStatus.APPROVED)
        self.assertEqual(self.open_custody(asset), storage)

        AssetAssignmentService.complete(assignment=assignment)
        assignment.refresh_from_db()
        asset.refresh_from_db()
        storage.refresh_from_db()

        held = self.open_custody(asset)

        self.assertEqual(assignment.status, AssignmentStatus.COMPLETED)
        self.assertEqual(assignment.resulting_custody, held)
        self.assertEqual(assignment.handover_date, timezone.localdate())

        self.assertEqual(storage.ended_on, timezone.localdate())
        self.assertEqual(storage.closed_by_type, "asset_assignment")
        self.assertEqual(storage.closed_by_id, str(assignment.pk))

        self.assertEqual(held.custody_type, EMPLOYEE)
        self.assertEqual(held.employee, employee)
        self.assertIsNone(held.department)
        self.assertEqual(held.location, self.loc_a2)

        # Salinan aset mengikuti custody; pemilik tidak berubah.
        self.assertEqual(asset.status, AssetStatus.ACTIVE)
        self.assertEqual(asset.current_custody, held)
        self.assertEqual(asset.location, self.loc_a2)
        self.assertIsNone(asset.facility)
        self.assertEqual(asset.company, self.company_a)

        # O-2: barang di lokasi lain, penempatan pegawai tidak disentuh.
        placement_after = OrganizationAssignment.objects.get(employee=employee)
        self.assertEqual(placement_after.location, self.loc_a1)
        self.assertEqual(placement_after.updated_at, placement.updated_at)
        self.assertEqual(assignment.employee_location, self.loc_a1)
        self.assertEqual(assignment.employee_department, self.dept_a_it)

        # Kondisi tidak berubah diam-diam.
        self.assertFalse(
            AssetConditionLog.objects
            .filter(asset=asset, source=ConditionSource.HANDOVER)
            .exists(),
        )

        self.assertEqual(AssetCustodyService.integrity_issues(), [])

    def test_one_employee_holds_many_assets_at_once(self):
        surveyor = self.make_employee(location=self.loc_a2)

        assets = [self.make_active_asset() for _ in range(4)]

        for asset in assets:
            self.run_through(self.to_employee(asset, surveyor, location=self.loc_a2))

        held = AssetCustody.objects.filter(
            employee=surveyor,
            ended_on__isnull=True,
            is_deleted=False,
        )

        self.assertEqual(held.count(), 4)
        self.assertEqual({c.asset_id for c in held}, {a.pk for a in assets})

    def test_employee_needs_an_active_placement(self):
        unplaced = self.make_employee(placed=False)

        with self.assertRaises(ValidationError) as caught:
            self.to_employee(self.make_active_asset(), unplaced)

        self.assertIn("employee", caught.exception.message_dict)

        inactive = self.make_employee()
        inactive.is_active = False
        inactive.save(update_fields=["is_active"])

        with self.assertRaises(ValidationError):
            self.to_employee(self.make_active_asset(), inactive)

    def test_employee_target_does_not_take_organization_fields(self):
        with self.assertRaises(ValidationError) as caught:
            self.to_employee(
                self.make_active_asset(),
                department=self.dept_a_it,
            )

        self.assertIn("department", caught.exception.message_dict)

    def test_target_location_must_belong_to_the_owner(self):
        with self.assertRaises(ValidationError) as caught:
            self.to_employee(self.make_active_asset(), location=self.loc_b1)

        self.assertIn("location", caught.exception.message_dict)

    def test_cross_company_employee_is_explicit_and_keeps_ownership(self):
        holding = self.make_employee(company=self.company_b)
        placement = OrganizationAssignment.objects.get(employee=holding)
        asset = self.make_active_asset()

        with self.assertRaises(ValidationError) as caught:
            self.to_employee(asset, holding)

        self.assertIn("cross_company_reason", caught.exception.message_dict)

        assignment = self.to_employee(
            asset,
            holding,
            cross_company_reason="Laptop operasional untuk tim holding",
        )

        self.assertTrue(assignment.is_cross_company)
        self.assertEqual(assignment.employee_company, self.company_b)
        self.assertEqual(assignment.company, self.company_a)

        self.run_through(assignment)

        asset.refresh_from_db()
        held = self.open_custody(asset)

        self.assertEqual(asset.company, self.company_a)
        self.assertEqual(held.company, self.company_a)
        self.assertEqual(held.employee, holding)
        self.assertEqual(held.location.company, self.company_a)

        placement_after = OrganizationAssignment.objects.get(employee=holding)
        self.assertEqual(placement_after.company, self.company_b)
        self.assertEqual(placement_after.updated_at, placement.updated_at)

    def test_same_company_recipient_drops_any_cross_company_reason(self):
        assignment = self.to_employee(
            self.make_active_asset(),
            cross_company_reason="tidak relevan",
        )

        self.assertFalse(assignment.is_cross_company)
        self.assertEqual(assignment.cross_company_reason, "")


# ======================================================================
# Organisasi
# ======================================================================


class OrganizationAssignmentTests(AssignmentTestCase):
    def test_vehicle_to_department_with_pic(self):
        vehicles = self.make_category(allow_employee_custody=False)
        lv = self.make_active_asset(category=vehicles, location=self.loc_a2)
        manager = self.make_employee(location=self.loc_a2)

        self.run_through(self.assign(
            lv,
            to=ORGANIZATION,
            location=self.loc_a2,
            department=self.dept_a_mining,
            pic_employee=manager,
        ))

        held = self.open_custody(lv)

        self.assertEqual(held.custody_type, ORGANIZATION)
        self.assertEqual(held.department, self.dept_a_mining)
        self.assertEqual(held.pic_employee, manager)
        self.assertIsNone(held.employee)

    def test_pic_is_optional(self):
        lv = self.make_active_asset()

        self.run_through(self.assign(
            lv,
            to=ORGANIZATION,
            department=self.dept_a_mining,
        ))

        self.assertIsNone(self.open_custody(lv).pic_employee)

    def test_invalid_organization_targets_are_rejected(self):
        cases = [
            ({"department": self.dept_b_fin}, "department"),
            ({}, "department"),
            (
                {
                    "department": self.dept_a_mining,
                    "pic_employee": self.make_employee(company=self.company_b),
                },
                "pic_employee",
            ),
            (
                {
                    "department": self.dept_a_mining,
                    "pic_employee": self.make_employee(placed=False),
                },
                "pic_employee",
            ),
            (
                {
                    "department": self.dept_a_mining,
                    "employee": self.make_employee(),
                },
                "employee",
            ),
        ]

        for extra, field_name in cases:
            with self.subTest(field=field_name, extra=list(extra)):
                with self.assertRaises(ValidationError) as caught:
                    self.assign(self.make_active_asset(), to=ORGANIZATION, **extra)

                self.assertIn(field_name, caught.exception.message_dict)


# ======================================================================
# Asal STORAGE
# ======================================================================


class SourceStorageTests(AssignmentTestCase):
    def test_source_must_be_an_active_asset_in_storage(self):
        with self.assertRaises(ValidationError):
            self.to_employee(self.make_asset())

        asset = self.make_active_asset()
        self.run_through(self.to_employee(asset))

        with self.assertRaises(ValidationError) as caught:
            self.to_employee(asset)

        self.assertIn("asset", caught.exception.message_dict)


# ======================================================================
# Alur, pemesanan, imutabilitas
# ======================================================================


class AssignmentWorkflowTests(AssignmentTestCase):
    def test_approval_flow_does_not_move_custody_until_complete(self):
        approver = self.make_user()
        self.make_workflow(approver=approver)

        asset = self.make_active_asset()
        storage = asset.current_custody
        assignment = self.to_employee(asset)

        AssetAssignmentService.submit(assignment=assignment)
        assignment.refresh_from_db()

        self.assertEqual(assignment.status, AssignmentStatus.SUBMITTED)
        self.assertEqual(self.open_custody(asset), storage)

        AssetAssignmentService.decide(
            assignment=assignment,
            approved=True,
            user=approver,
        )
        assignment.refresh_from_db()

        self.assertEqual(assignment.status, AssignmentStatus.APPROVED)
        self.assertEqual(self.open_custody(asset), storage)

        AssetAssignmentService.complete(assignment=assignment)

        self.assertEqual(self.open_custody(asset).custody_type, EMPLOYEE)

    def test_recipient_is_not_an_approver(self):
        approver = self.make_user()
        self.make_workflow(approver=approver)

        recipient_user = self.make_user()
        recipient = self.make_employee(user=recipient_user)

        assignment = self.to_employee(self.make_active_asset(), recipient)
        AssetAssignmentService.submit(assignment=assignment)

        with self.assertRaises((ValidationError, PermissionDenied)):
            AssetAssignmentService.decide(
                assignment=assignment,
                approved=True,
                user=recipient_user,
            )

        assignment.refresh_from_db()
        self.assertEqual(assignment.status, AssignmentStatus.SUBMITTED)

    def test_draft_does_not_reserve_but_submit_does(self):
        asset = self.make_active_asset()

        first = self.to_employee(asset)
        second = self.to_employee(asset)

        AssetAssignmentService.submit(assignment=first)

        with self.assertRaises(ValidationError) as caught:
            AssetAssignmentService.submit(assignment=second)

        self.assertIn("asset", caught.exception.message_dict)

        AssetAssignmentService.complete(assignment=first)

        # Sesudah serah terima, draft kedua basi: custody sudah berubah.
        with self.assertRaises(ValidationError):
            AssetAssignmentService.submit(assignment=second)

        second.refresh_from_db()
        self.assertEqual(second.status, AssignmentStatus.DRAFT)

    def test_reject_and_cancel_release_the_reservation(self):
        approver = self.make_user()
        self.make_workflow(approver=approver)

        asset = self.make_active_asset()

        rejected = self.to_employee(asset)
        AssetAssignmentService.submit(assignment=rejected)
        AssetAssignmentService.decide(
            assignment=rejected,
            approved=False,
            user=approver,
        )
        rejected.refresh_from_db()
        self.assertEqual(rejected.status, AssignmentStatus.REJECTED)

        cancelled = self.to_employee(asset)
        AssetAssignmentService.submit(assignment=cancelled)
        AssetAssignmentService.cancel(assignment=cancelled, notes="salah orang")
        cancelled.refresh_from_db()
        self.assertEqual(cancelled.status, AssignmentStatus.CANCELLED)
        self.assertIsNotNone(cancelled.cancelled_at)

        # Pemesanan sudah lepas dua kali — dokumen ketiga bisa berjalan.
        third = self.to_employee(asset)
        AssetAssignmentService.submit(assignment=third)
        AssetAssignmentService.decide(assignment=third, approved=True, user=approver)
        AssetAssignmentService.complete(assignment=third)

        self.assertEqual(self.open_custody(asset).custody_type, EMPLOYEE)

    def test_cancel_only_applies_to_running_documents(self):
        draft = self.to_employee(self.make_active_asset())

        with self.assertRaises(ValidationError):
            AssetAssignmentService.cancel(assignment=draft)

        done = self.run_through(self.to_employee(self.make_active_asset()))

        with self.assertRaises(ValidationError):
            AssetAssignmentService.cancel(assignment=done)

    def test_submitted_documents_cannot_be_edited_or_deleted(self):
        assignment = self.to_employee(self.make_active_asset())
        AssetAssignmentService.submit(assignment=assignment)
        assignment.refresh_from_db()

        with self.assertRaises(ValidationError):
            AssetAssignmentService.update(
                instance=assignment,
                data={"purpose": "ubah"},
            )

        with self.assertRaises(ValidationError):
            AssetAssignmentService.soft_delete(instance=assignment)

    def test_completed_assignment_is_immutable(self):
        done = self.run_through(self.to_employee(self.make_active_asset()))

        for attempt in (
            lambda: AssetAssignmentService.update(instance=done, data={"notes": "x"}),
            lambda: AssetAssignmentService.soft_delete(instance=done),
            lambda: AssetAssignmentService.complete(assignment=done),
            lambda: AssetAssignmentService.cancel(assignment=done),
        ):
            with self.assertRaises(ValidationError):
                attempt()

        done.refresh_from_db()
        self.assertEqual(done.status, AssignmentStatus.COMPLETED)
        self.assertFalse(done.is_deleted)

    def test_draft_can_be_deleted(self):
        draft = self.to_employee(self.make_active_asset())
        AssetAssignmentService.soft_delete(instance=draft)

        draft.refresh_from_db()
        self.assertTrue(draft.is_deleted)

    def test_handover_condition_goes_through_condition_history(self):
        asset = self.make_active_asset()

        self.run_through(
            self.to_employee(asset),
            condition=AssetCondition.DAMAGED,
            note="baret di casing",
        )

        asset.refresh_from_db()
        log = AssetConditionLog.objects.get(
            asset=asset,
            source=ConditionSource.HANDOVER,
        )

        self.assertEqual(log.previous_condition, AssetCondition.GOOD)
        self.assertEqual(log.new_condition, AssetCondition.DAMAGED)
        self.assertEqual(asset.condition, AssetCondition.DAMAGED)
        self.assertEqual(
            self.open_custody(asset).start_condition,
            AssetCondition.DAMAGED,
        )

    def test_handover_date_cannot_be_in_the_future(self):
        assignment = self.to_employee(self.make_active_asset())
        AssetAssignmentService.submit(assignment=assignment)

        with self.assertRaises(ValidationError):
            AssetAssignmentService.complete(
                assignment=assignment,
                handover_date=timezone.localdate() + timedelta(days=1),
            )

        with self.assertRaises(ValidationError):
            AssetAssignmentService.complete(
                assignment=assignment,
                handover_date=timezone.localdate() - timedelta(days=1),
            )

    def test_failed_completion_leaves_no_half_moved_custody(self):
        asset = self.make_active_asset()
        storage = asset.current_custody
        assignment = self.to_employee(asset)
        AssetAssignmentService.submit(assignment=assignment)

        target = "apps.assets.services.operations.custody.AssetCustodyService._open"

        with mock.patch(target, side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                AssetAssignmentService.complete(assignment=assignment)

        storage.refresh_from_db()
        asset.refresh_from_db()
        assignment.refresh_from_db()

        self.assertIsNone(storage.ended_on)
        self.assertEqual(asset.current_custody, storage)
        self.assertEqual(assignment.status, AssignmentStatus.APPROVED)

    def test_service_checks_workflow_action_permissions(self):
        nobody = self.make_user()
        assignment = self.to_employee(self.make_active_asset())

        with self.assertRaises(PermissionDenied):
            AssetAssignmentService.submit(assignment=assignment, user=nobody)

        submitter = self.make_user(permissions=("submit_assetassignment",))
        AssetAssignmentService.submit(assignment=assignment, user=submitter)

        with self.assertRaises(PermissionDenied):
            AssetAssignmentService.complete(assignment=assignment, user=submitter)

        with self.assertRaises(PermissionDenied):
            AssetAssignmentService.cancel(assignment=assignment, user=submitter)


# ======================================================================
# Invariant database
# ======================================================================


class AssignmentDatabaseInvariantTests(AssignmentTestCase):
    def test_database_allows_one_active_reservation_per_asset(self):
        # Sejak ASSET-4 penjaganya `AssetOperationReservation` (authority
        # bersama), bukan constraint di tabel Assignment.
        asset = self.make_active_asset()
        first = self.to_employee(asset)
        second = self.to_employee(asset)

        AssetAssignmentService.submit(assignment=first)

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AssetOperationReservation.objects.create(
                    asset=asset,
                    operation_type=AssetOperationType.ASSIGNMENT,
                    document_id=second.pk,
                    reserved_at=timezone.now(),
                )

    def test_database_enforces_custody_holder_shape(self):
        asset = self.make_active_asset()
        employee = self.make_employee()

        bad_rows = [
            {"custody_type": EMPLOYEE},
            {"custody_type": STORAGE_TYPE, "employee": employee},
            {"custody_type": ORGANIZATION},
            {
                "custody_type": EMPLOYEE,
                "employee": employee,
                "department": self.dept_a_it,
            },
        ]

        for extra in bad_rows:
            with self.subTest(extra=extra):
                with self.assertRaises(IntegrityError):
                    with transaction.atomic():
                        # Tutup dulu yang terbuka supaya yang diuji
                        # constraint bentuk, bukan constraint "satu terbuka".
                        AssetCustody.objects.filter(pk=asset.current_custody_id).update(
                            ended_on=timezone.localdate(),
                        )
                        AssetCustody.objects.create(
                            asset=asset,
                            company=asset.company,
                            location=asset.location,
                            started_on=timezone.localdate(),
                            start_condition=asset.condition,
                            opened_by_type="test",
                            opened_by_id="1",
                            **extra,
                        )


STORAGE_TYPE = CustodyType.STORAGE


# ======================================================================
# Registrasi workflow
# ======================================================================


class WorkflowRegistrationTests(AssignmentTestCase):
    def test_completion_handler_and_route_are_registered(self):
        from apps.assets import workflow_handlers
        from apps.workflow.registry import completion_handler, document_url

        handler = completion_handler(
            module="assets",
            document_type="asset_assignment",
        )

        self.assertIs(handler, workflow_handlers.asset_assignment_completed)
        self.assertEqual(
            document_url(
                module="assets",
                document_type="asset_assignment",
                object_id=7,
            ),
            "/assets/assignments/7",
        )

    def test_decision_from_the_generic_inbox_moves_the_document(self):
        from apps.workflow.registry import completion_handler
        from apps.workflow.services.workflow_service import WorkflowService

        approver = self.make_user()
        self.make_workflow(approver=approver)

        assignment = self.to_employee(self.make_active_asset())
        workflow = AssetAssignmentService.submit(assignment=assignment)

        # Jalur kotak masuk: engine memanggil handler yang terdaftar,
        # bukan callback dari layar dokumen.
        WorkflowService.approve(
            instance=workflow,
            user=approver,
            on_complete=completion_handler(
                module="assets",
                document_type="asset_assignment",
            ),
        )

        assignment.refresh_from_db()
        self.assertEqual(assignment.status, AssignmentStatus.APPROVED)


# ======================================================================
# API, cakupan, lookup
# ======================================================================


@override_settings(
    ENFORCE_MODEL_PERMISSIONS=True,
    ENFORCE_VIEW_PERMISSIONS=True,
)
class AssignmentApiTests(AssignmentTestCase):
    ALL = (
        "view_assetassignment",
        "add_assetassignment",
        "change_assetassignment",
        "delete_assetassignment",
        "submit_assetassignment",
        "complete_assetassignment",
        "cancel_assetassignment",
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
        asset = self.make_active_asset()
        employee = self.make_employee()

        created = self.call("post", ENDPOINT, clerk, {
            "asset": asset.pk,
            "target_custody_type": EMPLOYEE,
            "employee": employee.pk,
            "location": self.loc_a1.pk,
            "purpose": "Laptop kerja",
            # Diabaikan: read-only.
            "status": AssignmentStatus.COMPLETED,
            "company": self.company_b.pk,
        })

        self.assertEqual(created.status_code, 201, created.content[:500])

        assignment = AssetAssignment.objects.get(asset=asset, is_deleted=False)
        self.assertEqual(assignment.status, AssignmentStatus.DRAFT)
        self.assertEqual(assignment.company, self.company_a)

        submitted = self.call("post", f"{ENDPOINT}{assignment.pk}/submit/", clerk, {})
        self.assertEqual(submitted.status_code, 200, submitted.content[:500])
        self.assertEqual(
            self.body(submitted)["data"]["status"],
            AssignmentStatus.APPROVED,
        )

        edited = self.call("patch", f"{ENDPOINT}{assignment.pk}/", clerk, {
            "purpose": "ubah",
        })
        self.assertEqual(edited.status_code, 400)

        completed = self.call(
            "post",
            f"{ENDPOINT}{assignment.pk}/complete/",
            clerk,
            {"condition": AssetCondition.GOOD},
        )
        self.assertEqual(completed.status_code, 200, completed.content[:500])
        self.assertEqual(
            self.body(completed)["data"]["status"],
            AssignmentStatus.COMPLETED,
        )

        self.assertEqual(self.open_custody(asset).employee, employee)

        deleted = self.call("delete", f"{ENDPOINT}{assignment.pk}/", clerk)
        self.assertEqual(deleted.status_code, 400)

    def test_workflow_actions_need_their_own_permissions(self):
        drafter = self.make_user(permissions=(
            "view_assetassignment",
            "add_assetassignment",
            "change_assetassignment",
        ))
        assignment = self.to_employee(self.make_active_asset())

        submitted = self.call("post", f"{ENDPOINT}{assignment.pk}/submit/", drafter, {})
        self.assertIn(submitted.status_code, (403, 404))

        assignment.refresh_from_db()
        self.assertEqual(assignment.status, AssignmentStatus.DRAFT)

        AssetAssignmentService.submit(assignment=assignment)

        completed = self.call("post", f"{ENDPOINT}{assignment.pk}/complete/", drafter, {})
        self.assertIn(completed.status_code, (403, 404))

        assignment.refresh_from_db()
        self.assertEqual(assignment.status, AssignmentStatus.APPROVED)

    def test_recipient_gets_no_access_from_being_the_recipient(self):
        recipient_user = self.make_user()
        recipient = self.make_employee(user=recipient_user)
        assignment = self.to_employee(self.make_active_asset(), recipient)

        listed = self.call("get", ENDPOINT, recipient_user)
        self.assertEqual(listed.status_code, 403)

        approved = self.call(
            "post",
            f"{ENDPOINT}{assignment.pk}/approve/",
            recipient_user,
            {},
        )
        self.assertIn(approved.status_code, (403, 404))

    def test_scope_follows_the_owner_side(self):
        own_site = self.to_employee(self.make_active_asset(location=self.loc_a1))
        other_site = self.to_employee(
            self.make_active_asset(location=self.loc_a2),
            location=self.loc_a2,
        )
        cross = self.to_employee(
            self.make_active_asset(location=self.loc_a1),
            self.make_employee(company=self.company_b),
            cross_company_reason="Holding",
        )
        self.run_through(cross)

        site_admin = self.make_user(
            permissions=("view_assetassignment", "view_asset"),
            authorities=[("location", self.loc_a1.pk)],
        )

        visible = self.ids(self.call("get", f"{ENDPOINT}?page_size=500", site_admin))
        self.assertIn(own_site.pk, visible)
        self.assertIn(cross.pk, visible)
        self.assertNotIn(other_site.pk, visible)

        # Admin company penerima tidak melihat dokumen maupun register
        # milik company pemilik (O-8).
        recipient_admin = self.make_user(
            permissions=("view_assetassignment", "view_asset"),
            authorities=[("company", self.company_b.pk)],
        )

        self.assertNotIn(
            cross.pk,
            self.ids(self.call("get", f"{ENDPOINT}?page_size=500", recipient_admin)),
        )
        self.assertNotIn(
            cross.asset_id,
            self.ids(self.call("get", "/api/assets/assets/?page_size=500", recipient_admin)),
        )

    def test_available_assets_lookup(self):
        viewer = self.make_user(permissions=("view_asset",))

        vehicles = self.make_category(allow_employee_custody=False)

        free = self.make_active_asset()
        vehicle = self.make_active_asset(category=vehicles)
        reserved = self.make_active_asset()
        held = self.make_active_asset()
        draft = self.make_asset()

        AssetAssignmentService.submit(assignment=self.to_employee(reserved))
        self.run_through(self.to_employee(held))

        def offered(params=""):
            response = self.call(
                "get",
                f"{AVAILABLE}?page_size=1000{params}",
                viewer,
            )
            self.assertEqual(response.status_code, 200, response.content[:500])

            return {row["value"] for row in self.body(response)["results"]}

        everything = offered()

        self.assertIn(free.pk, everything)
        self.assertIn(vehicle.pk, everything)
        self.assertNotIn(reserved.pk, everything)
        self.assertNotIn(held.pk, everything)
        self.assertNotIn(draft.pk, everything)

        for_employee = offered(f"&target_custody_type={EMPLOYEE}")

        self.assertIn(free.pk, for_employee)
        self.assertNotIn(vehicle.pk, for_employee)

    def test_ui_schema_declares_assignment_actions(self):
        viewer = self.make_user(permissions=("view_assetassignment",))

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
