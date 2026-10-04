"""
Satu-satunya authority pemesanan aset oleh dokumen operasional
(`docs/claude/assets.md` §26).

Assignment, Return, dan Transfer memanggil service ini — tidak ada
dokumen yang memeriksa tabel dokumen lain, dan service ini tidak
mengimpor service dokumen mana pun (arah dependensi satu: dokumen →
pemesanan). Yang dikenal di sini hanya **model** dokumennya, lewat
`RESERVABLE_DOCUMENTS`, untuk memastikan identitas `(operation_type,
document_id)` menunjuk dokumen nyata atas aset yang sama.

Lifecycle (dipanggil dokumen, di dalam transaksinya sendiri):

* `acquire` — saat DRAFT → SUBMITTED/APPROVED;
* `assert_held` — saat complete, sebelum custody dipindah;
* `release` — saat dokumen keluar dari SUBMITTED/APPROVED (COMPLETED,
  REJECTED, CANCELLED, dikembalikan ke DRAFT).
"""

from __future__ import annotations

from dataclasses import dataclass

from django.apps import apps
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.assets.models import (
    ASSIGNMENT_RESERVING_STATUSES,
    RETURN_RESERVING_STATUSES,
    TRANSFER_RESERVING_STATUSES,
    Asset,
    AssetOperationReservation,
    AssetOperationType,
    ReservationRelease,
)


OPERATION_LABELS = {
    AssetOperationType.ASSIGNMENT: "Assignment",
    AssetOperationType.RETURN: "Return",
    AssetOperationType.TRANSFER: "Transfer",
}


@dataclass(frozen=True)
class ReservableDocument:
    """
    Model dokumen yang boleh memesan aset. Syaratnya: satu dokumen = satu
    aset (`asset` FK), soft delete (`is_deleted`), dan `status`.
    """

    model_label: str
    reserving_statuses: tuple

    @property
    def model(self):
        return apps.get_model(self.model_label)

    def asset_id_of(self, document_id) -> int | None:
        """Aset dokumen yang belum dihapus, atau `None`."""
        return (
            self.model.objects
            .filter(pk=document_id, is_deleted=False)
            .values_list("asset_id", flat=True)
            .first()
        )

    def inflight(self) -> dict[int, int]:
        """`{document_id: asset_id}` dokumen yang sedang memesan."""
        return dict(
            self.model.objects
            .filter(is_deleted=False, status__in=self.reserving_statuses)
            .values_list("pk", "asset_id")
        )


# Jenis yang tidak terdaftar di sini ditolak `acquire`.
RESERVABLE_DOCUMENTS: dict[str, ReservableDocument] = {
    AssetOperationType.ASSIGNMENT: ReservableDocument(
        "assets.AssetAssignment",
        tuple(ASSIGNMENT_RESERVING_STATUSES),
    ),
    AssetOperationType.RETURN: ReservableDocument(
        "assets.AssetReturn",
        tuple(RETURN_RESERVING_STATUSES),
    ),
    AssetOperationType.TRANSFER: ReservableDocument(
        "assets.AssetTransfer",
        tuple(TRANSFER_RESERVING_STATUSES),
    ),
}


