from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models.base import BaseModel

from .choices import AssetCondition, CustodyType, TransferReason, TransferStatus


USAGE = (CustodyType.EMPLOYEE, CustodyType.ORGANIZATION)


def _holder_shape(prefix: str) -> Q:
    """Bentuk pemegang per jenis custody (§8) untuk kolom `<prefix>_*`."""
    kind = f"{prefix}_custody_type"
    employee = f"{prefix}_employee__isnull"
    department = f"{prefix}_department__isnull"
    pic = f"{prefix}_pic_employee__isnull"

    return (
        Q(**{kind: CustodyType.STORAGE, employee: True, department: True, pic: True})
        | Q(**{kind: CustodyType.EMPLOYEE, employee: False, department: True, pic: True})
        | Q(**{kind: CustodyType.ORGANIZATION, employee: True, department: False})
    )


class AssetTransfer(BaseModel):
    """
    Perpindahan satu aset dari custody aktif ke custody aktif lain **di
    fase yang sama** — pemakaian → pemakaian, atau STORAGE → STORAGE.
    **Bukan perubahan kepemilikan.**

    STORAGE → pemakaian adalah Assignment; pemakaian → STORAGE adalah
    Return. Batas itu dijaga service **dan** database
    (`ck_assets_transfer_same_phase`), supaya tiga dokumen pergerakan tidak
    pernah tumpang tindih.

    Satu dokumen = satu aset. Pemesanan lewat `AssetOperationReservation`.
    Ganti PIC resmi (department sama, PIC lain) adalah Transfer; pemakai
    harian/sopir bukan custody dan tidak punya kolom di sini (O-5).
    Kontraknya: `docs/claude/assets.md` §10.
    """

    document_number = models.CharField(max_length=50, blank=True, default="")

    # Pemilik aset — disalin dari `asset.company`, tidak pernah berubah.
    company = models.ForeignKey(
        "administration.Company",
        on_delete=models.PROTECT,
        related_name="asset_transfers",
    )

    asset = models.ForeignKey(
        "assets.Asset",
        on_delete=models.PROTECT,
        related_name="transfers",
    )

    status = models.CharField(
        max_length=20,
        choices=TransferStatus.choices,
        default=TransferStatus.DRAFT,
        db_index=True,
    )

    # ------------------------------------------------------------------
    # Asal — salinan custody terbuka saat dokumen dibuat. `submit` dan
    # `complete` menolak bila custody aset sudah bukan baris ini.
    # ------------------------------------------------------------------

    source_custody = models.ForeignKey(
        "assets.AssetCustody",
        on_delete=models.PROTECT,
        related_name="+",
    )
    source_custody_type = models.CharField(max_length=20, choices=CustodyType.choices)
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
        related_name="asset_transfers_out",
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
    # Tujuan
    # ------------------------------------------------------------------

    target_custody_type = models.CharField(max_length=20, choices=CustodyType.choices)
    target_employee = models.ForeignKey(
        "hr.Employee",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="asset_transfers_in",
    )
    target_department = models.ForeignKey(
        "administration.Department",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="asset_transfers_in",
    )
    target_pic_employee = models.ForeignKey(
        "hr.Employee",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="asset_pic_transfers_in",
    )
    # Lokasi fisik tujuan — selalu milik company pemilik. Jalur cakupan
    # sisi tujuan.
    target_location = models.ForeignKey(
        "administration.Location",
        on_delete=models.PROTECT,
        related_name="asset_transfers_in",
    )
    target_facility = models.ForeignKey(
        "administration.Facility",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="asset_transfers_in",
    )

    # Jejak organisasi pegawai tujuan (EMPLOYEE) — dari OrganizationAssignment,
    # dibekukan saat complete. Diturunkan ulang dari **tujuan**, tidak
    # diwariskan dari asal.
    employee_company = models.ForeignKey(
        "administration.Company",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    employee_location = models.ForeignKey(
        "administration.Location",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    employee_department = models.ForeignKey(
        "administration.Department",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    is_cross_company = models.BooleanField(default=False)
    cross_company_reason = models.TextField(blank=True, default="")

    # ------------------------------------------------------------------
    # Isi + penyelesaian
    # ------------------------------------------------------------------

    reason = models.CharField(max_length=20, choices=TransferReason.choices)
    notes = models.TextField(blank=True, default="")

    transfer_date = models.DateField(null=True, blank=True)
    transfer_condition = models.CharField(
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
        db_table = "assets_asset_transfer"
        ordering = ["-created_at", "-id"]
        verbose_name = "Asset Transfer"
        verbose_name_plural = "Asset Transfers"

        permissions = [
            ("submit_assettransfer", "Can submit asset transfer"),
            ("complete_assettransfer", "Can complete asset transfer"),
            ("cancel_assettransfer", "Can cancel asset transfer"),
        ]

        constraints = [
            models.UniqueConstraint(
                fields=["company", "document_number"],
                condition=Q(is_deleted=False) & ~Q(document_number=""),
                name="uniq_active_assets_transfer_number",
            ),
            models.CheckConstraint(
                condition=_holder_shape("source"),
                name="ck_assets_transfer_source_shape",
            ),
            models.CheckConstraint(
                condition=_holder_shape("target"),
                name="ck_assets_transfer_target_shape",
            ),
            # Batas semantik dengan Assignment/Return: fase tidak berganti.
            models.CheckConstraint(
                condition=(
                    Q(
                        source_custody_type=CustodyType.STORAGE,
                        target_custody_type=CustodyType.STORAGE,
                    )
                    | Q(
                        source_custody_type__in=USAGE,
                        target_custody_type__in=USAGE,
                    )
                ),
                name="ck_assets_transfer_same_phase",
            ),
            models.CheckConstraint(
                condition=(
                    ~Q(status=TransferStatus.COMPLETED)
                    | (
                        Q(
                            resulting_custody__isnull=False,
                            transfer_date__isnull=False,
                        )
                        & ~Q(transfer_condition="")
                    )
                ),
                name="ck_assets_transfer_completed_has_custody",
            ),
            models.CheckConstraint(
                condition=Q(is_cross_company=False) | ~Q(cross_company_reason=""),
                name="ck_assets_transfer_cross_company_reason",
            ),
        ]

        indexes = [
            models.Index(
                fields=["company", "status"],
                name="idx_assets_transfer_co_status",
            ),
            models.Index(
                fields=["source_employee", "status"],
                name="idx_assets_transfer_src_emp",
            ),
            models.Index(
                fields=["target_employee", "status"],
                name="idx_assets_transfer_tgt_emp",
            ),
        ]

    def __str__(self):
        return self.document_number or f"Transfer #{self.pk}"
