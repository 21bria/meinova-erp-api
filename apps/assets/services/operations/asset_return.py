"""
Service Asset Return (`docs/claude/assets.md` §11, §16, §18, §26).

Lifecycle — sama dengan Assignment:

    DRAFT ─submit─▶ SUBMITTED ─approve─▶ APPROVED ─complete─▶ COMPLETED
      ▲               │  └─reject─▶ REJECTED        │
      └─(RETURNED)────┘                              └─cancel─▶ CANCELLED
                      └──────────── cancel ─────────────────────▲

* Asal = custody **pemakaian** (EMPLOYEE/ORGANIZATION) yang sedang
  terbuka, dibaca ulang dari database — bukan dari objek pemanggil, bukan
  dari klien. Aset di STORAGE tidak bisa di-Return.
* Tujuan = penyimpanan (STORAGE) di lokasi milik company pemilik; boleh
  lokasi asal maupun lokasi lain milik company itu.
* Pemesanan lewat `AssetReservationService` (authority bersama dengan
  Assignment dan kelak Transfer).
* **APPROVED tidak memindahkan custody.** Hanya `complete`: tutup custody
  pemakaian → buka STORAGE → salinan lokasi aset → log kondisi RETURN,
  satu transaksi.
* Kondisi kembali **wajib** saat complete. DAMAGED/UNSERVICEABLE tetap
  kembali ke STORAGE; tidak ada dispose, write-off, maintenance, atau
  event Finance otomatis.
* Pemanggil sistem kelak (offboarding, §19) memakai `create` + `submit`
  yang sama — tidak ada jalan pintas yang menutup custody langsung.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.administration.api.numbering.services.numbering_service import (
    DocumentNumberService,
)
from apps.assets.models import (
    RETURN_RESERVING_STATUSES,
    Asset,
    AssetCondition,
    AssetCustody,
    AssetOperationType,
    AssetReturn,
    AssetStatus,
    ConditionSource,
    CustodyType,
    ReservationRelease,
    ReturnStatus,
)
from apps.core.services.master import BaseMasterService

from .asset import AssetService
from .custody import AssetCustodyService, CustodyTarget
from .movement import assert_may, key, lock_asset, reject_system_fields
from .reservation import AssetReservationService


WORKFLOW_MODULE = "assets"
WORKFLOW_DOCUMENT_TYPE = "asset_return"
OPERATION = AssetOperationType.RETURN

SUBMIT_PERMISSION = "assets.submit_assetreturn"
COMPLETE_PERMISSION = "assets.complete_assetreturn"
CANCEL_PERMISSION = "assets.cancel_assetreturn"

IN_USE = (CustodyType.EMPLOYEE, CustodyType.ORGANIZATION)

# Diisi sistem — tidak pernah dari klien, juga lewat jalur non-HTTP.
SYSTEM_FIELDS = (
    "document_number",
    "status",
    "company",
    "source_custody",
    "source_custody_type",
    "source_location",
    "source_facility",
    "source_employee",
    "source_department",
    "source_pic_employee",
    "return_date",
    "return_condition",
    "resulting_custody",
    "submitted_at",
    "approved_at",
    "rejected_at",
    "cancelled_at",
    "completed_at",
    "completed_by",
)

DESTINATION_FIELDS = ("asset", "destination_location", "destination_facility")


class AssetReturnService(BaseMasterService):
    model = AssetReturn

    @classmethod
    def list(cls):
        return cls.get_queryset().select_related(
            "company",
            "asset",
            "asset__category",
            "source_location",
            "source_facility",
            "source_employee",
            "source_department",
            "source_pic_employee",
            "destination_location",
            "destination_facility",
        )

    # ------------------------------------------------------------------
    # Draft
    # ------------------------------------------------------------------

    @classmethod
    def prepare_create_data(cls, *, data: dict[str, Any], user=None, **kwargs):
        reject_system_fields(data, SYSTEM_FIELDS)

        asset = data.get("asset")

        if asset is None:
            raise ValidationError({"asset": "Aset wajib dipilih."})

        source = cls._source_of(asset)
        data.update(source)

        cls._assert_destination(
            company_id=source["company"].pk,
            location=data.get("destination_location"),
            facility=data.get("destination_facility"),
        )

        data["status"] = ReturnStatus.DRAFT
        data["document_number"] = DocumentNumberService.next(
            module=WORKFLOW_MODULE,
            document_type=WORKFLOW_DOCUMENT_TYPE,
            company=source["company"],
        )

        return data

    @classmethod
    def prepare_update_data(
        cls,
        *,
        instance: AssetReturn,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ):
        reject_system_fields(data, SYSTEM_FIELDS, instance=instance)

        if instance.status != ReturnStatus.DRAFT:
            raise ValidationError({
                "status": "Hanya dokumen DRAFT yang bisa disunting.",
            })

        merged = {
            name: data.get(name, getattr(instance, name))
            for name in DESTINATION_FIELDS
        }

        company_id = instance.company_id

        # Aset diganti di draft = asal ikut dibaca ulang.
        if key(merged["asset"]) != instance.asset_id:
            source = cls._source_of(merged["asset"])
            data.update(source)
            company_id = source["company"].pk

        cls._assert_destination(
            company_id=company_id,
            location=merged["destination_location"],
            facility=merged["destination_facility"],
        )

        return data

    @classmethod
    def before_soft_delete(cls, *, instance, user=None, **kwargs) -> None:
        if instance.status != ReturnStatus.DRAFT:
            raise ValidationError({
                "status": (
                    "Hanya dokumen DRAFT yang bisa dihapus. Dokumen yang "
                    "sudah diajukan dibatalkan lewat Cancel."
                ),
            })

    # ------------------------------------------------------------------
    # Submit
    # ------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def submit(cls, *, asset_return: AssetReturn, user=None, notes: str = ""):
        """
        DRAFT → SUBMITTED (atau langsung APPROVED tanpa alur). Memesan aset.
        Urutan kunci: dokumen → aset → pemesanan, sama dengan Assignment.
        """
        assert_may(user, SUBMIT_PERMISSION, "mengajukan Return")

        locked = cls._lock(asset_return)

        if locked.status != ReturnStatus.DRAFT:
            raise ValidationError({"status": "Dokumen ini sudah diajukan."})

        asset = lock_asset(locked.asset_id)

        cls._assert_source_current(locked, asset)
        cls._assert_destination(
            company_id=locked.company_id,
            location=locked.destination_location,
            facility=locked.destination_facility,
        )

        AssetReservationService.acquire(
            asset_id=asset.pk,
            operation_type=OPERATION,
            document_id=locked.pk,
            document_number=locked.document_number,
            user=user,
        )

        definition = cls._find_definition(locked)

        now = timezone.now()

        locked.status = (
            ReturnStatus.SUBMITTED
            if definition is not None
            else ReturnStatus.APPROVED
        )
        locked.submitted_at = now
        locked.updated_by = user

        if definition is None:
            locked.approved_at = now

        locked.save()

        cls._audit(
            instance=locked,
            action="update",
            user=user,
            before={"status": ReturnStatus.DRAFT},
            after={"status": locked.status},
        )

        if definition is None:
            return None

        from apps.workflow.services.workflow_service import WorkflowService

        return WorkflowService.submit(
            document=locked,
            module=WORKFLOW_MODULE,
            document_type=WORKFLOW_DOCUMENT_TYPE,
            # Subjek: pemegang lama (EMPLOYEE) atau PIC (ORGANIZATION) —
            # bukan approver; mejanya ditentukan alur.
            employee=locked.source_employee or locked.source_pic_employee,
            user=user,
            context=cls.workflow_context(locked),
            document_number=locked.document_number,
            document_label=cls.workflow_label(locked),
            notes=notes,
            scope=cls._workflow_scope(locked),
            initiator_employee=getattr(user, "employee_profile", None),
            on_complete=lambda wf, status: cls.on_workflow_done(
                asset_return=locked,
                status=status,
                user=user,
            ),
        )

    # ------------------------------------------------------------------
    # Keputusan alur
    # ------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def decide(
        cls,
        *,
        asset_return: AssetReturn,
        approved: bool,
        user=None,
        notes: str = "",
    ):
        """Approve/reject dari layar dokumen. Hak memutuskan milik engine."""
        from apps.workflow.services.workflow_service import WorkflowService

        workflow = cls.workflow_for(asset_return)

        if workflow is None:
            raise ValidationError({
                "status": "Dokumen ini tidak sedang menunggu persetujuan.",
            })

        handler = WorkflowService.approve if approved else WorkflowService.reject

        return handler(
            instance=workflow,
            user=user,
            comment=notes,
            on_complete=lambda wf, status: cls.on_workflow_done(
                asset_return=asset_return,
                status=status,
                user=user,
            ),
        )

    @classmethod
    def on_workflow_done(cls, *, asset_return, status, user=None):
        """
        Dipanggil engine saat alurnya berhenti. Hanya dokumen yang masih
        SUBMITTED yang digerakkan; setiap jalan keluar selain APPROVED
        melepas pemesanan di transaksi yang sama.
        """
        from apps.workflow.models import InstanceStatus

        mapping = {
            InstanceStatus.APPROVED: (ReturnStatus.APPROVED, None),
            InstanceStatus.REJECTED: (
                ReturnStatus.REJECTED,
                ReservationRelease.REJECTED,
            ),
            InstanceStatus.RETURNED: (
                ReturnStatus.DRAFT,
                ReservationRelease.RETURNED_TO_DRAFT,
            ),
            InstanceStatus.CANCELLED: (
                ReturnStatus.CANCELLED,
                ReservationRelease.CANCELLED,
            ),
        }

        if status not in mapping:
            return asset_return

        target, release = mapping[status]

        locked = cls._lock(asset_return)

        if locked.status != ReturnStatus.SUBMITTED:
            return locked

        stamps = {
            ReturnStatus.APPROVED: "approved_at",
            ReturnStatus.REJECTED: "rejected_at",
            ReturnStatus.CANCELLED: "cancelled_at",
        }

        fields = ["status", "updated_by", "updated_at"]

        locked.status = target
        locked.updated_by = user

        if target in stamps:
            setattr(locked, stamps[target], timezone.now())
            fields.append(stamps[target])

        locked.save(update_fields=fields)

        if release is not None:
            AssetReservationService.release(
                operation_type=OPERATION,
                document_id=locked.pk,
                reason=release,
                user=user,
            )

        cls._audit(
            instance=locked,
            action="update",
            user=user,
            before={"status": ReturnStatus.SUBMITTED},
            after={"status": target},
        )

        return locked

    # ------------------------------------------------------------------
    # Cancel
    # ------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def cancel(cls, *, asset_return: AssetReturn, user=None, notes: str = ""):
        """SUBMITTED/APPROVED → CANCELLED, melepas pemesanan."""
        assert_may(user, CANCEL_PERMISSION, "membatalkan Return")

        locked = cls._lock(asset_return)

        if locked.status not in RETURN_RESERVING_STATUSES:
            raise ValidationError({
                "status": (
                    "Hanya dokumen yang sedang berjalan (Submitted/Approved) "
                    "yang bisa dibatalkan."
                ),
            })

        previous = locked.status

        workflow = cls.workflow_for(locked)

        if workflow is not None:
            from apps.workflow.services.workflow_service import WorkflowService

            WorkflowService.cancel(instance=workflow, user=user, comment=notes)

        locked.status = ReturnStatus.CANCELLED
        locked.cancelled_at = timezone.now()
        locked.updated_by = user

        if notes:
            locked.notes = f"{locked.notes}\n{notes}".strip()

        locked.save(update_fields=[
            "status",
            "cancelled_at",
            "updated_by",
            "updated_at",
            "notes",
        ])

        AssetReservationService.release(
            operation_type=OPERATION,
            document_id=locked.pk,
            reason=ReservationRelease.CANCELLED,
            user=user,
        )

        cls._audit(
            instance=locked,
            action="update",
            user=user,
            before={"status": previous},
            after={"status": ReturnStatus.CANCELLED},
        )

        return locked

    # ------------------------------------------------------------------
    # Complete — satu-satunya titik custody berpindah
    # ------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def complete(
        cls,
        *,
        asset_return: AssetReturn,
        condition: str,
        user=None,
        return_date=None,
        note: str = "",
    ) -> AssetReturn:
        """
        Barang diterima kembali di penyimpanan. `condition` wajib — kondisi
        saat kembali selalu diketahui dan selalu masuk riwayat (RETURN),
        juga bila nilainya sama dengan sebelumnya.
        """
        assert_may(user, COMPLETE_PERMISSION, "menyelesaikan pengembalian")

        locked = cls._lock(asset_return)

        if locked.status == ReturnStatus.COMPLETED:
            raise ValidationError({"status": "Pengembalian ini sudah selesai."})

        if locked.status != ReturnStatus.APPROVED:
            raise ValidationError({
                "status": "Pengembalian hanya bisa diselesaikan sesudah disetujui.",
            })

        if not condition:
            raise ValidationError({
                "condition": "Kondisi aset saat dikembalikan wajib diisi.",
            })

        if condition not in AssetCondition.values:
            raise ValidationError({"condition": "Kondisi tidak dikenal."})

        on = return_date or timezone.localdate()

        asset = lock_asset(locked.asset_id)

        cls._assert_source_current(locked, asset)

        AssetReservationService.assert_held(
            asset_id=asset.pk,
            operation_type=OPERATION,
            document_id=locked.pk,
        )

        cls._assert_destination(
            company_id=locked.company_id,
            location=locked.destination_location,
            facility=locked.destination_facility,
        )

        cls._assert_return_date(on, locked.source_custody)

        custody = AssetCustodyService.move(
            asset_id=asset.pk,
            expected_custody_id=locked.source_custody_id,
            target=CustodyTarget(
                custody_type=CustodyType.STORAGE,
                location=locked.destination_location,
                facility=locked.destination_facility,
            ),
            effective_date=on,
            condition=condition,
            source_type=WORKFLOW_DOCUMENT_TYPE,
            source_id=locked.pk,
            user=user,
        )

        asset.refresh_from_db()
        AssetService.append_condition(
            asset=asset,
            condition=condition,
            source=ConditionSource.RETURN,
            note=note or f"Pengembalian {locked.document_number}",
            user=user,
        )

        locked.status = ReturnStatus.COMPLETED
        locked.resulting_custody = custody
        locked.return_date = on
        locked.return_condition = condition
        locked.completed_at = timezone.now()
        locked.completed_by = user
        locked.updated_by = user
        locked.save()

        AssetReservationService.release(
            operation_type=OPERATION,
            document_id=locked.pk,
            reason=ReservationRelease.COMPLETED,
            user=user,
        )

        cls._audit(
            instance=locked,
            action="update",
            user=user,
            before={"status": ReturnStatus.APPROVED},
            after={
                "status": ReturnStatus.COMPLETED,
                "resulting_custody": custody.pk,
                "return_condition": condition,
            },
        )

        return locked

    # ------------------------------------------------------------------
    # Workflow helpers
    # ------------------------------------------------------------------

    @classmethod
    def workflow_for(cls, asset_return: AssetReturn):
        from apps.workflow.services.workflow_service import WorkflowService

        return WorkflowService.instance_for(
            document=asset_return,
            module=WORKFLOW_MODULE,
            document_type=WORKFLOW_DOCUMENT_TYPE,
        )

    @staticmethod
    def _workflow_scope(asset_return: AssetReturn) -> dict:
        # Sisi penyimpanan penerima (tujuan) milik pemilik — pihak yang
        # menerima barang kembali. Bukan penempatan pemegang lama.
        return {
            "company": asset_return.company,
            "branch": asset_return.destination_location.branch,
            "location": asset_return.destination_location,
            "employee_group": None,
        }

    @classmethod
    def _find_definition(cls, asset_return: AssetReturn):
        from apps.workflow.services.definition_service import (
            WorkflowDefinitionResolver,
        )

        return WorkflowDefinitionResolver.match(
            module=WORKFLOW_MODULE,
            document_type=WORKFLOW_DOCUMENT_TYPE,
            **cls._workflow_scope(asset_return),
        )

    @staticmethod
    def workflow_context(asset_return: AssetReturn) -> dict:
        return {
            "asset_code": asset_return.asset.asset_code,
            "category": asset_return.asset.category.code,
            "source_custody_type": asset_return.source_custody_type,
            "reason": asset_return.reason,
            "is_relocation": (
                asset_return.destination_location_id
                != asset_return.source_location_id
            ),
        }

    @staticmethod
    def workflow_label(asset_return: AssetReturn) -> str:
        holder = (
            str(asset_return.source_employee)
            if asset_return.source_employee_id
            else str(asset_return.source_department)
        )

        return f"{asset_return.asset.asset_code} ← {holder}"

    # ------------------------------------------------------------------
    # Validasi
    # ------------------------------------------------------------------

    @staticmethod
    def _source_of(asset) -> dict:
        """
        Asal = custody **pemakaian** yang sedang terbuka, dibaca ulang dari
        database. Pemegang, department, PIC, dan lokasi asal disalin dari
        custody itu — kiriman klien untuk kolom-kolom itu sudah ditolak
        sebagai kolom sistem.
        """
        asset = (
            Asset.objects
            .select_related(
                "company",
                "current_custody",
                "current_custody__location",
            )
            .filter(pk=key(asset))
            .first()
        )

        if asset is None or asset.is_deleted or asset.status != AssetStatus.ACTIVE:
            raise ValidationError({"asset": "Aset belum aktif atau sudah dihapus."})

        custody = asset.current_custody

        if custody is None or custody.custody_type not in IN_USE:
            raise ValidationError({
                "asset": (
                    "Aset ini sudah di penyimpanan (STORAGE) — tidak ada yang "
                    "dikembalikan. Relokasi antar-penyimpanan lewat Transfer."
                ),
            })

        return {
            "company": asset.company,
            "source_custody": custody,
            "source_custody_type": custody.custody_type,
            "source_location": custody.location,
            "source_facility": custody.facility,
            "source_employee": custody.employee,
            "source_department": custody.department,
            "source_pic_employee": custody.pic_employee,
        }

    @staticmethod
    def _assert_source_current(asset_return: AssetReturn, asset: Asset) -> None:
        """Dokumen basi: custody aset sudah bukan asal yang dicatatnya."""
        if (
            asset.status != AssetStatus.ACTIVE
            or asset.current_custody_id != asset_return.source_custody_id
        ):
            raise ValidationError({
                "asset": (
                    "Custody aset sudah berubah sejak dokumen ini dibuat. "
                    "Dokumen ini tidak bisa diteruskan."
                ),
            })

    @staticmethod
    def _assert_destination(*, company_id, location, facility) -> None:
        """
        Penyimpanan tujuan milik company pemilik; fasilitas (opsional)
        milik company dan lokasi yang sama. Cross-table, jadi dijaga di
        sini (dan sekali lagi di `AssetCustodyService.move`).
        """
        errors: dict[str, str] = {}

        if location is None:
            errors["destination_location"] = "Lokasi penyimpanan tujuan wajib diisi."
        elif location.company_id != company_id:
            errors["destination_location"] = (
                "Lokasi penyimpanan harus milik company pemilik aset."
            )

        if facility is not None and location is not None:
            if facility.company_id != company_id:
                errors["destination_facility"] = (
                    "Fasilitas bukan milik company pemilik aset."
                )
            elif facility.location_id != location.pk:
                errors["destination_facility"] = (
                    "Fasilitas tidak berada di lokasi penyimpanan tujuan."
                )

        if errors:
            raise ValidationError(errors)

    @staticmethod
    def _assert_return_date(on, source_custody: AssetCustody) -> None:
        if on > timezone.localdate():
            raise ValidationError({
                "return_date": "Tanggal pengembalian tidak boleh di masa depan.",
            })

        if on < source_custody.started_on:
            raise ValidationError({
                "return_date": (
                    "Tanggal pengembalian tidak boleh sebelum aset diterima "
                    f"pemegangnya ({source_custody.started_on:%d-%m-%Y})."
                ),
            })

    @staticmethod
    def _lock(asset_return: AssetReturn) -> AssetReturn:
        locked = (
            AssetReturn.objects
            .select_for_update(of=("self",))
            .select_related(
                "asset",
                "asset__category",
                "source_custody",
                "source_location",
                "source_employee",
                "source_department",
                "destination_location",
                "destination_location__branch",
                "destination_facility",
            )
            .filter(pk=asset_return.pk, is_deleted=False)
            .first()
        )

        if locked is None:
            raise ValidationError("Dokumen tidak ditemukan atau sudah dihapus.")

        return locked
