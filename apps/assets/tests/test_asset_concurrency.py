"""
Race nyata — dua koneksi database sungguhan, bukan simulasi.

Test biasa berjalan di dalam transaksi yang di-rollback, dan baris yang
belum di-commit tidak terlihat oleh koneksi lain, jadi race tidak bisa
diuji di sana. Kelas di sini karena itu **mematikan atomik test**
(`_enter_atomics` kosong): data dibuat ter-commit di schema test
`fast_assets`, lalu dibersihkan sendiri di `addCleanup`. Tidak memakai
`TransactionTestCase` — flush-nya mengosongkan tabel `public`, termasuk
baris tenant milik kelas lain.

Yang dibuktikan di tiap race: tepat satu pemanggil berhasil, yang lain
ditolak dengan `ValidationError` (bukan `IntegrityError`, bukan sukses
ganda), dan aset berakhir dengan tepat satu custody terbuka.
"""

from __future__ import annotations

import threading
import uuid

from unittest import mock

from django.core.exceptions import ValidationError
from django.db import connection
from django_tenants.utils import schema_context

from apps.assets.models import (
    Asset,
    AssetAssignment,
    AssetCategory,
    AssetCondition,
    AssetConditionLog,
    AssetCustody,
    AssetOperationReservation,
    AssetOperationType,
    AssetReturn,
    AssetStatus,
    AssetTransfer,
    AssignmentStatus,
    CustodyType,
    ReturnStatus,
    TransferStatus,
)
from apps.assets.services import (
    AssetAssignmentService,
    AssetCategoryService,
    AssetReservationService,
    AssetReturnService,
    AssetService,
    AssetTransferService,
)
from apps.hr.models import Employee, OrganizationAssignment

from .base import AssetsTestCase


class CommittedRaceTestCase(AssetsTestCase):
    @classmethod
    def _enter_atomics(cls):
        return {}

    @classmethod
    def _rollback_atomics(cls, atomics):
        return None

    def setUp(self):
        super().setUp()

        # Satu pembersih, didaftarkan paling awal supaya berjalan paling
        # akhir — dan urutannya sendiri yang mengikuti FK PROTECT: aset
        # (custody, dokumen) dulu, baru pegawai yang ditunjuknya.
        self._assets: list[tuple[int, int]] = []
        self._employees: list[int] = []
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        for asset_pk, category_pk in self._assets:
            self._cleanup_asset(asset_pk, category_pk)

        for employee_pk in self._employees:
            self._cleanup_employee(employee_pk)

    # ------------------------------------------------------------------

    def committed_asset(self) -> Asset:
        suffix = uuid.uuid4().hex[:8].upper()

        category = AssetCategoryService.create(
            data={"code": f"RACE-{suffix}", "name": "Race"},
        )
        asset = AssetService.create(data={
            "company": self.company_a,
            "location": self.loc_a1,
            "category": category,
            "name": "Race asset",
        })

        self._assets.append((asset.pk, category.pk))

        return asset

    def committed_employee(self) -> Employee:
        employee = self.make_employee()
        self._employees.append(employee.pk)

        return employee

    @staticmethod
    def _cleanup_asset(asset_pk, category_pk):
        # Urutan mengikuti FK PROTECT. QuerySet.delete() dipakai untuk log
        # kondisi karena `AssetConditionLog.delete()` sengaja menolak.
        AssetTransfer.objects.filter(asset_id=asset_pk).delete()
        AssetReturn.objects.filter(asset_id=asset_pk).delete()
        AssetAssignment.objects.filter(asset_id=asset_pk).delete()
        AssetOperationReservation.objects.filter(asset_id=asset_pk).delete()
        Asset.objects.filter(pk=asset_pk).update(
            current_custody=None,
            status=AssetStatus.DRAFT,
        )
        AssetConditionLog.objects.filter(asset_id=asset_pk).delete()
        AssetCustody.objects.filter(asset_id=asset_pk).delete()
        Asset.objects.filter(pk=asset_pk).delete()
        AssetCategory.objects.filter(pk=category_pk).delete()

    @staticmethod
    def _cleanup_employee(employee_pk):
        OrganizationAssignment.objects.filter(employee_id=employee_pk).delete()
        Employee.objects.filter(pk=employee_pk).delete()

    def race(self, *calls) -> list[str]:
        """Jalankan `calls` bersamaan, masing-masing di koneksinya sendiri."""
        schema_name = connection.schema_name
        barrier = threading.Barrier(len(calls))
        outcomes: list[str] = []
        lock = threading.Lock()

        def run(call):
            try:
                with schema_context(schema_name):
                    barrier.wait(timeout=10)

                    try:
                        call()
                        result = "ok"
                    except ValidationError:
                        result = "rejected"
                    except Exception as exc:  # noqa: BLE001
                        result = f"error:{type(exc).__name__}:{exc}"

                with lock:
                    outcomes.append(result)
            finally:
                connection.close()

        threads = [threading.Thread(target=run, args=(call,)) for call in calls]

        for thread in threads:
            thread.start()

        for thread in threads:
            thread.join(timeout=30)

        return sorted(outcomes)

    def assert_one_open_custody(self, asset) -> AssetCustody:
        open_rows = AssetCustody.objects.filter(
            asset=asset,
            ended_on__isnull=True,
            is_deleted=False,
        )

        self.assertEqual(open_rows.count(), 1)

        asset.refresh_from_db()
        self.assertEqual(asset.current_custody_id, open_rows.get().pk)

        return open_rows.get()


