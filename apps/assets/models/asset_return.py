from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models.base import BaseModel

from .choices import AssetCondition, CustodyType, ReturnReason, ReturnStatus


class AssetReturn(BaseModel):
    """
    Pengembalian satu aset dari pemakaian (EMPLOYEE/ORGANIZATION) ke
    STORAGE milik pemilik. **Bukan perubahan kepemilikan.**

    Satu dokumen = satu aset (ASSET-4), seperti Assignment. Pemesanan
    asetnya lewat `AssetOperationReservation` — authority bersama dengan
    Assignment dan kelak Transfer — bukan constraint per tabel dokumen.

    Asal (`source_*`) disalin dari custody yang sedang terbuka saat draft
    dibuat, tidak pernah dari klien. Approval **tidak** memindahkan
    custody; hanya `complete`, lewat `AssetCustodyService.move`.
    Kontraknya: `docs/claude/assets.md` §11.
    """

    document_number = models.CharField(max_length=50, blank=True, default="")

    # Pemilik aset — disalin dari `asset.company`, tidak pernah berubah.
    company = models.ForeignKey(
        "administration.Company",
        on_delete=models.PROTECT,
        related_name="asset_returns",
    )

    asset = models.ForeignKey(
        "assets.Asset",
        on_delete=models.PROTECT,
        related_name="returns",
    )

    status = models.CharField(
        max_length=20,
        choices=ReturnStatus.choices,
        default=ReturnStatus.DRAFT,
        db_index=True,
    )

    # ------------------------------------------------------------------
    # Asal — salinan custody pemakaian yang terbuka saat dokumen dibuat.
    # `submit`/`complete` menolak bila custody aset sudah bukan baris ini.
    # ------------------------------------------------------------------

    source_custody = models.ForeignKey(
        "assets.AssetCustody",
        on_delete=models.PROTECT,
        related_name="+",
    )
    source_custody_type = models.CharField(
        max_length=20,
        choices=[
            (CustodyType.EMPLOYEE, CustodyType.EMPLOYEE.label),
            (CustodyType.ORGANIZATION, CustodyType.ORGANIZATION.label),
        ],
    )
    # Jalur cakupan sisi asal.
    source_location = models.ForeignKey(
        "administration.Location",
        on_delete=models.PROTECT,
        related_name="+",
    )
    source_facility = models.ForeignKey(
        "administration.Facility",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    source_employee = models.ForeignKey(
        "hr.Employee",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="asset_returns",
    )
    source_department = models.ForeignKey(
        "administration.Department",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    source_pic_employee = models.ForeignKey(
        "hr.Employee",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    # ------------------------------------------------------------------
    # Tujuan — penyimpanan milik company pemilik. Jalur cakupan sisi tujuan.
    # ------------------------------------------------------------------

    destination_location = models.ForeignKey(
        "administration.Location",
        on_delete=models.PROTECT,
        related_name="asset_returns",
    )
    destination_facility = models.ForeignKey(
        "administration.Facility",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="asset_returns",
    )

    # ------------------------------------------------------------------
    # Isi
    # ------------------------------------------------------------------

    reason = models.CharField(max_length=20, choices=ReturnReason.choices)
    notes = models.TextField(blank=True, default="")

    # Diisi saat complete: tanggal barang benar-benar diterima kembali
    # (bawaan hari itu) dan kondisinya — wajib, supaya kondisi saat kembali
    # selalu diketahui.
    return_date = models.DateField(null=True, blank=True)
    return_condition = models.CharField(
        max_length=20,
        choices=AssetCondition.choices,
        blank=True,
        default="",
    )

    resulting_custody = models.OneToOneField(
        "assets.AssetCustody",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    submitted_at = models.DateTimeField(null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    rejected_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    completed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        db_table = "assets_asset_return"
        ordering = ["-created_at", "-id"]
        verbose_name = "Asset Return"
        verbose_name_plural = "Asset Returns"

        permissions = [
            ("submit_assetreturn", "Can submit asset return"),
            ("complete_assetreturn", "Can complete asset return"),
            ("cancel_assetreturn", "Can cancel asset return"),
        ]

        constraints = [
            models.UniqueConstraint(
                fields=["company", "document_number"],
                condition=Q(is_deleted=False) & ~Q(document_number=""),
                name="uniq_active_assets_return_number",
            ),
            # Bentuk asal mengikuti bentuk custody pemakaian (§8).
            models.CheckConstraint(
                condition=(
                    Q(
                        source_custody_type=CustodyType.EMPLOYEE,
                        source_employee__isnull=False,
                        source_department__isnull=True,
                        source_pic_employee__isnull=True,
                    )
                    | Q(
                        source_custody_type=CustodyType.ORGANIZATION,
                        source_employee__isnull=True,
                        source_department__isnull=False,
                    )
                ),
                name="ck_assets_return_source_shape",
            ),
            models.CheckConstraint(
                condition=(
                    ~Q(status=ReturnStatus.COMPLETED)
                    | (
                        Q(
                            resulting_custody__isnull=False,
                            return_date__isnull=False,
                        )
                        & ~Q(return_condition="")
                    )
                ),
                name="ck_assets_return_completed_has_custody",
            ),
        ]

        indexes = [
            models.Index(
                fields=["company", "status"],
                name="idx_assets_return_co_status",
            ),
            models.Index(
                fields=["source_employee", "status"],
                name="idx_assets_return_emp_status",
            ),
        ]

    def __str__(self):
        return self.document_number or f"Return #{self.pk}"
