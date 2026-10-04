"""
Service Asset Assignment (`docs/claude/assets.md` §9, §16, §18, §26).

Lifecycle:

    DRAFT ─submit─▶ SUBMITTED ─approve─▶ APPROVED ─complete─▶ COMPLETED
      ▲               │  └─reject─▶ REJECTED        │
      └─(RETURNED)────┘                              └─cancel─▶ CANCELLED
                      └──────────── cancel ─────────────────────▲

* **Pemesanan** dimulai saat SUBMITTED dan bertahan selama APPROVED
  (`ASSIGNMENT_RESERVING_STATUSES`). DRAFT tidak memesan apa pun. Sejak
  ASSET-4 dipegang `AssetReservationService` — authority bersama Return
  dan kelak Transfer — dan dilepas di setiap jalan keluar dari
  SUBMITTED/APPROVED, di transaksi yang sama dengan perubahan statusnya.
* Tanpa `WorkflowDefinition` yang cocok, submit langsung APPROVED (pola
  jurnal Finance) — tetap memesan, tetap butuh `complete`.
* **APPROVED tidak memindahkan custody.** Hanya `complete`, lewat
  `AssetCustodyService.move`, dalam satu transaksi.
* Penerima (pegawai) adalah **subjek** dokumen, bukan approver (O-4).
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
    ASSIGNMENT_RESERVING_STATUSES,
    Asset,
    AssetAssignment,
    AssetCondition,
    AssetOperationType,
    AssetStatus,
    AssignmentStatus,
    ConditionSource,
    CustodyType,
    ReservationRelease,
)
from apps.core.services.master import BaseMasterService

from .asset import AssetService
from .custody import AssetCustodyService, CustodyTarget
from .movement import (
    active_placement,
    assert_may,
    key as _key,
    lock_asset,
    reject_system_fields,
    resolve_holder,
)
from .reservation import AssetReservationService


WORKFLOW_MODULE = "assets"
WORKFLOW_DOCUMENT_TYPE = "asset_assignment"
OPERATION = AssetOperationType.ASSIGNMENT

SUBMIT_PERMISSION = "assets.submit_assetassignment"
COMPLETE_PERMISSION = "assets.complete_assetassignment"
CANCEL_PERMISSION = "assets.cancel_assetassignment"

# Diisi sistem — tidak pernah dari klien, juga lewat jalur non-HTTP.
SYSTEM_FIELDS = (
    "document_number",
    "status",
    "company",
    "source_custody",
    "source_location",
    "employee_company",
    "employee_location",
    "employee_department",
    "is_cross_company",
    "handover_date",
    "handover_condition",
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
    "employee",
    "department",
    "pic_employee",
    "location",
    "facility",
    "cross_company_reason",
)


class AssetAssignmentService(BaseMasterService):
    model = AssetAssignment

    @classmethod
    def list(cls):
        return cls.get_queryset().select_related(
            "company",
            "asset",
            "asset__category",
            "source_location",
            "employee",
            "department",
            "pic_employee",
            "location",
            "facility",
            "employee_company",
        )

    # ------------------------------------------------------------------
    # Draft
    # ------------------------------------------------------------------

    @classmethod
    def prepare_create_data(cls, *, data: dict[str, Any], user=None, **kwargs):
        cls._reject_system_fields(data)

        asset = data.get("asset")

        if asset is None:
            raise ValidationError({"asset": "Aset wajib dipilih."})

        data.update(cls._source_of(asset))
        data.update(
            cls._resolve_target(merged=data, asset=asset, on=timezone.localdate()),
        )

        data["status"] = AssignmentStatus.DRAFT
        data["document_number"] = DocumentNumberService.next(
            module=WORKFLOW_MODULE,
            document_type=WORKFLOW_DOCUMENT_TYPE,
            company=asset.company,
        )

        return data

    @classmethod
    def prepare_update_data(
        cls,
        *,
        instance: AssetAssignment,
        data: dict[str, Any],
        user=None,
        **kwargs,
    ):
        cls._reject_system_fields(data, instance=instance)

        if instance.status != AssignmentStatus.DRAFT:
            raise ValidationError({
                "status": "Hanya dokumen DRAFT yang bisa disunting.",
            })

        merged = {
            name: data.get(name, getattr(instance, name))
            for name in TARGET_FIELDS
        }

        asset = merged["asset"]

        # Aset diganti di draft = asal ikut dibaca ulang.
        if _key(asset) != instance.asset_id:
            data.update(cls._source_of(asset))

        data.update(
            cls._resolve_target(merged=merged, asset=asset, on=timezone.localdate()),
        )

        return data

    @classmethod
    def before_soft_delete(cls, *, instance, user=None, **kwargs) -> None:
        if instance.status != AssignmentStatus.DRAFT:
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
    def submit(cls, *, assignment: AssetAssignment, user=None, notes: str = ""):
        """
        DRAFT → SUBMITTED (atau langsung APPROVED tanpa alur). Memesan aset.

        Urutan kunci dokumen → aset sama di submit, cancel, dan complete,
        supaya dua jalur tidak saling menunggu terbalik.
        """
        cls._assert_may(user, SUBMIT_PERMISSION, "mengajukan Assignment")

        locked = cls._lock(assignment)

        if locked.status != AssignmentStatus.DRAFT:
            raise ValidationError({"status": "Dokumen ini sudah diajukan."})

        asset = cls._lock_asset(locked.asset_id)

        cls._assert_source_current(locked, asset)
        cls._assert_assignable_condition(asset)

        derived = cls._resolve_target(
            merged={name: getattr(locked, name) for name in TARGET_FIELDS},
            asset=asset,
            on=timezone.localdate(),
        )

        for name, value in derived.items():
            setattr(locked, name, value)

        # Pemesanan lewat authority bersama: kunci baris aset di atas
        # membuat submit lain (jenis dokumen apa pun) menunggu, lalu
        # `uniq_active_assets_reservation_asset` sebagai jaring terakhir.
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
            AssignmentStatus.SUBMITTED
            if definition is not None
            else AssignmentStatus.APPROVED
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
            before={"status": AssignmentStatus.DRAFT},
            after={"status": locked.status},
        )

        if definition is None:
            return None

        from apps.workflow.services.workflow_service import WorkflowService

        return WorkflowService.submit(
            document=locked,
            module=WORKFLOW_MODULE,
            document_type=WORKFLOW_DOCUMENT_TYPE,
            # Subjek dokumen: penerima (EMPLOYEE) atau PIC (ORGANIZATION).
            # Subjek bukan approver — mejanya ditentukan alurnya (O-4).
            employee=locked.employee or locked.pic_employee,
            user=user,
            context=cls.workflow_context(locked),
            document_number=locked.document_number,
            document_label=cls.workflow_label(locked),
            notes=notes,
            # Cakupan alur = pemilik aset, bukan penempatan penerima —
            # penerima lintas company tidak boleh memindahkan meja
            # persetujuan ke company-nya (O-8).
            scope=cls._workflow_scope(locked),
            initiator_employee=getattr(user, "employee_profile", None),
            on_complete=lambda wf, status: cls.on_workflow_done(
                assignment=locked,
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
        assignment: AssetAssignment,
        approved: bool,
        user=None,
        notes: str = "",
    ):
        """
        Approve/reject dari layar dokumen. Hak memutuskan milik engine
        (pemegang meja), bukan izin model — dan bukan penerima aset.
        """
        from apps.workflow.services.workflow_service import WorkflowService

        workflow = cls.workflow_for(assignment)

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
                assignment=assignment,
                status=status,
                user=user,
            ),
        )

    @classmethod
    def on_workflow_done(cls, *, assignment, status, user=None):
        """
        Dipanggil engine saat alurnya berhenti — dari layar dokumen maupun
        dari kotak masuk generik (`apps/assets/workflow_handlers.py`).

        Hanya dokumen yang masih menunggu (SUBMITTED) yang digerakkan:
        keputusan yang datang terlambat untuk dokumen yang sudah dibatalkan
        tidak boleh menghidupkannya lagi.
        """
        from apps.workflow.models import InstanceStatus

        mapping = {
            InstanceStatus.APPROVED: AssignmentStatus.APPROVED,
            InstanceStatus.REJECTED: AssignmentStatus.REJECTED,
            # Dikembalikan untuk diperbaiki: turun ke DRAFT — pemesanan
            # dilepas, dokumen bisa disunting dan diajukan ulang.
            InstanceStatus.RETURNED: AssignmentStatus.DRAFT,
            InstanceStatus.CANCELLED: AssignmentStatus.CANCELLED,
        }

        target = mapping.get(status)

        if target is None:
            return assignment

        locked = cls._lock(assignment)

        if locked.status != AssignmentStatus.SUBMITTED:
            return locked

        stamps = {
            AssignmentStatus.APPROVED: "approved_at",
            AssignmentStatus.REJECTED: "rejected_at",
            AssignmentStatus.CANCELLED: "cancelled_at",
        }

        fields = ["status", "updated_by", "updated_at"]

        locked.status = target
        locked.updated_by = user

        if target in stamps:
            setattr(locked, stamps[target], timezone.now())
            fields.append(stamps[target])

        locked.save(update_fields=fields)

        release = {
            AssignmentStatus.REJECTED: ReservationRelease.REJECTED,
            AssignmentStatus.DRAFT: ReservationRelease.RETURNED_TO_DRAFT,
            AssignmentStatus.CANCELLED: ReservationRelease.CANCELLED,
        }.get(target)

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
            before={"status": AssignmentStatus.SUBMITTED},
            after={"status": target},
        )

        return locked

    # ------------------------------------------------------------------
    # Cancel
    # ------------------------------------------------------------------

    @classmethod
    @transaction.atomic
    def cancel(cls, *, assignment: AssetAssignment, user=None, notes: str = ""):
        """
        SUBMITTED/APPROVED → CANCELLED, melepas pemesanan. DRAFT dihapus,
        bukan dibatalkan; COMPLETED tidak bisa dibatalkan — salah serah
        terima dikoreksi dengan dokumen kebalikannya (Return/Transfer).
        """
        cls._assert_may(user, CANCEL_PERMISSION, "membatalkan Assignment")

        locked = cls._lock(assignment)

        if locked.status not in ASSIGNMENT_RESERVING_STATUSES:
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

        locked.status = AssignmentStatus.CANCELLED
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
            after={"status": AssignmentStatus.CANCELLED},
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
        assignment: AssetAssignment,
        user=None,
        handover_date=None,
        condition: str = "",
        note: str = "",
    ) -> AssetAssignment:
        cls._assert_may(user, COMPLETE_PERMISSION, "menyelesaikan serah terima")

        locked = cls._lock(assignment)

        if locked.status == AssignmentStatus.COMPLETED:
            raise ValidationError({"status": "Serah terima ini sudah selesai."})

        if locked.status != AssignmentStatus.APPROVED:
            raise ValidationError({
                "status": "Serah terima hanya bisa diselesaikan sesudah disetujui.",
            })

        if condition and condition not in AssetCondition.values:
            raise ValidationError({"condition": "Kondisi tidak dikenal."})

        on = handover_date or timezone.localdate()

        asset = cls._lock_asset(locked.asset_id)

        cls._assert_source_current(locked, asset)

        AssetReservationService.assert_held(
            asset_id=asset.pk,
            operation_type=OPERATION,
            document_id=locked.pk,
        )

        # Penerima bisa berubah keadaan di antara approve dan serah terima
        # (terminasi, mutasi) — divalidasi ulang dan jejaknya dibekukan.
        derived = cls._resolve_target(
            merged={name: getattr(locked, name) for name in TARGET_FIELDS},
            asset=asset,
            on=on,
        )

        for name, value in derived.items():
            setattr(locked, name, value)

        custody = AssetCustodyService.move(
            asset_id=asset.pk,
            expected_custody_id=locked.source_custody_id,
            target=CustodyTarget(
                custody_type=locked.target_custody_type,
                location=locked.location,
                facility=locked.facility,
                employee=locked.employee,
                department=locked.department,
                pic_employee=locked.pic_employee,
            ),
            effective_date=on,
            condition=condition,
            source_type=WORKFLOW_DOCUMENT_TYPE,
            source_id=locked.pk,
            user=user,
        )

        # Kondisi saat serah terima hanya dicatat bila dikirim — lewat
        # riwayat kondisi, bukan menimpa kolom aset.
        if condition:
            asset.refresh_from_db()
            AssetService.append_condition(
                asset=asset,
                condition=condition,
                source=ConditionSource.HANDOVER,
                note=note or f"Serah terima {locked.document_number}",
                user=user,
            )

        locked.status = AssignmentStatus.COMPLETED
        locked.resulting_custody = custody
        locked.handover_date = on
        locked.handover_condition = condition or custody.start_condition
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
            before={"status": AssignmentStatus.APPROVED},
            after={
                "status": AssignmentStatus.COMPLETED,
                "resulting_custody": custody.pk,
            },
        )

        return locked

    # ------------------------------------------------------------------
    # Workflow helpers
    # ------------------------------------------------------------------

    @classmethod
    def workflow_for(cls, assignment: AssetAssignment):
        from apps.workflow.services.workflow_service import WorkflowService

        return WorkflowService.instance_for(
            document=assignment,
            module=WORKFLOW_MODULE,
            document_type=WORKFLOW_DOCUMENT_TYPE,
        )

    @staticmethod
    def _workflow_scope(assignment: AssetAssignment) -> dict:
        # Instance, bukan id — `WorkflowService.submit()` meneruskannya ke
        # kolom FK `WorkflowInstance`.
        return {
            "company": assignment.company,
            "branch": assignment.source_location.branch,
            "location": assignment.source_location,
            "employee_group": None,
        }

    @classmethod
    def _find_definition(cls, assignment: AssetAssignment):
        from apps.workflow.services.definition_service import (
            WorkflowDefinitionResolver,
        )

        return WorkflowDefinitionResolver.match(
            module=WORKFLOW_MODULE,
            document_type=WORKFLOW_DOCUMENT_TYPE,
            **cls._workflow_scope(assignment),
        )

    @staticmethod
    def workflow_context(assignment: AssetAssignment) -> dict:
        # Dibekukan saat pengajuan — bahan `WorkflowStep.condition`,
        # mis. meja tambahan untuk penyerahan lintas company.
        return {
            "asset_code": assignment.asset.asset_code,
            "category": assignment.asset.category.code,
            "target_custody_type": assignment.target_custody_type,
            "is_cross_company": assignment.is_cross_company,
        }

    @staticmethod
    def workflow_label(assignment: AssetAssignment) -> str:
        holder = (
            str(assignment.employee)
            if assignment.employee_id
            else str(assignment.department)
        )

        return f"{assignment.asset.asset_code} → {holder}"

    # ------------------------------------------------------------------
    # Validasi
    # ------------------------------------------------------------------

    @staticmethod
    def _reject_system_fields(data: dict[str, Any], *, instance=None) -> None:
        reject_system_fields(data, SYSTEM_FIELDS, instance=instance)

    @staticmethod
    def _source_of(asset: Asset) -> dict:
        """
        Asal = custody STORAGE yang sedang terbuka.

        Dibaca **ulang dari database**, bukan dari objek pemanggil: objek
        aset di memori bisa basi (custody-nya sudah berpindah), dan draft
        yang dibuat atas custody lama baru akan tertolak saat submit —
        terlambat. Submit dan complete tetap memvalidasi ulang di dalam
        kunci; ini supaya penolakannya terjadi sejak draft.
        """
        asset = (
            Asset.objects
            .select_related("company", "current_custody", "current_custody__location")
            .filter(pk=getattr(asset, "pk", asset))
            .first()
        )

        if asset is None or asset.is_deleted or asset.status != AssetStatus.ACTIVE:
            raise ValidationError({"asset": "Aset belum aktif atau sudah dihapus."})

        custody = asset.current_custody

        if custody is None or custody.custody_type != CustodyType.STORAGE:
            raise ValidationError({
                "asset": (
                    "Aset ini tidak sedang di penyimpanan (STORAGE). Yang "
                    "sedang dipakai dipindahkan lewat Transfer, bukan "
                    "Assignment."
                ),
            })

        AssetAssignmentService._assert_assignable_condition(asset)

        return {
            "company": asset.company,
            "source_custody": custody,
            "source_location": custody.location,
        }

    @staticmethod
    def _assert_assignable_condition(asset: Asset) -> None:
        """
        Aset rusak tidak diserahkan lagi (ASSET-4): DAMAGED/UNSERVICEABLE
        boleh kembali ke penyimpanan, tetapi baru bisa diajukan untuk
        diserahkan sesudah kondisinya dicatat layak (inspeksi, kelak
        maintenance). Dicek saat draft dan, di dalam kunci, saat submit.
        Kondisi serah terima yang dicatat saat `complete` tidak dibatasi —
        itu catatan fakta, bukan kelayakan.
        """
        if asset.condition not in ASSIGNABLE_CONDITIONS:
            raise ValidationError({
                "asset": (
                    f"Kondisi aset {asset.get_condition_display()} — tidak "
                    "layak diserahkan. Catat kondisi layak (inspeksi) lebih "
                    "dulu."
                ),
            })

    @staticmethod
    def _assert_source_current(assignment: AssetAssignment, asset: Asset) -> None:
        """Dokumen basi: custody aset sudah bukan asal yang dicatatnya."""
        if (
            asset.status != AssetStatus.ACTIVE
            or asset.current_custody_id != assignment.source_custody_id
        ):
            raise ValidationError({
                "asset": (
                    "Custody aset sudah berubah sejak dokumen ini dibuat. "
                    "Dokumen ini tidak bisa diteruskan."
                ),
            })

    @classmethod
    def _resolve_target(cls, *, merged: dict, asset, on) -> dict:
        """
        Validasi tujuan dan turunkan jejak organisasi penerima — aturan
        bersama Assignment/Transfer di `movement.resolve_holder`.
        """
        return resolve_holder(
            asset=asset,
            custody_type=merged.get("target_custody_type"),
            employee=merged.get("employee"),
            department=merged.get("department"),
            pic=merged.get("pic_employee"),
            location=merged.get("location"),
            facility=merged.get("facility"),
            reason=merged.get("cross_company_reason"),
            on=on,
        )

    _active_placement = staticmethod(active_placement)

    # Jalur non-HTTP ikut dijaga; `user=None` = pemanggil sistem.
    _assert_may = staticmethod(assert_may)

    @staticmethod
    def _lock(assignment: AssetAssignment) -> AssetAssignment:
        locked = (
            AssetAssignment.objects
            .select_for_update(of=("self",))
            .select_related(
                "asset",
                "asset__category",
                "source_location",
                "location",
                "facility",
                "employee",
                "department",
                "pic_employee",
            )
            .filter(pk=assignment.pk, is_deleted=False)
            .first()
        )

        if locked is None:
            raise ValidationError("Dokumen tidak ditemukan atau sudah dihapus.")

        return locked

    _lock_asset = staticmethod(lock_asset)
