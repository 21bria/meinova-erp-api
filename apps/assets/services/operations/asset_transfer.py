"""
Service Asset Transfer (`docs/claude/assets.md` §10, §16–§18, §26).

Lifecycle — sama dengan Assignment/Return:

    DRAFT ─submit─▶ SUBMITTED ─approve─▶ APPROVED ─complete─▶ COMPLETED
      ▲               │  └─reject─▶ REJECTED        │
      └─(RETURNED)────┘                              └─cancel─▶ CANCELLED
                      └──────────── cancel ─────────────────────▲

Semantik (tidak tumpang tindih dengan dokumen lain):

* pemakaian (EMPLOYEE/ORGANIZATION) → pemakaian — ganti pemegang, ganti
  unit, ganti PIC resmi, pindah lokasi/fasilitas;
* STORAGE → STORAGE — relokasi penyimpanan.

STORAGE → pemakaian = Assignment; pemakaian → STORAGE = Return — ditolak di
sini. Transfer yang tidak mengubah apa pun (pemegang, department, PIC,
lokasi, fasilitas sama) ditolak sebagai no-op.

Kondisi: tujuan pemakaian hanya untuk GOOD/FAIR (`ASSIGNABLE_CONDITIONS`) —
aset rusak dikembalikan lewat Return, bukan dioper ke pemakai lain.
STORAGE → STORAGE boleh untuk kondisi apa pun (mis. ke gudang/workshop).
Kondisi saat Transfer selesai wajib dan selalu dicatat (TRANSFER).

Ganti PIC resmi tidak punya approval khusus yang ditanam di kode (O-5):
mengikuti `WorkflowDefinition` `asset_transfer` bila ada (konteks
`is_pic_change` tersedia untuk kondisi langkah), tanpa definisi langsung
APPROVED seperti dokumen aset lain.
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
    ASSIGNABLE_CONDITIONS,
    TRANSFER_RESERVING_STATUSES,
    Asset,
    AssetCondition,
    AssetCustody,
    AssetOperationType,
    AssetStatus,
    AssetTransfer,
    ConditionSource,
    CustodyType,
    ReservationRelease,
    TransferStatus,
)
from apps.core.services.master import BaseMasterService

from .asset import AssetService
from .custody import AssetCustodyService, CustodyTarget
from .movement import (
    assert_may,
    key,
    lock_asset,
    reject_system_fields,
    resolve_holder,
)
from .reservation import AssetReservationService


WORKFLOW_MODULE = "assets"
WORKFLOW_DOCUMENT_TYPE = "asset_transfer"
OPERATION = AssetOperationType.TRANSFER

SUBMIT_PERMISSION = "assets.submit_assettransfer"
COMPLETE_PERMISSION = "assets.complete_assettransfer"
CANCEL_PERMISSION = "assets.cancel_assettransfer"

USAGE = (CustodyType.EMPLOYEE, CustodyType.ORGANIZATION)

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
    "employee_company",
    "employee_location",
    "employee_department",
    "is_cross_company",
    "transfer_date",
    "transfer_condition",
    "resulting_custody",
    "submitted_at",
    "approved_at",
    "rejected_at",
    "cancelled_at",
    "completed_at",
    "completed_by",
)

TARGET_FIELDS = (
    "asset",
    "target_custody_type",
    "target_employee",
    "target_department",
    "target_pic_employee",
    "target_location",
    "target_facility",
    "cross_company_reason",
)

# Kunci error `resolve_holder` → kolom dokumen Transfer.
HOLDER_KEYS = {
    "custody_type": "target_custody_type",
    "employee": "target_employee",
    "department": "target_department",
    "pic": "target_pic_employee",
    "location": "target_location",
    "facility": "target_facility",
    "reason": "cross_company_reason",
}


def custody_signature(
    *,
    custody_type,
    employee,
    department,
    pic,
    location,
    facility,
) -> tuple:
    """
    Kesetaraan semantik custody — dasar deteksi no-op. Dua custody sama
    bila jenis, pegawai, department, PIC, lokasi, **dan** fasilitas sama
    (dibandingkan lewat pk; kosong = `None`). Department sama + PIC beda,
    atau pegawai sama + lokasi beda, adalah perubahan.
    """
    return (
        custody_type,
        key(employee),
        key(department),
        key(pic),
        key(location),
        key(facility),
    )


class AssetTransferService(BaseMasterService):
    model = AssetTransfer

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
            "target_employee",
            "target_department",
            "target_pic_employee",
            "target_location",
            "target_facility",
            "employee_company",
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

        data.update(cls._resolve(
            merged=data,
            source=source,
            asset=cls._asset(asset),
            on=timezone.localdate(),
        ))

        data["status"] = TransferStatus.DRAFT
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
        instance: AssetTransfer,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ):
        reject_system_fields(data, SYSTEM_FIELDS, instance=instance)

        if instance.status != TransferStatus.DRAFT:
            raise ValidationError({
                "status": "Hanya dokumen DRAFT yang bisa disunting.",
            })

        merged = {
            name: data.get(name, getattr(instance, name))
            for name in TARGET_FIELDS
        }

        if key(merged["asset"]) != instance.asset_id:
            source = cls._source_of(merged["asset"])
            data.update(source)
        else:
            source = cls._snapshot_of(instance)

        data.update(cls._resolve(
            merged=merged,
            source=source,
            asset=cls._asset(merged["asset"]),
            on=timezone.localdate(),
        ))

        return data

    @classmethod
    def before_soft_delete(cls, *, instance, user=None, **kwargs) -> None:
        if instance.status != TransferStatus.DRAFT:
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
    def submit(cls, *, transfer: AssetTransfer, user=None, notes: str = ""):
        """
        DRAFT → SUBMITTED (atau langsung APPROVED tanpa alur). Memesan aset.
        Urutan kunci: dokumen → aset → pemesanan.
        """
        assert_may(user, SUBMIT_PERMISSION, "mengajukan Transfer")

        locked = cls._lock(transfer)

        if locked.status != TransferStatus.DRAFT:
            raise ValidationError({"status": "Dokumen ini sudah diajukan."})

        asset = lock_asset(locked.asset_id)

        cls._assert_source_current(locked, asset)

        derived = cls._resolve(
            merged={name: getattr(locked, name) for name in TARGET_FIELDS},
            source=cls._snapshot_of(locked),
            asset=asset,
            on=timezone.localdate(),
        )

        for name, value in derived.items():
            setattr(locked, name, value)

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
            TransferStatus.SUBMITTED
            if definition is not None
            else TransferStatus.APPROVED
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
            before={"status": TransferStatus.DRAFT},
            after={"status": locked.status},
        )

        if definition is None:
            return None

        from apps.workflow.services.workflow_service import WorkflowService

        return WorkflowService.submit(
            document=locked,
            module=WORKFLOW_MODULE,
            document_type=WORKFLOW_DOCUMENT_TYPE,
            # Subjek: pemegang tujuan (pegawai atau PIC), lalu pemegang asal.
            # Subjek bukan approver — mejanya ditentukan alur.
            employee=(
                locked.target_employee
                or locked.target_pic_employee
                or locked.source_employee
                or locked.source_pic_employee
            ),
            user=user,
            context=cls.workflow_context(locked),
            document_number=locked.document_number,
            document_label=cls.workflow_label(locked),
            notes=notes,
            scope=cls._workflow_scope(locked),
            initiator_employee=getattr(user, "employee_profile", None),
            on_complete=lambda wf, status: cls.on_workflow_done(
                transfer=locked,
                status=status,
                user=user,
            ),
        )

    # ------------------------------------------------------------------
    # Keputusan alur
    # ------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def decide(cls, *, transfer: AssetTransfer, approved: bool, user=None, notes: str = ""):
        """Approve/reject dari layar dokumen. Hak memutuskan milik engine."""
        from apps.workflow.services.workflow_service import WorkflowService

        workflow = cls.workflow_for(transfer)

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
                transfer=transfer,
                status=status,
                user=user,
            ),
        )

    @classmethod
    def on_workflow_done(cls, *, transfer, status, user=None):
        """
        Dipanggil engine saat alurnya berhenti. Hanya dokumen yang masih
        SUBMITTED yang digerakkan; setiap jalan keluar selain APPROVED
        melepas pemesanan di transaksi yang sama.
        """
        from apps.workflow.models import InstanceStatus

        mapping = {
            InstanceStatus.APPROVED: (TransferStatus.APPROVED, None),
            InstanceStatus.REJECTED: (
                TransferStatus.REJECTED,
                ReservationRelease.REJECTED,
            ),
            InstanceStatus.RETURNED: (
                TransferStatus.DRAFT,
                ReservationRelease.RETURNED_TO_DRAFT,
            ),
            InstanceStatus.CANCELLED: (
                TransferStatus.CANCELLED,
                ReservationRelease.CANCELLED,
            ),
        }

        if status not in mapping:
            return transfer

        target, release = mapping[status]

        locked = cls._lock(transfer)

        if locked.status != TransferStatus.SUBMITTED:
            return locked

        stamps = {
            TransferStatus.APPROVED: "approved_at",
            TransferStatus.REJECTED: "rejected_at",
            TransferStatus.CANCELLED: "cancelled_at",
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
            before={"status": TransferStatus.SUBMITTED},
            after={"status": target},
        )

        return locked

    # ------------------------------------------------------------------
    # Cancel
    # ------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def cancel(cls, *, transfer: AssetTransfer, user=None, notes: str = ""):
        """SUBMITTED/APPROVED → CANCELLED, melepas pemesanan."""
        assert_may(user, CANCEL_PERMISSION, "membatalkan Transfer")

        locked = cls._lock(transfer)

        if locked.status not in TRANSFER_RESERVING_STATUSES:
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

        locked.status = TransferStatus.CANCELLED
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
            after={"status": TransferStatus.CANCELLED},
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
        transfer: AssetTransfer,
        condition: str,
        user=None,
        transfer_date=None,
        note: str = "",
    ) -> AssetTransfer:
        """
        Barang benar-benar berpindah. `condition` wajib dan selalu masuk
        riwayat (TRANSFER). Tujuan pemakaian menolak kondisi tidak layak —
        aset itu dikembalikan lewat Return.
        """
        assert_may(user, COMPLETE_PERMISSION, "menyelesaikan Transfer")

        locked = cls._lock(transfer)

        if locked.status == TransferStatus.COMPLETED:
            raise ValidationError({"status": "Transfer ini sudah selesai."})

        if locked.status != TransferStatus.APPROVED:
            raise ValidationError({
                "status": "Transfer hanya bisa diselesaikan sesudah disetujui.",
            })

        if not condition:
            raise ValidationError({
                "condition": "Kondisi aset saat dipindahkan wajib diisi.",
            })

        if condition not in AssetCondition.values:
            raise ValidationError({"condition": "Kondisi tidak dikenal."})

        if (
            locked.target_custody_type in USAGE
            and condition not in ASSIGNABLE_CONDITIONS
        ):
            raise ValidationError({
                "condition": (
                    "Aset dalam kondisi ini tidak dioper ke pemakai lain. "
                    "Batalkan Transfer dan kembalikan lewat Return."
                ),
            })

        on = transfer_date or timezone.localdate()

        asset = lock_asset(locked.asset_id)

        cls._assert_source_current(locked, asset)

        AssetReservationService.assert_held(
            asset_id=asset.pk,
            operation_type=OPERATION,
            document_id=locked.pk,
        )

        # Penerima bisa berubah keadaan di antara approve dan serah terima
        # — divalidasi ulang pada tanggal Transfer, jejaknya dibekukan.
        derived = cls._resolve(
            merged={name: getattr(locked, name) for name in TARGET_FIELDS},
            source=cls._snapshot_of(locked),
            asset=asset,
            on=on,
            check_condition=False,
        )

        for name, value in derived.items():
            setattr(locked, name, value)

        cls._assert_transfer_date(on, locked.source_custody)

        custody = AssetCustodyService.move(
            asset_id=asset.pk,
            expected_custody_id=locked.source_custody_id,
            target=CustodyTarget(
                custody_type=locked.target_custody_type,
                location=locked.target_location,
                facility=locked.target_facility,
                employee=locked.target_employee,
                department=locked.target_department,
                pic_employee=locked.target_pic_employee,
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
            source=ConditionSource.TRANSFER,
            note=note or f"Transfer {locked.document_number}",
            user=user,
        )

        locked.status = TransferStatus.COMPLETED
        locked.resulting_custody = custody
        locked.transfer_date = on
        locked.transfer_condition = condition
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
            before={"status": TransferStatus.APPROVED},
            after={
                "status": TransferStatus.COMPLETED,
                "resulting_custody": custody.pk,
                "transfer_condition": condition,
            },
        )

        return locked

    # ------------------------------------------------------------------
    # Workflow helpers
    # ------------------------------------------------------------------

    @classmethod
    def workflow_for(cls, transfer: AssetTransfer):
        from apps.workflow.services.workflow_service import WorkflowService

        return WorkflowService.instance_for(
            document=transfer,
            module=WORKFLOW_MODULE,
            document_type=WORKFLOW_DOCUMENT_TYPE,
        )

    @staticmethod
    def _workflow_scope(transfer: AssetTransfer) -> dict:
        # Sisi asal — pihak yang mengajukan (§17). Bukan penempatan
        # penerima, supaya penerima lintas company tidak memindahkan meja.
        return {
            "company": transfer.company,
            "branch": transfer.source_location.branch,
            "location": transfer.source_location,
            "employee_group": None,
        }

    @classmethod
    def _find_definition(cls, transfer: AssetTransfer):
        from apps.workflow.services.definition_service import (
            WorkflowDefinitionResolver,
        )

        return WorkflowDefinitionResolver.match(
            module=WORKFLOW_MODULE,
            document_type=WORKFLOW_DOCUMENT_TYPE,
            **cls._workflow_scope(transfer),
        )

    @staticmethod
    def is_pic_change(transfer: AssetTransfer) -> bool:
        """ORGANIZATION → ORGANIZATION; hanya PIC yang berubah."""
        return (
            transfer.source_custody_type == CustodyType.ORGANIZATION
            and transfer.target_custody_type == CustodyType.ORGANIZATION
            and transfer.source_department_id == key(transfer.target_department)
            and transfer.source_location_id == key(transfer.target_location)
            and transfer.source_facility_id == key(transfer.target_facility)
            and transfer.source_pic_employee_id != key(transfer.target_pic_employee)
        )

    @classmethod
    def workflow_context(cls, transfer: AssetTransfer) -> dict:
        # Dibekukan saat pengajuan — bahan `WorkflowStep.condition`. Tidak
        # ada kategori yang ditanam di kode; tenant yang mengatur.
        return {
            "asset_code": transfer.asset.asset_code,
            "category": transfer.asset.category.code,
            "source_custody_type": transfer.source_custody_type,
            "target_custody_type": transfer.target_custody_type,
            "reason": transfer.reason,
            "is_cross_company": transfer.is_cross_company,
            "is_pic_change": cls.is_pic_change(transfer),
            "is_relocation": (
                transfer.source_location_id != key(transfer.target_location)
            ),
        }

    @staticmethod
    def workflow_label(transfer: AssetTransfer) -> str:
        def holder(employee, department, location):
            if employee is not None:
                return str(employee)
            if department is not None:
                return str(department)
            return str(location)

        return (
            f"{transfer.asset.asset_code}: "
            f"{holder(transfer.source_employee, transfer.source_department, transfer.source_location)}"
            f" → "
            f"{holder(transfer.target_employee, transfer.target_department, transfer.target_location)}"
        )

    # ------------------------------------------------------------------
    # Validasi
    # ------------------------------------------------------------------

    @staticmethod
    def _asset(asset) -> Asset:
        return Asset.objects.select_related("category").get(pk=key(asset))

    @staticmethod
    def _source_of(asset) -> dict:
        """
        Asal = custody yang sedang terbuka, dibaca ulang dari database —
        bukan dari objek pemanggil, bukan dari `current_custody` di memori,
        bukan dari klien.
        """
        asset = (
            Asset.objects
            .select_related("company", "current_custody")
            .filter(pk=key(asset))
            .first()
        )

        if asset is None or asset.is_deleted or asset.status != AssetStatus.ACTIVE:
            raise ValidationError({"asset": "Aset belum aktif atau sudah dihapus."})

        custody = asset.current_custody

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
    def _snapshot_of(transfer: AssetTransfer) -> dict:
        return {
            "company": transfer.company,
            "source_custody": transfer.source_custody,
            "source_custody_type": transfer.source_custody_type,
            "source_location": transfer.source_location,
            "source_facility": transfer.source_facility,
            "source_employee": transfer.source_employee,
            "source_department": transfer.source_department,
            "source_pic_employee": transfer.source_pic_employee,
        }

    @classmethod
    def _resolve(
        cls,
        *,
        merged: dict,
        source: dict,
        asset: Asset,
        on,
        check_condition: bool = True,
    ) -> dict:
        """
        Validasi tujuan terhadap asal dan turunkan kolom sistem tujuan
        (`employee_*`, `is_cross_company`, `cross_company_reason`).
        """
        source_type = source["source_custody_type"]
        target_type = merged.get("target_custody_type")

        # Batas semantik dengan Assignment/Return.
        if source_type == CustodyType.STORAGE and target_type in USAGE:
            raise ValidationError({
                "target_custody_type": (
                    "Aset di penyimpanan diserahkan ke pemakai lewat "
                    "Assignment, bukan Transfer."
                ),
            })

        if source_type in USAGE and target_type == CustodyType.STORAGE:
            raise ValidationError({
                "target_custody_type": (
                    "Aset yang sedang dipakai dikembalikan ke penyimpanan "
                    "lewat Return, bukan Transfer."
                ),
            })

        if target_type == CustodyType.STORAGE:
            derived = cls._resolve_storage(merged=merged, asset=asset)
        elif target_type in USAGE:
            if check_condition and asset.condition not in ASSIGNABLE_CONDITIONS:
                raise ValidationError({
                    "asset": (
                        f"Kondisi aset {asset.get_condition_display()} — "
                        "tidak dioper ke pemakai lain. Kembalikan lewat "
                        "Return; pemindahan antar-penyimpanan tetap boleh."
                    ),
                })

            derived = resolve_holder(
                asset=asset,
                custody_type=target_type,
                employee=merged.get("target_employee"),
                department=merged.get("target_department"),
                pic=merged.get("target_pic_employee"),
                location=merged.get("target_location"),
                facility=merged.get("target_facility"),
                reason=merged.get("cross_company_reason"),
                on=on,
                keys=HOLDER_KEYS,
            )
        else:
            raise ValidationError({
                "target_custody_type": "Pilih EMPLOYEE, ORGANIZATION, atau STORAGE.",
            })

        before = custody_signature(
            custody_type=source_type,
            employee=source["source_employee"],
            department=source["source_department"],
            pic=source["source_pic_employee"],
            location=source["source_location"],
            facility=source["source_facility"],
        )
        after = custody_signature(
            custody_type=target_type,
            employee=merged.get("target_employee"),
            department=merged.get("target_department"),
            pic=merged.get("target_pic_employee"),
            location=merged.get("target_location"),
            facility=merged.get("target_facility"),
        )

        if before == after:
            raise ValidationError({
                "target_custody_type": (
                    "Tujuan sama dengan custody saat ini — tidak ada yang "
                    "dipindahkan."
                ),
            })

        return derived

    @staticmethod
    def _resolve_storage(*, merged: dict, asset: Asset) -> dict:
        errors: dict[str, str] = {}

        for name in ("target_employee", "target_department", "target_pic_employee"):
            if merged.get(name) is not None:
                errors[name] = "Penyimpanan tidak punya pemegang."

        if (merged.get("cross_company_reason") or "").strip():
            errors["cross_company_reason"] = "Penyimpanan tidak lintas company."

        location = merged.get("target_location")
        facility = merged.get("target_facility")

        if location is None:
            errors["target_location"] = "Lokasi penyimpanan tujuan wajib diisi."
        elif location.company_id != asset.company_id:
            errors["target_location"] = (
                "Lokasi penyimpanan harus milik company pemilik aset."
            )

        if facility is not None and location is not None:
            if facility.company_id != asset.company_id:
                errors["target_facility"] = "Fasilitas bukan milik company pemilik aset."
            elif facility.location_id != location.pk:
                errors["target_facility"] = "Fasilitas tidak berada di lokasi tujuan."

        if errors:
            raise ValidationError(errors)

        return {
            "employee_company": None,
            "employee_location": None,
            "employee_department": None,
            "is_cross_company": False,
            "cross_company_reason": "",
        }

    @staticmethod
    def _assert_source_current(transfer: AssetTransfer, asset: Asset) -> None:
        """Dokumen basi: custody aset sudah bukan asal yang dicatatnya."""
        if (
            asset.status != AssetStatus.ACTIVE
            or asset.current_custody_id != transfer.source_custody_id
        ):
            raise ValidationError({
                "asset": (
                    "Custody aset sudah berubah sejak dokumen ini dibuat. "
                    "Dokumen ini tidak bisa diteruskan."
                ),
            })

    @staticmethod
    def _assert_transfer_date(on, source_custody: AssetCustody) -> None:
        if on > timezone.localdate():
            raise ValidationError({
                "transfer_date": "Tanggal Transfer tidak boleh di masa depan.",
            })

        if on < source_custody.started_on:
            raise ValidationError({
                "transfer_date": (
                    "Tanggal Transfer tidak boleh sebelum custody asal "
                    f"dimulai ({source_custody.started_on:%d-%m-%Y})."
                ),
            })

    @staticmethod
    def _lock(transfer: AssetTransfer) -> AssetTransfer:
        locked = (
            AssetTransfer.objects
            .select_for_update(of=("self",))
            .select_related(
                "asset",
                "asset__category",
                "source_custody",
                "source_location",
                "source_location__branch",
                "source_facility",
                "source_employee",
                "source_department",
                "source_pic_employee",
                "target_employee",
                "target_department",
                "target_pic_employee",
                "target_location",
                "target_facility",
            )
            .filter(pk=transfer.pk, is_deleted=False)
            .first()
        )

        if locked is None:
            raise ValidationError("Dokumen tidak ditemukan atau sudah dihapus.")

        return locked