class AssetReservationService:
    @classmethod
    @transaction.atomic
    def acquire(
        cls,
        *,
        asset_id: int,
        operation_type: str,
        document_id: int,
        document_number: str = "",
        user=None,
    ) -> AssetOperationReservation:
        """
        Pesan aset untuk satu dokumen. Gagal = `ValidationError` yang
        menyebut dokumen pemesannya, tidak pernah `IntegrityError`.

        Baris aset dikunci di sini (pemanggil dokumen biasanya sudah
        menguncinya — mengunci ulang di transaksi yang sama tidak
        menunggu). Urutan kunci tetap: dokumen → aset → pemesanan →
        custody. Constraint `uniq_active_assets_reservation_asset` adalah
        jaring terakhir bila dua pemanggil lolos dari kunci.
        """
        document = cls._document(operation_type)

        if document.asset_id_of(document_id) != asset_id:
            raise ValidationError(
                "Dokumen pemesan tidak ditemukan atau bukan dokumen untuk "
                "aset ini.",
            )

        locked = (
            Asset.objects
            .select_for_update(of=("self",))
            .filter(pk=asset_id, is_deleted=False)
            .first()
        )

        if locked is None:
            raise ValidationError({"asset": "Aset tidak ditemukan atau sudah dihapus."})

        held = cls.active_for(asset_id)

        if held is not None:
            raise cls._reserved_error(held)

        reservation = AssetOperationReservation(
            asset_id=asset_id,
            operation_type=operation_type,
            document_id=document_id,
            document_number=document_number or "",
            reserved_at=timezone.now(),
            reserved_by=user,
        )

        reservation.full_clean(validate_constraints=False)

        try:
            with transaction.atomic():
                reservation.save()
        except IntegrityError as exc:
            # Pemesan lain menang di antara pemeriksaan dan INSERT.
            held = cls.active_for(asset_id)

            if held is not None:
                raise cls._reserved_error(held) from exc

            raise ValidationError({
                "asset": "Aset ini sedang dipesan dokumen lain.",
            }) from exc

        return reservation

    @classmethod
    @transaction.atomic
    def release(
        cls,
        *,
        operation_type: str,
        document_id: int,
        reason: str,
        user=None,
    ) -> AssetOperationReservation:
        """
        Lepas pemesanan milik satu dokumen. Dokumen yang keluar dari
        status berjalan **harus** memegang pemesanan; tidak ada = keadaan
        yang tidak konsisten, dan transisinya ditolak (rollback) alih-alih
        diam-diam dianggap beres.
        """
        if reason not in ReservationRelease.values:
            raise ValueError(f"Alasan lepas pemesanan tidak dikenal: {reason!r}")

        reservation = (
            AssetOperationReservation.objects
            .select_for_update()
            .filter(
                operation_type=operation_type,
                document_id=document_id,
                released_at__isnull=True,
            )
            .first()
        )

        if reservation is None:
            raise ValidationError(
                "Dokumen ini tidak memegang pemesanan aset yang aktif.",
            )

        reservation.released_at = timezone.now()
        reservation.released_by = user
        reservation.release_reason = reason
        reservation.save(update_fields=[
            "released_at",
            "released_by",
            "release_reason",
        ])

        return reservation

    @classmethod
    def assert_held(cls, *, asset_id: int, operation_type: str, document_id: int) -> None:
        """
        Dokumen yang akan memindahkan custody harus masih pemegang
        pemesanan aktif aset itu. Dipanggil di dalam kunci aset.
        """
        held = cls.active_for(asset_id)

        if (
            held is None
            or held.operation_type != operation_type
            or held.document_id != document_id
        ):
            raise ValidationError({
                "asset": (
                    "Dokumen ini tidak lagi memegang pemesanan aset. Muat "
                    "ulang dokumennya."
                ),
            })

    @staticmethod
    def active_for(asset_id) -> AssetOperationReservation | None:
        return (
            AssetOperationReservation.objects
            .filter(asset_id=asset_id, released_at__isnull=True)
            .first()
        )

    @staticmethod
    def active():
        """Pemesanan terbuka — untuk `Exists()` di lookup."""
        return AssetOperationReservation.objects.filter(released_at__isnull=True)

    # ------------------------------------------------------------------
    # Audit read-only
    # ------------------------------------------------------------------

    @classmethod
    def integrity_issues(cls) -> list[dict]:
        """
        Pelanggaran "dokumen berjalan ⇔ pemesanan terbuka" — invariant
        lintas tabel yang tidak bisa dijaga constraint. **Tidak menulis
        apa pun.** Dibaca `audit_asset_custody` dan test.
        """
        issues: list[dict] = []

        active = {
            (row.operation_type, row.document_id): row
            for row in cls.active().select_related("asset")
        }

        for operation_type, document in RESERVABLE_DOCUMENTS.items():
            inflight = document.inflight()

            for document_id, asset_id in inflight.items():
                row = active.get((operation_type, document_id))

                if row is None:
                    issues.append(cls._issue(
                        asset_id,
                        operation_type,
                        document_id,
                        "dokumen berjalan tanpa pemesanan aktif",
                    ))
                elif row.asset_id != asset_id:
                    issues.append(cls._issue(
                        row.asset_id,
                        operation_type,
                        document_id,
                        "pemesanan menunjuk aset lain dari dokumennya",
                    ))

            for (row_type, document_id), row in active.items():
                if row_type == operation_type and document_id not in inflight:
                    issues.append(cls._issue(
                        row.asset_id,
                        operation_type,
                        document_id,
                        "pemesanan yatim: dokumennya tidak sedang berjalan",
                    ))

        for (row_type, document_id), row in active.items():
            if row_type not in RESERVABLE_DOCUMENTS:
                issues.append(cls._issue(
                    row.asset_id,
                    row_type,
                    document_id,
                    "pemesanan atas jenis dokumen yang tidak terdaftar",
                ))

        return issues

    # ------------------------------------------------------------------

    @staticmethod
    def _document(operation_type):
        document = RESERVABLE_DOCUMENTS.get(operation_type)

        if document is None:
            raise ValidationError(
                f"Jenis dokumen {operation_type!r} belum bisa memesan aset.",
            )

        return document

    @staticmethod
    def _reserved_error(held: AssetOperationReservation) -> ValidationError:
        label = OPERATION_LABELS.get(held.operation_type, held.operation_type)

        return ValidationError({
            "asset": (
                f"Aset ini sedang dipesan {label} "
                f"{held.document_number or held.document_id}."
            ),
        })

    @staticmethod
    def _issue(asset_id, operation_type, document_id, problem) -> dict:
        return {
            "asset_id": asset_id,
            "document": f"{operation_type}#{document_id}",
            "problem": problem,
        }