class AssetActivationRaceTests(CommittedRaceTestCase):
    def test_concurrent_activation_opens_one_custody(self):
        asset = self.committed_asset()

        outcomes = self.race(
            lambda: AssetService.activate(asset=Asset(pk=asset.pk)),
            lambda: AssetService.activate(asset=Asset(pk=asset.pk)),
        )

        self.assertEqual(outcomes, ["ok", "rejected"])

        asset.refresh_from_db()
        self.assertEqual(asset.status, AssetStatus.ACTIVE)
        self.assert_one_open_custody(asset)


class AssetAssignmentRaceTests(CommittedRaceTestCase):
    def draft(self, asset, employee) -> AssetAssignment:
        return AssetAssignmentService.create(data={
            "asset": Asset.objects.get(pk=asset.pk),
            "target_custody_type": CustodyType.EMPLOYEE,
            "employee": employee,
            "location": self.loc_a1,
        })

    def test_a_two_assignments_racing_to_reserve_one_asset(self):
        asset = AssetService.activate(asset=self.committed_asset())
        first = self.draft(asset, self.committed_employee())
        second = self.draft(asset, self.committed_employee())

        outcomes = self.race(
            lambda: AssetAssignmentService.submit(assignment=first),
            lambda: AssetAssignmentService.submit(assignment=second),
        )

        self.assertEqual(outcomes, ["ok", "rejected"])
        self.assertEqual(
            AssetAssignment.objects.filter(
                asset=asset,
                status__in=(AssignmentStatus.SUBMITTED, AssignmentStatus.APPROVED),
            ).count(),
            1,
        )

    def test_b_two_completions_of_one_assignment(self):
        asset = AssetService.activate(asset=self.committed_asset())
        assignment = self.draft(asset, self.committed_employee())
        AssetAssignmentService.submit(assignment=assignment)

        outcomes = self.race(
            lambda: AssetAssignmentService.complete(
                assignment=AssetAssignment(pk=assignment.pk),
            ),
            lambda: AssetAssignmentService.complete(
                assignment=AssetAssignment(pk=assignment.pk),
            ),
        )

        self.assertEqual(outcomes, ["ok", "rejected"])

        held = self.assert_one_open_custody(asset)
        self.assertEqual(held.custody_type, CustodyType.EMPLOYEE)
        self.assertEqual(
            AssetCustody.objects.filter(asset=asset).count(),
            2,
        )

    def test_c_d_stale_assignment_racing_a_completion(self):
        asset = AssetService.activate(asset=self.committed_asset())
        winner = self.draft(asset, self.committed_employee())
        stale = self.draft(asset, self.committed_employee())
        AssetAssignmentService.submit(assignment=winner)

        outcomes = self.race(
            lambda: AssetAssignmentService.complete(
                assignment=AssetAssignment(pk=winner.pk),
            ),
            lambda: AssetAssignmentService.submit(
                assignment=AssetAssignment(pk=stale.pk),
            ),
        )

        # Siapa pun yang lebih dulu memegang kunci aset, dokumen basi
        # selalu ditolak: dipesan (complete belum selesai) atau custody
        # sudah berubah (complete sudah selesai).
        self.assertEqual(outcomes, ["ok", "rejected"])

        stale.refresh_from_db()
        self.assertEqual(stale.status, AssignmentStatus.DRAFT)

        held = self.assert_one_open_custody(asset)
        self.assertEqual(held.employee_id, winner.employee_id)

    def test_e_failure_after_close_leaves_committed_state_untouched(self):
        asset = AssetService.activate(asset=self.committed_asset())
        storage_pk = asset.current_custody_id
        assignment = self.draft(asset, self.committed_employee())
        AssetAssignmentService.submit(assignment=assignment)

        target = "apps.assets.services.operations.custody.AssetCustodyService._open"

        with mock.patch(target, side_effect=RuntimeError("open failed")):
            with self.assertRaises(RuntimeError):
                AssetAssignmentService.complete(
                    assignment=AssetAssignment(pk=assignment.pk),
                )

        # Dibaca lewat koneksi baru: yang tersimpan, bukan sisa memori.
        held = self.assert_one_open_custody(asset)
        self.assertEqual(held.pk, storage_pk)
        self.assertEqual(held.custody_type, CustodyType.STORAGE)

        assignment.refresh_from_db()
        self.assertEqual(assignment.status, AssignmentStatus.APPROVED)


