"""
ASSET-5 — Asset Transfer (pemakaian → pemakaian, STORAGE → STORAGE).

Kontraknya `docs/claude/assets.md` §10, §17, §18, §26. Yang dikunci:

* matriks semantik: Transfer tidak pernah STORAGE ↔ pemakaian (itu
  Assignment/Return), dan tidak pernah no-op;
* asal dibaca ulang dari custody terbuka; dokumen basi ditolak;
* tujuan EMPLOYEE/ORGANIZATION mengikuti aturan pemegang yang sama dengan
  Assignment (kapabilitas kategori, penempatan aktif, O-8, PIC pemilik);
* ganti PIC resmi = Transfer; tanpa approval khusus yang ditanam di kode;
* kondisi: tujuan pemakaian hanya GOOD/FAIR; STORAGE → STORAGE semua
  kondisi; kondisi selesai wajib dan dicatat (TRANSFER);
* pemesanan bersama, dilepas di setiap jalan keluar;
* lihat = asal ∪ tujuan; submit/cancel/sunting = asal; complete = tujuan.
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
    AssetCondition,
    AssetConditionLog,
    AssetCustody,
    AssetOperationReservation,
    AssetOperationType,
    AssetTransfer,
    ConditionSource,
    CustodyType,
    ReservationRelease,
    TransferReason,
    TransferStatus,
)
from apps.assets.services import (
    AssetAssignmentService,
    AssetCustodyService,
    AssetReservationService,
    AssetReturnService,
    AssetService,
    AssetTransferService,
)
from apps.assets.services.operations.asset_transfer import custody_signature

from .base import AssetsTestCase


ENDPOINT = "/api/assets/transfers/"
TRANSFERABLE = "/api/assets/lookup/transferable-assets/"

EMPLOYEE = CustodyType.EMPLOYEE
ORGANIZATION = CustodyType.ORGANIZATION
STORAGE = CustodyType.STORAGE


class TransferTestCase(AssetsTestCase):
    @classmethod
    def build_baseline(cls):
        super().build_baseline()

        cls.loc_a3 = cls._location(cls.company_a, "AST-A-THIRD", "A Third Site")

    @staticmethod
    def open_custody(asset):
        return AssetCustody.objects.get(
            asset=asset,
            ended_on__isnull=True,
            is_deleted=False,
        )

    @staticmethod
    def run_through(transfer, condition=AssetCondition.GOOD, **kwargs):
        """Tanpa alur yang cocok: submit → APPROVED, lalu complete."""
        AssetTransferService.submit(transfer=transfer)

        return AssetTransferService.complete(
            transfer=transfer,
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

    def vehicle(self, *, pic=None, department=None, location=None, **category):
        category = self.make_category(**category)

        return self.hand_to_department(
            self.make_active_asset(category=category),
            department or self.dept_a_mining,
            pic=pic,
            location=location,
        )


# ======================================================================
# EMPLOYEE → EMPLOYEE
# ======================================================================


class EmployeeToEmployeeTests(TransferTestCase):
    def test_holder_a_to_holder_b(self):
        a = self.make_employee()
        b = self.make_employee()
        laptop = self.hand_over(self.make_active_asset(), a)
        radio = self.hand_over(self.make_active_asset(), a)
        b_already = self.hand_over(self.make_active_asset(), b)
        held = laptop.current_custody

        transfer = self.make_transfer(laptop, target_employee=b)

        # Asal disalin dari custody.
        self.assertEqual(transfer.source_custody, held)
        self.assertEqual(transfer.source_custody_type, EMPLOYEE)
        self.assertEqual(transfer.source_employee, a)
        self.assertEqual(transfer.company, self.company_a)
        self.assertTrue(transfer.document_number.startswith("ATR"))
        self.assertEqual(transfer.employee_company, self.company_a)
        self.assertFalse(transfer.is_cross_company)

        self.run_through(transfer, note="pindah tangan")

        transfer.refresh_from_db()
        laptop.refresh_from_db()
        held.refresh_from_db()

        now = self.open_custody(laptop)

        self.assertEqual(transfer.status, TransferStatus.COMPLETED)
        self.assertEqual(transfer.resulting_custody, now)
        self.assertEqual(transfer.transfer_date, timezone.localdate())
        self.assertEqual(transfer.transfer_condition, AssetCondition.GOOD)

        self.assertEqual((now.custody_type, now.employee), (EMPLOYEE, b))
        self.assertEqual(now.opened_by_type, "asset_transfer")
        self.assertEqual(held.closed_by_type, "asset_transfer")
        self.assertEqual(laptop.current_custody, now)
        self.assertEqual(laptop.company, self.company_a)

        # A tetap memegang aset lain; B memegang banyak.
        self.assertEqual(self.open_custody(radio).employee, a)
        self.assertEqual(
            {
                self.open_custody(laptop).employee_id,
                self.open_custody(b_already).employee_id,
            },
            {b.pk},
        )

        self.assertIsNone(self.reservation_of(laptop))
        self.assert_invariants()

    def test_same_employee_new_location_is_a_real_change(self):
        employee = self.make_employee()
        asset = self.hand_over(self.make_active_asset(), employee)

        self.run_through(self.make_transfer(
            asset,
            target_employee=employee,
            location=self.loc_a2,
            reason=TransferReason.RELOCATION,
        ))

        asset.refresh_from_db()
        now = self.open_custody(asset)

        self.assertEqual((now.employee, now.location), (employee, self.loc_a2))
        self.assertEqual(asset.location, self.loc_a2)

    def test_cross_company_target_is_explicit_and_keeps_ownership(self):
        outsider = self.make_employee(company=self.company_b)
        asset = self.hand_over(self.make_active_asset())

        with self.assertRaises(ValidationError) as caught:
            self.make_transfer(asset, target_employee=outsider)
        self.assertIn("cross_company_reason", caught.exception.message_dict)

        # Lokasi fisik tetap harus milik pemilik.
        with self.assertRaises(ValidationError) as caught:
            self.make_transfer(
                asset,
                target_employee=outsider,
                cross_company_reason="Proyek bersama",
                location=self.loc_b1,
            )
        self.assertIn("target_location", caught.exception.message_dict)

        transfer = self.make_transfer(
            asset,
            target_employee=outsider,
            cross_company_reason="Proyek bersama",
        )
        self.assertTrue(transfer.is_cross_company)
        self.assertEqual(transfer.employee_company, self.company_b)

        self.run_through(transfer)

        asset.refresh_from_db()
        now = self.open_custody(asset)

        self.assertEqual(asset.company, self.company_a)
        self.assertEqual(now.company, self.company_a)
        self.assertEqual(now.location.company, self.company_a)
        # Penempatan HR tidak disentuh.
        self.assertEqual(outsider.organization.company, self.company_b)

        # Dari pegawai lintas company kembali ke pegawai pemilik: flag
        # diturunkan ulang dari tujuan, tidak diwariskan dari asal.
        back = self.make_transfer(
            asset,
            target_employee=self.make_employee(),
            cross_company_reason="sisa alasan lama",
        )
        self.assertFalse(back.is_cross_company)
        self.assertEqual(back.cross_company_reason, "")
        self.assertEqual(back.employee_company, self.company_a)


# ======================================================================
# EMPLOYEE ↔ ORGANIZATION
# ======================================================================


class EmployeeOrganizationTests(TransferTestCase):
    def test_employee_to_mining_department_with_optional_pic(self):
        for pic in (None, self.make_employee()):
            with self.subTest(pic=pic):
                asset = self.hand_over(self.make_active_asset())

                self.run_through(self.make_transfer(
                    asset,
                    to=ORGANIZATION,
                    target_department=self.dept_a_mining,
                    target_pic_employee=pic,
                ))

                now = self.open_custody(asset)
                self.assertEqual(now.custody_type, ORGANIZATION)
                self.assertEqual(now.department, self.dept_a_mining)
                self.assertEqual(now.pic_employee, pic)
                self.assertIsNone(now.employee)

    def test_department_to_employee_needs_category_capability(self):
        lv = self.vehicle(allow_employee_custody=False)

        with self.assertRaises(ValidationError) as caught:
            self.make_transfer(lv, target_employee=self.make_employee())
        self.assertIn("target_custody_type", caught.exception.message_dict)

        equipment = self.vehicle()
        employee = self.make_employee()

        self.run_through(self.make_transfer(equipment, target_employee=employee))

        self.assertEqual(self.open_custody(equipment).employee, employee)


# ======================================================================
# ORGANIZATION → ORGANIZATION (+ ganti PIC)
# ======================================================================


class OrganizationToOrganizationTests(TransferTestCase):
    def test_department_a_to_department_b(self):
        lv = self.vehicle(department=self.dept_a_mining)

        self.run_through(self.make_transfer(
            lv,
            to=ORGANIZATION,
            target_department=self.dept_a_it,
            reason=TransferReason.REORGANIZATION,
        ))

        self.assertEqual(self.open_custody(lv).department, self.dept_a_it)

    def test_pic_only_transfer_is_valid(self):
        pic_a = self.make_employee()
        pic_b = self.make_employee()
        lv = self.vehicle(pic=pic_a, allow_employee_custody=False)

        transfer = self.make_transfer(
            lv,
            to=ORGANIZATION,
            target_department=self.dept_a_mining,
            target_pic_employee=pic_b,
            reason=TransferReason.PIC_CHANGE,
        )

        self.assertTrue(AssetTransferService.is_pic_change(transfer))
        self.assertTrue(AssetTransferService.workflow_context(transfer)["is_pic_change"])
        self.assertFalse(AssetTransferService.workflow_context(transfer)["is_relocation"])

        # Tanpa definisi alur: langsung APPROVED, tidak ada approval khusus
        # yang ditanam di kode.
        AssetTransferService.submit(transfer=transfer)
        transfer.refresh_from_db()
        self.assertEqual(transfer.status, TransferStatus.APPROVED)

        AssetTransferService.complete(transfer=transfer, condition=AssetCondition.GOOD)

        now = self.open_custody(lv)
        self.assertEqual(
            (now.department, now.pic_employee, now.location),
            (self.dept_a_mining, pic_b, self.loc_a1),
        )

        # Riwayat PIC lama tetap ada.
        self.assertTrue(
            AssetCustody.objects.filter(
                asset=lv,
                pic_employee=pic_a,
                ended_on__isnull=False,
            ).exists(),
        )
        self.assert_invariants()

    def test_pic_change_follows_a_configured_workflow(self):
        approver = self.make_user()
        self.make_workflow(approver=approver, document_type="asset_transfer")

        lv = self.vehicle(pic=self.make_employee())
        transfer = self.make_transfer(
            lv,
            to=ORGANIZATION,
            target_department=self.dept_a_mining,
            target_pic_employee=self.make_employee(),
        )

        AssetTransferService.submit(transfer=transfer)
        transfer.refresh_from_db()
        self.assertEqual(transfer.status, TransferStatus.SUBMITTED)

        AssetTransferService.decide(transfer=transfer, approved=True, user=approver)
        transfer.refresh_from_db()
        self.assertEqual(transfer.status, TransferStatus.APPROVED)

    def test_site_to_site_movement(self):
        lv = self.vehicle(location=self.loc_a1)

        self.run_through(self.make_transfer(
            lv,
            to=ORGANIZATION,
            target_department=self.dept_a_mining,
            location=self.loc_a2,
            target_facility=self.fac_a2,
            reason=TransferReason.RELOCATION,
        ))

        lv.refresh_from_db()
        now = self.open_custody(lv)

        self.assertEqual((now.location, now.facility), (self.loc_a2, self.fac_a2))
        self.assertEqual((lv.location, lv.facility), (self.loc_a2, self.fac_a2))

    def test_no_driver_or_operator_concept(self):
        names = {field.name for field in AssetTransfer._meta.get_fields()}

        self.assertFalse({n for n in names if "driver" in n or "operator" in n})

    def test_pic_must_belong_to_owner_company(self):
        lv = self.vehicle()

        with self.assertRaises(ValidationError) as caught:
            self.make_transfer(
                lv,
                to=ORGANIZATION,
                target_department=self.dept_a_mining,
                target_pic_employee=self.make_employee(company=self.company_b),
            )
        self.assertIn("target_pic_employee", caught.exception.message_dict)

        with self.assertRaises(ValidationError) as caught:
            self.make_transfer(lv, to=ORGANIZATION, target_department=self.dept_b_fin)
        self.assertIn("target_department", caught.exception.message_dict)


# ======================================================================
# STORAGE → STORAGE
# ======================================================================


class StorageToStorageTests(TransferTestCase):
    def test_ho_storage_to_site_storage(self):
        asset = self.make_active_asset()

        transfer = self.make_transfer(
            asset,
            to=STORAGE,
            location=self.loc_a2,
            target_facility=self.fac_a2,
            reason=TransferReason.RELOCATION,
        )
        self.assertEqual(transfer.source_custody_type, STORAGE)

        self.run_through(transfer)

        asset.refresh_from_db()
        now = self.open_custody(asset)

        self.assertEqual(now.custody_type, STORAGE)
        self.assertEqual((now.location, now.facility), (self.loc_a2, self.fac_a2))
        self.assertEqual((asset.location, asset.facility), (self.loc_a2, self.fac_a2))
        self.assertIsNone(now.employee)
        self.assert_invariants()

    def test_same_storage_is_a_no_op(self):
        asset = self.make_active_asset()

        with self.assertRaises(ValidationError) as caught:
            self.make_transfer(asset, to=STORAGE, location=self.loc_a1)
        self.assertIn("target_custody_type", caught.exception.message_dict)

        # Fasilitas berbeda di lokasi yang sama = perubahan.
        self.make_transfer(
            asset,
            to=STORAGE,
            location=self.loc_a1,
            target_facility=self.fac_a1,
        )

    def test_damaged_and_unserviceable_assets_can_move_between_storages(self):
        for condition in (AssetCondition.DAMAGED, AssetCondition.UNSERVICEABLE):
            with self.subTest(condition=condition):
                asset = self.make_active_asset()
                AssetService.record_condition(asset=asset, condition=condition)

                self.run_through(
                    self.make_transfer(asset, to=STORAGE, location=self.loc_a2),
                    condition=condition,
                )

                asset.refresh_from_db()
                self.assertEqual(self.open_custody(asset).location, self.loc_a2)
                self.assertEqual(asset.condition, condition)

    def test_storage_target_has_no_holder(self):
        asset = self.make_active_asset()

        with self.assertRaises(ValidationError) as caught:
            self.make_transfer(
                asset,
                to=STORAGE,
                location=self.loc_a2,
                target_employee=self.make_employee(),
            )
        self.assertIn("target_employee", caught.exception.message_dict)


# ======================================================================
# Tidak sah
# ======================================================================


class InvalidTransferTests(TransferTestCase):
    def test_storage_to_usage_is_an_assignment(self):
        asset = self.make_active_asset()

        for extra in (
            {"to": EMPLOYEE, "target_employee": self.make_employee()},
            {"to": ORGANIZATION, "target_department": self.dept_a_it},
        ):
            with self.subTest(to=extra["to"]):
                with self.assertRaises(ValidationError) as caught:
                    self.make_transfer(asset, **extra)

                message = str(caught.exception.message_dict["target_custody_type"])
                self.assertIn("Assignment", message)

    def test_usage_to_storage_is_a_return(self):
        for asset in (self.hand_over(self.make_active_asset()), self.vehicle()):
            with self.subTest(asset=asset.pk):
                with self.assertRaises(ValidationError) as caught:
                    self.make_transfer(asset, to=STORAGE, location=self.loc_a2)

                message = str(caught.exception.message_dict["target_custody_type"])
                self.assertIn("Return", message)

    def test_no_op_transfers_are_rejected(self):
        employee = self.make_employee()
        with_employee = self.hand_over(self.make_active_asset(), employee)

        pic = self.make_employee()
        lv = self.vehicle(pic=pic)

        for asset, extra in (
            (with_employee, {"target_employee": employee}),
            (
                lv,
                {
                    "to": ORGANIZATION,
                    "target_department": self.dept_a_mining,
                    "target_pic_employee": pic,
                },
            ),
        ):
            with self.subTest(asset=asset.pk):
                with self.assertRaises(ValidationError) as caught:
                    self.make_transfer(asset, **extra)

                self.assertIn("target_custody_type", caught.exception.message_dict)

    def test_semantic_equality_is_deterministic(self):
        base = {
            "custody_type": ORGANIZATION,
            "employee": None,
            "department": self.dept_a_mining,
            "pic": None,
            "location": self.loc_a1,
            "facility": None,
        }

        self.assertEqual(
            custody_signature(**base),
            custody_signature(**{**base, "department": self.dept_a_mining.pk}),
        )

        for change in (
            {"pic": self.make_employee()},
            {"department": self.dept_a_it},
            {"location": self.loc_a2},
            {"facility": self.fac_a1},
            {"custody_type": EMPLOYEE},
        ):
            with self.subTest(change=list(change)):
                self.assertNotEqual(
                    custody_signature(**base),
                    custody_signature(**{**base, **change}),
                )

    def test_wrong_company_location_or_facility(self):
        asset = self.hand_over(self.make_active_asset())
        employee = self.make_employee()

        with self.assertRaises(ValidationError) as caught:
            self.make_transfer(asset, target_employee=employee, location=self.loc_b1)
        self.assertIn("target_location", caught.exception.message_dict)

        with self.assertRaises(ValidationError) as caught:
            self.make_transfer(
                asset,
                target_employee=employee,
                location=self.loc_a1,
                target_facility=self.fac_a2,
            )
        self.assertIn("target_facility", caught.exception.message_dict)

        storage = self.make_active_asset()

        with self.assertRaises(ValidationError) as caught:
            self.make_transfer(storage, to=STORAGE, location=self.loc_b1)
        self.assertIn("target_location", caught.exception.message_dict)

    def test_employee_target_needs_an_active_placement(self):
        asset = self.hand_over(self.make_active_asset())

        with self.assertRaises(ValidationError) as caught:
            self.make_transfer(asset, target_employee=self.make_employee(placed=False))
        self.assertIn("target_employee", caught.exception.message_dict)

        with self.assertRaises(ValidationError) as caught:
            self.make_transfer(
                asset,
                target_employee=self.make_employee(),
                target_department=self.dept_a_it,
            )
        self.assertIn("target_department", caught.exception.message_dict)

    def test_source_cannot_be_supplied_by_the_client(self):
        asset = self.hand_over(self.make_active_asset())

        for name, value in (
            ("source_employee", self.make_employee()),
            ("source_location", self.loc_a2),
            ("source_custody_type", STORAGE),
            ("is_cross_company", True),
            ("employee_company", self.company_b),
            ("status", TransferStatus.APPROVED),
            ("transfer_condition", AssetCondition.GOOD),
        ):
            with self.subTest(field=name):
                with self.assertRaises(ValidationError) as caught:
                    self.make_transfer(
                        asset,
                        target_employee=self.make_employee(),
                        **{name: value},
                    )

                self.assertIn(name, caught.exception.message_dict)

    def test_stale_asset_object_does_not_leak_into_the_source(self):
        asset = self.make_active_asset()
        stale = type(asset).objects.get(pk=asset.pk)  # masih STORAGE di memori

        holder = self.make_employee()
        self.hand_over(asset, holder)

        transfer = self.make_transfer(stale, target_employee=self.make_employee())
        self.assertEqual(transfer.source_employee, holder)
        self.assertEqual(transfer.source_custody_type, EMPLOYEE)

    def test_stale_source_is_rejected(self):
        asset = self.hand_over(self.make_active_asset())

        winner = self.make_transfer(asset, target_employee=self.make_employee())
        stale = self.make_transfer(asset, target_employee=self.make_employee())

        self.run_through(winner)

        with self.assertRaises(ValidationError):
            AssetTransferService.submit(transfer=stale)

        stale.refresh_from_db()
        self.assertEqual(stale.status, TransferStatus.DRAFT)

    def test_completed_transfer_is_immutable(self):
        done = self.run_through(self.make_transfer(
            self.hand_over(self.make_active_asset()),
            target_employee=self.make_employee(),
        ))

        for attempt in (
            lambda: AssetTransferService.update(instance=done, data={"notes": "x"}),
            lambda: AssetTransferService.soft_delete(instance=done),
            lambda: AssetTransferService.complete(transfer=done, condition=AssetCondition.GOOD),
            lambda: AssetTransferService.cancel(transfer=done),
        ):
            with self.assertRaises(ValidationError):
                attempt()

        done.refresh_from_db()
        self.assertEqual(done.status, TransferStatus.COMPLETED)

    def test_database_enforces_transfer_shapes_and_phase(self):
        transfer = self.make_transfer(
            self.hand_over(self.make_active_asset()),
            target_employee=self.make_employee(),
        )

        for change in (
            # Batas semantik: pemakaian → STORAGE (Return).
            {"target_custody_type": STORAGE, "target_employee": None},
            # Bentuk tujuan.
            {"target_department": self.dept_a_it},
            {"target_employee": None},
            # Bentuk asal.
            {"source_employee": None},
            # Selesai tanpa custody hasil.
            {"status": TransferStatus.COMPLETED},
            # Lintas company tanpa alasan.
            {"is_cross_company": True},
        ):
            with self.subTest(change=list(change)):
                with self.assertRaises(IntegrityError):
                    with transaction.atomic():
                        AssetTransfer.objects.filter(pk=transfer.pk).update(**change)


# ======================================================================
# Workflow + pemesanan
# ======================================================================


class TransferWorkflowTests(TransferTestCase):
    def test_only_complete_moves_custody(self):
        approver = self.make_user()
        self.make_workflow(approver=approver, document_type="asset_transfer")

        asset = self.hand_over(self.make_active_asset())
        held = asset.current_custody_id

        transfer = self.make_transfer(asset, target_employee=self.make_employee())
        self.assertIsNone(self.reservation_of(asset))

        AssetTransferService.submit(transfer=transfer)
        transfer.refresh_from_db()
        self.assertEqual(transfer.status, TransferStatus.SUBMITTED)
        self.assertEqual(self.open_custody(asset).pk, held)
        self.assertEqual(
            self.reservation_of(asset).operation_type,
            AssetOperationType.TRANSFER,
        )

        AssetTransferService.decide(transfer=transfer, approved=True, user=approver)
        transfer.refresh_from_db()
        self.assertEqual(transfer.status, TransferStatus.APPROVED)
        self.assertEqual(self.open_custody(asset).pk, held)
        self.assertIsNotNone(self.reservation_of(asset))

        AssetTransferService.complete(transfer=transfer, condition=AssetCondition.FAIR)

        self.assertEqual(self.open_custody(asset).employee, transfer.target_employee)
        self.assertIsNone(self.reservation_of(asset))
        self.assert_invariants()

    def test_holders_are_subjects_not_approvers(self):
        approver = self.make_user()
        self.make_workflow(approver=approver, document_type="asset_transfer")

        recipient_user = self.make_user()
        transfer = self.make_transfer(
            self.hand_over(self.make_active_asset()),
            target_employee=self.make_employee(user=recipient_user),
        )
        AssetTransferService.submit(transfer=transfer)

        with self.assertRaises((ValidationError, PermissionDenied)):
            AssetTransferService.decide(transfer=transfer, approved=True, user=recipient_user)

        transfer.refresh_from_db()
        self.assertEqual(transfer.status, TransferStatus.SUBMITTED)

    def test_every_exit_releases_the_reservation(self):
        from apps.workflow.models import InstanceStatus

        approver = self.make_user()
        self.make_workflow(approver=approver, document_type="asset_transfer")

        asset = self.hand_over(self.make_active_asset())

        def drafted():
            return self.make_transfer(asset, target_employee=self.make_employee())

        rejected = drafted()
        AssetTransferService.submit(transfer=rejected)
        AssetTransferService.decide(transfer=rejected, approved=False, user=approver)

        cancelled = drafted()
        AssetTransferService.submit(transfer=cancelled)
        AssetTransferService.cancel(transfer=cancelled, notes="batal")

        sent_back = drafted()
        AssetTransferService.submit(transfer=sent_back)
        AssetTransferService.on_workflow_done(
            transfer=sent_back,
            status=InstanceStatus.RETURNED,
        )
        sent_back.refresh_from_db()
        self.assertEqual(sent_back.status, TransferStatus.DRAFT)

        completed = drafted()
        AssetTransferService.submit(transfer=completed)
        AssetTransferService.decide(transfer=completed, approved=True, user=approver)
        AssetTransferService.complete(transfer=completed, condition=AssetCondition.GOOD)

        reasons = dict(
            AssetOperationReservation.objects
            .filter(asset=asset, operation_type=AssetOperationType.TRANSFER)
            .values_list("document_id", "release_reason")
        )

        self.assertEqual(reasons, {
            rejected.pk: ReservationRelease.REJECTED,
            cancelled.pk: ReservationRelease.CANCELLED,
            sent_back.pk: ReservationRelease.RETURNED_TO_DRAFT,
            completed.pk: ReservationRelease.COMPLETED,
        })
        self.assertIsNone(self.reservation_of(asset))
        self.assert_invariants()

    def test_transfer_assignment_and_return_do_not_overtake_each_other(self):
        asset = self.hand_over(self.make_active_asset())

        transfer = self.make_transfer(asset, target_employee=self.make_employee())
        asset_return = self.make_return(asset)
        AssetReturnService.submit(asset_return=asset_return)

        with self.assertRaises(ValidationError) as caught:
            AssetTransferService.submit(transfer=transfer)

        self.assertIn(asset_return.document_number, str(caught.exception.message_dict["asset"]))

        storage = self.make_active_asset()
        relocation = self.make_transfer(storage, to=STORAGE, location=self.loc_a2)
        AssetTransferService.submit(transfer=relocation)

        with self.assertRaises(ValidationError):
            AssetAssignmentService.submit(
                assignment=AssetAssignmentService.create(data={
                    "asset": storage,
                    "target_custody_type": EMPLOYEE,
                    "employee": self.make_employee(),
                    "location": self.loc_a1,
                }),
            )

    def test_completion_needs_condition_and_a_valid_date(self):
        transfer = self.make_transfer(
            self.hand_over(self.make_active_asset()),
            target_employee=self.make_employee(),
        )
        AssetTransferService.submit(transfer=transfer)

        for kwargs, field in (
            ({"condition": ""}, "condition"),
            ({"condition": "BROKEN"}, "condition"),
            (
                {
                    "condition": AssetCondition.GOOD,
                    "transfer_date": timezone.localdate() + timedelta(days=1),
                },
                "transfer_date",
            ),
            (
                {
                    "condition": AssetCondition.GOOD,
                    "transfer_date": timezone.localdate() - timedelta(days=1),
                },
                "transfer_date",
            ),
        ):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValidationError) as caught:
                    AssetTransferService.complete(transfer=transfer, **kwargs)

                self.assertIn(field, caught.exception.message_dict)

    def test_recipient_is_revalidated_at_completion(self):
        recipient = self.make_employee()
        transfer = self.make_transfer(
            self.hand_over(self.make_active_asset()),
            target_employee=recipient,
        )
        AssetTransferService.submit(transfer=transfer)

        recipient.is_active = False
        recipient.save(update_fields=["is_active"])

        with self.assertRaises(ValidationError) as caught:
            AssetTransferService.complete(transfer=transfer, condition=AssetCondition.GOOD)

        self.assertIn("target_employee", caught.exception.message_dict)

    def test_service_checks_workflow_action_permissions(self):
        nobody = self.make_user()
        transfer = self.make_transfer(
            self.hand_over(self.make_active_asset()),
            target_employee=self.make_employee(),
        )

        with self.assertRaises(PermissionDenied):
            AssetTransferService.submit(transfer=transfer, user=nobody)

        submitter = self.make_user(permissions=("submit_assettransfer",))
        AssetTransferService.submit(transfer=transfer, user=submitter)

        with self.assertRaises(PermissionDenied):
            AssetTransferService.complete(
                transfer=transfer,
                condition=AssetCondition.GOOD,
                user=submitter,
            )

        with self.assertRaises(PermissionDenied):
            AssetTransferService.cancel(transfer=transfer, user=submitter)

    def test_draft_can_be_edited_and_deleted(self):
        transfer = self.make_transfer(
            self.hand_over(self.make_active_asset()),
            target_employee=self.make_employee(),
        )

        other = self.make_employee()
        AssetTransferService.update(instance=transfer, data={"target_employee": other})
        transfer.refresh_from_db()
        self.assertEqual(transfer.target_employee, other)

        AssetTransferService.soft_delete(instance=transfer)
        transfer.refresh_from_db()
        self.assertTrue(transfer.is_deleted)


# ======================================================================
# Kondisi
# ======================================================================


class TransferConditionTests(TransferTestCase):
    def test_condition_is_always_recorded(self):
        asset = self.hand_over(self.make_active_asset())

        self.run_through(
            self.make_transfer(asset, target_employee=self.make_employee()),
            condition=AssetCondition.FAIR,
            note="baret halus",
        )

        asset.refresh_from_db()
        log = AssetConditionLog.objects.get(asset=asset, source=ConditionSource.TRANSFER)

        self.assertEqual(
            (log.previous_condition, log.new_condition, log.note),
            (AssetCondition.GOOD, AssetCondition.FAIR, "baret halus"),
        )
        self.assertEqual(asset.condition, AssetCondition.FAIR)
        self.assertEqual(self.open_custody(asset).start_condition, AssetCondition.FAIR)

    def test_unfit_asset_is_not_handed_to_another_user(self):
        asset = self.hand_over(self.make_active_asset())
        AssetService.record_condition(asset=asset, condition=AssetCondition.DAMAGED)

        with self.assertRaises(ValidationError) as caught:
            self.make_transfer(asset, target_employee=self.make_employee())
        self.assertIn("asset", caught.exception.message_dict)

        # Kondisi turun sesudah draft → submit ditolak.
        fit = self.hand_over(self.make_active_asset())
        draft = self.make_transfer(fit, target_employee=self.make_employee())
        AssetService.record_condition(asset=fit, condition=AssetCondition.UNSERVICEABLE)

        with self.assertRaises(ValidationError):
            AssetTransferService.submit(transfer=draft)

        self.assertIsNone(self.reservation_of(fit))

    def test_unfit_condition_at_completion_blocks_usage_target(self):
        asset = self.hand_over(self.make_active_asset())
        transfer = self.make_transfer(asset, target_employee=self.make_employee())
        AssetTransferService.submit(transfer=transfer)

        with self.assertRaises(ValidationError) as caught:
            AssetTransferService.complete(transfer=transfer, condition=AssetCondition.DAMAGED)
        self.assertIn("condition", caught.exception.message_dict)

        transfer.refresh_from_db()
        self.assertEqual(transfer.status, TransferStatus.APPROVED)
        self.assertEqual(self.open_custody(asset).custody_type, EMPLOYEE)

    def test_no_automatic_side_effects(self):
        asset = self.make_active_asset()
        AssetService.record_condition(asset=asset, condition=AssetCondition.UNSERVICEABLE)

        self.run_through(
            self.make_transfer(asset, to=STORAGE, location=self.loc_a2),
            condition=AssetCondition.UNSERVICEABLE,
        )

        asset.refresh_from_db()
        self.assertEqual(asset.status, "ACTIVE")
        self.assertEqual(
            list(
                AssetConditionLog.objects
                .filter(asset=asset)
                .order_by("id")
                .values_list("source", flat=True)
            ),
            [
                ConditionSource.REGISTRATION,
                ConditionSource.INSPECTION,
                ConditionSource.TRANSFER,
            ],
        )


# ======================================================================
# Registrasi workflow
# ======================================================================


class TransferWorkflowRegistrationTests(TransferTestCase):
    def test_completion_handler_and_route_are_registered(self):
        from apps.assets import workflow_handlers
        from apps.workflow.registry import completion_handler, document_url

        self.assertIs(
            completion_handler(module="assets", document_type="asset_transfer"),
            workflow_handlers.asset_transfer_completed,
        )
        self.assertEqual(
            document_url(module="assets", document_type="asset_transfer", object_id=5),
            "/assets/transfers/5",
        )

    def test_decision_from_the_generic_inbox_moves_the_document(self):
        from apps.workflow.registry import completion_handler
        from apps.workflow.services.workflow_service import WorkflowService

        approver = self.make_user()
        self.make_workflow(approver=approver, document_type="asset_transfer")

        transfer = self.make_transfer(
            self.hand_over(self.make_active_asset()),
            target_employee=self.make_employee(),
        )
        workflow = AssetTransferService.submit(transfer=transfer)

        WorkflowService.approve(
            instance=workflow,
            user=approver,
            on_complete=completion_handler(
                module="assets",
                document_type="asset_transfer",
            ),
        )

        transfer.refresh_from_db()
        self.assertEqual(transfer.status, TransferStatus.APPROVED)
        self.assertIsNotNone(self.reservation_of(transfer.asset))


# ======================================================================
# API, wewenang per sisi, lookup
# ======================================================================


@override_settings(
    ENFORCE_MODEL_PERMISSIONS=True,
    ENFORCE_VIEW_PERMISSIONS=True,
)
class TransferApiTests(TransferTestCase):
    ALL = (
        "view_assettransfer",
        "add_assettransfer",
        "change_assettransfer",
        "delete_assettransfer",
        "submit_assettransfer",
        "complete_assettransfer",
        "cancel_assettransfer",
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

    def admin(self, location):
        return self.make_user(
            permissions=self.ALL,
            authorities=[("location", location.pk)],
        )

    # ------------------------------------------------------------------

    def test_full_flow_through_the_api(self):
        clerk = self.make_user(permissions=self.ALL)
        holder = self.make_employee()
        recipient = self.make_employee()
        asset = self.hand_over(self.make_active_asset(), holder)

        created = self.call("post", ENDPOINT, clerk, {
            "asset": asset.pk,
            "target_custody_type": EMPLOYEE,
            "target_employee": recipient.pk,
            "target_location": self.loc_a1.pk,
            "reason": TransferReason.REASSIGNMENT,
            # Diabaikan: read-only.
            "status": TransferStatus.COMPLETED,
            "company": self.company_b.pk,
            "source_employee": recipient.pk,
            "is_cross_company": True,
        })
        self.assertEqual(created.status_code, 201, created.content[:500])

        transfer = AssetTransfer.objects.get(asset=asset, is_deleted=False)
        self.assertEqual(transfer.status, TransferStatus.DRAFT)
        self.assertEqual(transfer.company, self.company_a)
        self.assertEqual(transfer.source_employee, holder)
        self.assertFalse(transfer.is_cross_company)

        submitted = self.call("post", f"{ENDPOINT}{transfer.pk}/submit/", clerk, {})
        self.assertEqual(submitted.status_code, 200, submitted.content[:500])
        self.assertEqual(self.body(submitted)["data"]["status"], TransferStatus.APPROVED)

        edited = self.call("patch", f"{ENDPOINT}{transfer.pk}/", clerk, {"notes": "x"})
        self.assertEqual(edited.status_code, 400)

        missing = self.call("post", f"{ENDPOINT}{transfer.pk}/complete/", clerk, {})
        self.assertEqual(missing.status_code, 400)

        completed = self.call(
            "post",
            f"{ENDPOINT}{transfer.pk}/complete/",
            clerk,
            {"condition": AssetCondition.GOOD},
        )
        self.assertEqual(completed.status_code, 200, completed.content[:500])
        self.assertEqual(self.body(completed)["data"]["status"], TransferStatus.COMPLETED)

        self.assertEqual(self.open_custody(asset).employee, recipient)

        deleted = self.call("delete", f"{ENDPOINT}{transfer.pk}/", clerk)
        self.assertEqual(deleted.status_code, 400)

    def test_storage_to_usage_is_refused_through_the_api(self):
        clerk = self.make_user(permissions=self.ALL)
        asset = self.make_active_asset()

        response = self.call("post", ENDPOINT, clerk, {
            "asset": asset.pk,
            "target_custody_type": EMPLOYEE,
            "target_employee": self.make_employee().pk,
            "target_location": self.loc_a1.pk,
            "reason": TransferReason.REASSIGNMENT,
        })

        self.assertEqual(response.status_code, 400, response.content[:500])
        self.assertFalse(AssetTransfer.objects.filter(asset=asset).exists())

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

    def test_view_is_union_and_actions_follow_their_side(self):
        # Pegawai di site A2 → pegawai di HO A1.
        asset = self.hand_over(self.make_active_asset(), location=self.loc_a2)
        transfer = self.make_transfer(
            asset,
            target_employee=self.make_employee(),
            location=self.loc_a1,
        )

        source_admin = self.admin(self.loc_a2)
        target_admin = self.admin(self.loc_a1)
        third_admin = self.admin(self.loc_a3)

        listing = f"{ENDPOINT}?page_size=500"
        detail = f"{ENDPOINT}{transfer.pk}/"

        # Lihat: asal atau tujuan.
        self.assertIn(transfer.pk, self.ids(self.call("get", listing, source_admin)))
        self.assertIn(transfer.pk, self.ids(self.call("get", listing, target_admin)))
        self.assertNotIn(transfer.pk, self.ids(self.call("get", listing, third_admin)))
        self.assertEqual(self.call("get", detail, third_admin).status_code, 404)

        # Sunting draft + submit: hanya asal.
        self.assertEqual(
            self.call("patch", detail, target_admin, {"notes": "x"}).status_code,
            404,
        )
        self.assertEqual(
            self.call("post", f"{detail}submit/", target_admin, {}).status_code,
            404,
        )

        transfer.refresh_from_db()
        self.assertEqual(transfer.status, TransferStatus.DRAFT)

        submitted = self.call("post", f"{detail}submit/", source_admin, {})
        self.assertEqual(submitted.status_code, 200, submitted.content[:500])

        # Complete: hanya tujuan — pembuat sisi asal tidak bisa.
        payload = {"condition": AssetCondition.GOOD}

        self.assertEqual(
            self.call("post", f"{detail}complete/", source_admin, payload).status_code,
            404,
        )

        done = self.call("post", f"{detail}complete/", target_admin, payload)
        self.assertEqual(done.status_code, 200, done.content[:500])

        # Sesudah complete tetap terlihat di kedua sisi.
        self.assertIn(transfer.pk, self.ids(self.call("get", listing, source_admin)))
        self.assertIn(transfer.pk, self.ids(self.call("get", listing, target_admin)))

    def test_cancel_is_source_side(self):
        asset = self.hand_over(self.make_active_asset(), location=self.loc_a2)
        transfer = self.make_transfer(
            asset,
            target_employee=self.make_employee(),
            location=self.loc_a1,
        )
        AssetTransferService.submit(transfer=transfer)

        detail = f"{ENDPOINT}{transfer.pk}/"

        self.assertEqual(
            self.call("post", f"{detail}cancel/", self.admin(self.loc_a1), {}).status_code,
            404,
        )

        cancelled = self.call("post", f"{detail}cancel/", self.admin(self.loc_a2), {})
        self.assertEqual(cancelled.status_code, 200, cancelled.content[:500])
        self.assertIsNone(self.reservation_of(asset))

    def test_same_location_transfer_one_scope_covers_both_sides(self):
        pic_a = self.make_employee()
        lv = self.vehicle(pic=pic_a, location=self.loc_a2)
        transfer = self.make_transfer(
            lv,
            to=ORGANIZATION,
            target_department=self.dept_a_mining,
            target_pic_employee=self.make_employee(),
            location=self.loc_a2,
        )

        site_admin = self.admin(self.loc_a2)
        detail = f"{ENDPOINT}{transfer.pk}/"

        self.assertEqual(self.call("post", f"{detail}submit/", site_admin, {}).status_code, 200)

        done = self.call(
            "post",
            f"{detail}complete/",
            site_admin,
            {"condition": AssetCondition.GOOD},
        )
        self.assertEqual(done.status_code, 200, done.content[:500])

    def test_cross_company_recipient_admin_sees_nothing(self):
        transfer = self.make_transfer(
            self.hand_over(self.make_active_asset()),
            target_employee=self.make_employee(company=self.company_b),
            cross_company_reason="Pinjam holding",
        )
        self.run_through(transfer)

        recipient_admin = self.make_user(
            permissions=("view_assettransfer", "view_asset"),
            authorities=[("company", self.company_b.pk)],
        )

        self.assertNotIn(
            transfer.pk,
            self.ids(self.call("get", f"{ENDPOINT}?page_size=500", recipient_admin)),
        )
        self.assertNotIn(
            transfer.asset_id,
            self.ids(self.call("get", "/api/assets/assets/?page_size=500", recipient_admin)),
        )

    def test_workflow_actions_need_their_own_permissions(self):
        drafter = self.make_user(permissions=(
            "view_assettransfer",
            "add_assettransfer",
            "change_assettransfer",
        ))
        transfer = self.make_transfer(
            self.hand_over(self.make_active_asset()),
            target_employee=self.make_employee(),
        )

        submitted = self.call("post", f"{ENDPOINT}{transfer.pk}/submit/", drafter, {})
        self.assertIn(submitted.status_code, (403, 404))

        transfer.refresh_from_db()
        self.assertEqual(transfer.status, TransferStatus.DRAFT)

    def test_holders_get_no_access_from_holding(self):
        holder_user = self.make_user()
        holder = self.make_employee(user=holder_user)
        self.make_transfer(
            self.hand_over(self.make_active_asset(), holder),
            target_employee=self.make_employee(),
        )

        self.assertEqual(self.call("get", ENDPOINT, holder_user).status_code, 403)

    def test_transferable_assets_lookup(self):
        viewer = self.make_user(permissions=("view_asset",))

        employee = self.make_employee()
        in_use = self.hand_over(self.make_active_asset(), employee)
        in_department = self.vehicle()
        in_storage = self.make_active_asset()

        damaged_in_use = self.hand_over(self.make_active_asset())
        AssetService.record_condition(asset=damaged_in_use, condition=AssetCondition.DAMAGED)

        damaged_in_storage = self.make_active_asset()
        AssetService.record_condition(
            asset=damaged_in_storage,
            condition=AssetCondition.UNSERVICEABLE,
        )

        reserved = self.hand_over(self.make_active_asset())
        AssetTransferService.submit(
            transfer=self.make_transfer(reserved, target_employee=self.make_employee()),
        )

        draft = self.make_asset()

        def offered(params=""):
            response = self.call("get", f"{TRANSFERABLE}?page_size=1000{params}", viewer)
            self.assertEqual(response.status_code, 200, response.content[:500])

            return {row["value"] for row in self.body(response)["results"]}

        everything = offered()

        self.assertLessEqual(
            {in_use.pk, in_department.pk, in_storage.pk, damaged_in_storage.pk},
            everything,
        )
        self.assertNotIn(damaged_in_use.pk, everything)
        self.assertNotIn(reserved.pk, everything)
        self.assertNotIn(draft.pk, everything)

        self.assertEqual(
            offered(f"&employee_id={employee.pk}") & {in_use.pk, in_department.pk},
            {in_use.pk},
        )

        storage_only = offered(f"&custody_type={STORAGE}")
        self.assertIn(in_storage.pk, storage_only)
        self.assertNotIn(in_use.pk, storage_only)

        outsider = self.make_user()
        response = self.call("get", f"{TRANSFERABLE}?page_size=1000", outsider)
        self.assertEqual(self.body(response)["results"], [])

    def test_ui_schema_declares_transfer_actions(self):
        viewer = self.make_user(permissions=("view_assettransfer",))

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
        self.assertEqual(schema["fields"]["asset"]["lookup_endpoint"], TRANSFERABLE)


# ======================================================================
# Batas modul
# ======================================================================


class TransferBoundaryTests(TransferTestCase):
    def test_transfer_does_not_touch_finance_scm_or_hr_placement(self):
        from apps.assets.services.operations import asset_transfer

        source = open(asset_transfer.__file__).read()

        for forbidden in ("apps.finance", "apps.scm", "AccountingEvent"):
            self.assertNotIn(forbidden, source)

        employee = self.make_employee(location=self.loc_a1)
        before = (employee.organization.company_id, employee.organization.location_id)

        self.run_through(self.make_transfer(
            self.hand_over(self.make_active_asset()),
            target_employee=employee,
            location=self.loc_a2,
        ))

        employee.organization.refresh_from_db()
        self.assertEqual(
            (employee.organization.company_id, employee.organization.location_id),
            before,
        )
