from django.conf import settings
from django.db import models
from django.db.models import F, Q

from .choices import AssetOperationType, ReservationRelease


class AssetOperationReservation(models.Model):
    """
    Satu-satunya authority "aset ini sedang diklaim dokumen operasional"
    (`docs/claude/assets.md` §26).

    Satu baris = satu dokumen (Assignment, Return, kelak Transfer) yang
    sedang memesan satu aset. Terbuka (`released_at IS NULL`) selama
    dokumennya SUBMITTED/APPROVED; ditutup — bukan dihapus — saat dokumen
    selesai, ditolak, dibatalkan, atau dikembalikan ke DRAFT. Barisnya
    tetap ada sebagai jejak siapa memesan kapan.

    Invariant di database, bukan hanya di service:

    * `uniq_active_assets_reservation_asset` — satu aset, paling banyak
      satu pemesanan terbuka, **lintas jenis dokumen**;
    * `uniq_active_assets_reservation_document` — satu dokumen, paling
      banyak satu pemesanan terbuka.

    Identitas dokumen = `operation_type` + `document_id`, tanpa
    GenericForeignKey (pola yang sama dengan `AssetCustody.opened_by_*`
    dan engine workflow). `AssetReservationService` memastikan pasangan
    itu menunjuk dokumen nyata atas aset yang sama.

    Bukan turunan `BaseModel`: soft delete akan menjadi jalan kedua untuk
    melepas pemesanan. Ditulis hanya oleh `AssetReservationService`.
    """

    asset = models.ForeignKey(
        "assets.Asset",
        on_delete=models.PROTECT,
        related_name="operation_reservations",
    )

    operation_type = models.CharField(
        max_length=20,
        choices=AssetOperationType.choices,
    )
    document_id = models.BigIntegerField()

    # Salinan untuk pesan "sedang dipesan ART-…" tanpa join ke tabel
    # dokumen yang jenisnya berbeda-beda.
    document_number = models.CharField(max_length=50, blank=True, default="")

    reserved_at = models.DateTimeField()
    reserved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    released_at = models.DateTimeField(null=True, blank=True)
    released_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    release_reason = models.CharField(
        max_length=20,
        choices=ReservationRelease.choices,
        blank=True,
        default="",
    )

    class Meta:
        db_table = "assets_asset_operation_reservation"
        ordering = ["asset", "reserved_at", "id"]
        verbose_name = "Asset Operation Reservation"
        verbose_name_plural = "Asset Operation Reservations"

        constraints = [
            models.UniqueConstraint(
                fields=["asset"],
                condition=Q(released_at__isnull=True),
                name="uniq_active_assets_reservation_asset",
            ),
            models.UniqueConstraint(
                fields=["operation_type", "document_id"],
                condition=Q(released_at__isnull=True),
                name="uniq_active_assets_reservation_document",
            ),
            models.CheckConstraint(
                condition=Q(operation_type__in=AssetOperationType.values),
                name="ck_assets_reservation_operation_type",
            ),
            # Terbuka = tanpa alasan lepas; tertutup = alasan wajib dan
            # tidak sebelum dipesan.
            models.CheckConstraint(
                condition=(
                    Q(released_at__isnull=True, release_reason="")
                    | (
                        Q(released_at__isnull=False)
                        & ~Q(release_reason="")
                        & Q(released_at__gte=F("reserved_at"))
                    )
                ),
                name="ck_assets_reservation_release_shape",
            ),
        ]

        indexes = [
            models.Index(
                fields=["operation_type", "document_id"],
                name="idx_assets_reserv_document",
            ),
        ]

    def __str__(self):
        state = "active" if self.released_at is None else self.release_reason
        return f"{self.asset_id} ← {self.operation_type}#{self.document_id} ({state})"