class MovementRaceTestCase(CommittedRaceTestCase):
    """
    Race antar dokumen pergerakan (Assignment, Return, Transfer) di atas
    pemesanan bersama. Setiap race berakhir dengan invariant penuh: paling
    banyak satu pemesanan aktif, tepat satu custody terbuka, tidak ada
    setengah pindah, `integrity_issues() == []` untuk custody **dan**
    pemesanan.
    """

    def in_use_asset(self, employee=None) -> Asset:
        asset = AssetService.activate(asset=self.committed_asset())

        return self.hand_over(asset, employee or self.committed_employee())

    def storage_asset(self) -> Asset:
        return AssetService.activate(asset=self.committed_asset())

    def department_asset(self, pic) -> Asset:
        asset = self.storage_asset()

        return self.hand_to_department(asset, self.dept_a_mining, pic=pic)

    @staticmethod
    def active(asset):
        return AssetOperationReservation.objects.filter(
            asset=asset,
            released_at__isnull=True,
        )

    def assert_settled(self, asset) -> AssetCustody:
        from apps.assets.services import AssetCustodyService

        self.assertLessEqual(self.active(asset).count(), 1)
        self.assertEqual(AssetReservationService.integrity_issues(), [])
        self.assertEqual(AssetCustodyService.integrity_issues(), [])

        return self.assert_one_open_custody(asset)

    def to_employee(self, asset, employee=None):
        return self.make_transfer(
            Asset.objects.get(pk=asset.pk),
            target_employee=employee or self.committed_employee(),
        )

    def relocate(self, asset):
        return self.make_transfer(
            Asset.objects.get(pk=asset.pk),
            to=CustodyType.STORAGE,
            location=self.loc_a2,
        )

    @staticmethod
    def submit_transfer(transfer):
        return lambda: AssetTransferService.submit(
            transfer=AssetTransfer(pk=transfer.pk),
        )

    @staticmethod
    def complete_transfer(transfer, condition=AssetCondition.GOOD):
        return lambda: AssetTransferService.complete(
            transfer=AssetTransfer(pk=transfer.pk),
            condition=condition,
        )

    @staticmethod
    def submit_return(asset_return):
        return lambda: AssetReturnService.submit(
            asset_return=AssetReturn(pk=asset_return.pk),
        )


class CrossDocumentRaceTests(MovementRaceTestCase):
    """ASSET-4 — Return vs dokumen lain (sejak ASSET-5 pesaingnya Transfer nyata)."""

    def test_a_return_vs_transfer_on_an_asset_in_use(self):
        asset = self.in_use_asset()
        held = asset.current_custody_id
        asset_return = self.make_return(asset)
        transfer = self.to_employee(asset)

        outcomes = self.race(
            self.submit_return(asset_return),
            self.submit_transfer(transfer),
        )

        self.assertEqual(outcomes, ["ok", "rejected"])

        winner = self.active(asset).get()
        asset_return.refresh_from_db()
        transfer.refresh_from_db()

        if winner.operation_type == AssetOperationType.RETURN:
            self.assertEqual(asset_return.status, ReturnStatus.APPROVED)
            self.assertEqual(transfer.status, TransferStatus.DRAFT)
        else:
            self.assertEqual(transfer.status, TransferStatus.APPROVED)
            self.assertEqual(asset_return.status, ReturnStatus.DRAFT)

        self.assertEqual(self.assert_settled(asset).pk, held)

    def test_b_assignment_vs_storage_transfer(self):
        asset = self.storage_asset()
        assignment = AssetAssignmentService.create(data={
            "asset": Asset.objects.get(pk=asset.pk),
            "target_custody_type": CustodyType.EMPLOYEE,
            "employee": self.committed_employee(),
            "location": self.loc_a1,
        })
        transfer = self.relocate(asset)

        outcomes = self.race(
            lambda: AssetAssignmentService.submit(
                assignment=AssetAssignment(pk=assignment.pk),
            ),
            self.submit_transfer(transfer),
        )

        self.assertEqual(outcomes, ["ok", "rejected"])
        self.assertEqual(self.active(asset).count(), 1)
        self.assertEqual(self.assert_settled(asset).custody_type, CustodyType.STORAGE)

    def test_c_two_returns_racing_to_reserve(self):
        asset = self.in_use_asset()
        first = self.make_return(asset)
        second = self.make_return(asset)

        outcomes = self.race(self.submit_return(first), self.submit_return(second))

        self.assertEqual(outcomes, ["ok", "rejected"])
        self.assertEqual(
            AssetReturn.objects.filter(asset=asset, status=ReturnStatus.APPROVED).count(),
            1,
        )
        self.assertEqual(self.active(asset).count(), 1)
        self.assert_settled(asset)

    def test_d_return_completion_vs_stale_return(self):
        asset = self.in_use_asset()
        winner = self.make_return(asset)
        stale = self.make_return(asset)
        AssetReturnService.submit(asset_return=winner)

        outcomes = self.race(
            lambda: AssetReturnService.complete(
                asset_return=AssetReturn(pk=winner.pk),
                condition=AssetCondition.GOOD,
            ),
            self.submit_return(stale),
        )

        self.assertEqual(outcomes, ["ok", "rejected"])

        stale.refresh_from_db()
        self.assertEqual(stale.status, ReturnStatus.DRAFT)

        storage = self.assert_settled(asset)
        self.assertEqual(storage.custody_type, CustodyType.STORAGE)
        self.assertEqual(storage.opened_by_id, str(winner.pk))
        self.assertFalse(self.active(asset).exists())

    def test_d_return_completion_vs_transfer_submit(self):
        asset = self.in_use_asset()
        asset_return = self.make_return(asset)
        transfer = self.to_employee(asset)
        AssetReturnService.submit(asset_return=asset_return)

        outcomes = self.race(
            lambda: AssetReturnService.complete(
                asset_return=AssetReturn(pk=asset_return.pk),
                condition=AssetCondition.FAIR,
            ),
            self.submit_transfer(transfer),
        )

        # Transfer selalu kalah: dipesan Return (sebelum commit) atau basi
        # (custody sudah STORAGE sesudah commit).
        self.assertEqual(outcomes, ["ok", "rejected"])

        transfer.refresh_from_db()
        self.assertEqual(transfer.status, TransferStatus.DRAFT)

        storage = self.assert_settled(asset)
        self.assertEqual(storage.custody_type, CustodyType.STORAGE)
        self.assertEqual(storage.opened_by_id, str(asset_return.pk))
        self.assertFalse(self.active(asset).exists())

    def test_e_return_failure_after_close_keeps_source_and_reservation(self):
        asset = self.in_use_asset()
        held = asset.current_custody_id
        asset_return = self.make_return(asset)
        AssetReturnService.submit(asset_return=asset_return)

        target = "apps.assets.services.operations.custody.AssetCustodyService._open"

        with mock.patch(target, side_effect=RuntimeError("open failed")):
            with self.assertRaises(RuntimeError):
                AssetReturnService.complete(
                    asset_return=AssetReturn(pk=asset_return.pk),
                    condition=AssetCondition.DAMAGED,
                )

        source = self.assert_settled(asset)
        self.assertEqual(source.pk, held)
        self.assertIsNone(source.ended_on)

        asset_return.refresh_from_db()
        self.assertEqual(asset_return.status, ReturnStatus.APPROVED)

        reservation = self.active(asset).get()
        self.assertEqual(
            (reservation.operation_type, reservation.document_id),
            (AssetOperationType.RETURN, asset_return.pk),
        )

        asset.refresh_from_db()
        self.assertEqual(asset.condition, AssetCondition.GOOD)

    def test_f_return_cancel_then_transfer_immediately(self):
        asset = self.in_use_asset()
        first = self.make_return(asset)
        transfer = self.to_employee(asset)
        AssetReturnService.submit(asset_return=first)

        outcomes = self.race(
            lambda: AssetReturnService.cancel(asset_return=AssetReturn(pk=first.pk)),
            self.submit_transfer(transfer),
        )

        # Cancel selalu sukses; Transfer menang hanya bila datang sesudah
        # pelepasan ter-commit.
        self.assertIn(outcomes, (["ok", "ok"], ["ok", "rejected"]))
        self.assert_settled(asset)

        transfer.refresh_from_db()

        if transfer.status == TransferStatus.DRAFT:
            AssetTransferService.submit(transfer=transfer)

        self.assertEqual(self.active(asset).get().document_id, transfer.pk)

        AssetTransferService.complete(transfer=transfer, condition=AssetCondition.GOOD)

        self.assertFalse(self.active(asset).exists())
        self.assertEqual(
            self.assert_settled(asset).employee_id,
            transfer.target_employee_id,
        )


class TransferRaceTests(MovementRaceTestCase):
    """ASSET-5 — Transfer di atas pemesanan bersama (A–H)."""

    def test_a_assignment_vs_transfer_on_storage(self):
        asset = self.storage_asset()
        assignment = AssetAssignmentService.create(data={
            "asset": Asset.objects.get(pk=asset.pk),
            "target_custody_type": CustodyType.EMPLOYEE,
            "employee": self.committed_employee(),
            "location": self.loc_a1,
        })
        transfer = self.relocate(asset)

        outcomes = self.race(
            self.submit_transfer(transfer),
            lambda: AssetAssignmentService.submit(
                assignment=AssetAssignment(pk=assignment.pk),
            ),
        )

        self.assertEqual(outcomes, ["ok", "rejected"])

        transfer.refresh_from_db()
        assignment.refresh_from_db()

        self.assertEqual(
            sorted([transfer.status, assignment.status]),
            ["APPROVED", "DRAFT"],
        )
        self.assertEqual(self.assert_settled(asset).custody_type, CustodyType.STORAGE)

    def test_b_return_vs_transfer_on_asset_in_use(self):
        asset = self.in_use_asset()
        held = asset.current_custody_id
        transfer = self.to_employee(asset)
        asset_return = self.make_return(asset)

        outcomes = self.race(
            self.submit_transfer(transfer),
            self.submit_return(asset_return),
        )

        self.assertEqual(outcomes, ["ok", "rejected"])
        self.assertEqual(self.active(asset).count(), 1)
        self.assertEqual(self.assert_settled(asset).pk, held)

    def test_c_two_transfers_racing_to_reserve(self):
        asset = self.in_use_asset()
        first = self.to_employee(asset)
        second = self.to_employee(asset)

        outcomes = self.race(self.submit_transfer(first), self.submit_transfer(second))

        self.assertEqual(outcomes, ["ok", "rejected"])
        self.assertEqual(
            AssetTransfer.objects.filter(
                asset=asset,
                status=TransferStatus.APPROVED,
            ).count(),
            1,
        )
        self.assert_settled(asset)

    def test_d_transfer_completion_vs_stale_transfer(self):
        asset = self.in_use_asset()
        winner = self.to_employee(asset)
        stale = self.to_employee(asset)
        AssetTransferService.submit(transfer=winner)

        outcomes = self.race(
            self.complete_transfer(winner),
            self.submit_transfer(stale),
        )

        self.assertEqual(outcomes, ["ok", "rejected"])

        stale.refresh_from_db()
        self.assertEqual(stale.status, TransferStatus.DRAFT)

        held = self.assert_settled(asset)
        self.assertEqual(held.employee_id, winner.target_employee_id)
        self.assertFalse(self.active(asset).exists())

        # Draft lama tetap basi untuk selamanya.
        with self.assertRaises(ValidationError):
            AssetTransferService.submit(transfer=stale)

    def test_e_transfer_completion_vs_competing_return(self):
        asset = self.in_use_asset()
        transfer = self.to_employee(asset)
        asset_return = self.make_return(asset)
        AssetTransferService.submit(transfer=transfer)

        outcomes = self.race(
            self.complete_transfer(transfer),
            self.submit_return(asset_return),
        )

        # Return kalah: dipesan Transfer, atau basi sesudah Transfer selesai.
        self.assertEqual(outcomes, ["ok", "rejected"])

        asset_return.refresh_from_db()
        self.assertEqual(asset_return.status, ReturnStatus.DRAFT)

        held = self.assert_settled(asset)
        self.assertEqual(held.employee_id, transfer.target_employee_id)
        self.assertEqual(held.opened_by_type, "asset_transfer")

    def test_f_failure_after_close_rolls_back_fully(self):
        asset = self.in_use_asset()
        held = asset.current_custody_id
        transfer = self.to_employee(asset)
        AssetTransferService.submit(transfer=transfer)

        target = "apps.assets.services.operations.custody.AssetCustodyService._open"

        with mock.patch(target, side_effect=RuntimeError("open failed")):
            with self.assertRaises(RuntimeError):
                AssetTransferService.complete(
                    transfer=AssetTransfer(pk=transfer.pk),
                    condition=AssetCondition.FAIR,
                )

        source = self.assert_settled(asset)
        self.assertEqual(source.pk, held)
        self.assertIsNone(source.ended_on)
        self.assertEqual(
            AssetCustody.objects.filter(asset=asset).count(),
            2,  # STORAGE awal (tertutup) + pemakaian (terbuka)
        )

        transfer.refresh_from_db()
        self.assertEqual(transfer.status, TransferStatus.APPROVED)
        self.assertIsNone(transfer.resulting_custody_id)

        reservation = self.active(asset).get()
        self.assertEqual(
            (reservation.operation_type, reservation.document_id),
            (AssetOperationType.TRANSFER, transfer.pk),
        )

        asset.refresh_from_db()
        self.assertEqual(asset.condition, AssetCondition.GOOD)

    def test_g_transfer_cancel_then_next_operation_immediately(self):
        asset = self.storage_asset()
        transfer = self.relocate(asset)
        assignment = AssetAssignmentService.create(data={
            "asset": Asset.objects.get(pk=asset.pk),
            "target_custody_type": CustodyType.EMPLOYEE,
            "employee": self.committed_employee(),
            "location": self.loc_a1,
        })
        AssetTransferService.submit(transfer=transfer)

        outcomes = self.race(
            lambda: AssetTransferService.cancel(transfer=AssetTransfer(pk=transfer.pk)),
            lambda: AssetAssignmentService.submit(
                assignment=AssetAssignment(pk=assignment.pk),
            ),
        )

        self.assertIn(outcomes, (["ok", "ok"], ["ok", "rejected"]))
        self.assert_settled(asset)

        transfer.refresh_from_db()
        self.assertEqual(transfer.status, TransferStatus.CANCELLED)

        assignment.refresh_from_db()

        if assignment.status == AssignmentStatus.DRAFT:
            AssetAssignmentService.submit(assignment=assignment)

        self.assertEqual(self.active(asset).get().document_id, assignment.pk)

        AssetAssignmentService.complete(assignment=assignment)

        self.assertFalse(self.active(asset).exists())
        self.assertEqual(self.assert_settled(asset).custody_type, CustodyType.EMPLOYEE)

    def test_h_pic_only_transfers_race(self):
        first_pic = self.committed_employee()
        asset = self.department_asset(first_pic)

        def pic_change(pic):
            return self.make_transfer(
                Asset.objects.get(pk=asset.pk),
                to=CustodyType.ORGANIZATION,
                target_department=self.dept_a_mining,
                target_pic_employee=pic,
            )

        to_b = pic_change(self.committed_employee())
        to_c = pic_change(self.committed_employee())

        outcomes = self.race(self.submit_transfer(to_b), self.submit_transfer(to_c))
        self.assertEqual(outcomes, ["ok", "rejected"])

        winner = to_b if self.active(asset).get().document_id == to_b.pk else to_c
        loser = to_c if winner is to_b else to_b

        outcomes = self.race(
            self.complete_transfer(winner),
            self.submit_transfer(loser),
        )
        self.assertEqual(outcomes, ["ok", "rejected"])

        held = self.assert_settled(asset)
        self.assertEqual(held.custody_type, CustodyType.ORGANIZATION)
        self.assertEqual(held.department_id, self.dept_a_mining.pk)
        self.assertEqual(held.pic_employee_id, winner.target_pic_employee_id)
        self.assertFalse(self.active(asset).exists())
