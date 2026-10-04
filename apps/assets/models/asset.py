from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Upper

from apps.core.models.base import BaseModel

from .choices import AssetCondition, AssetStatus


class Asset(BaseModel):
    """
    Identitas satu unit fisik yang dilacak sendiri-sendiri.

    **Bukan nilai uang.** Harga perolehan, nilai buku, dan penyusutan
    milik `AssetBook` di tahap Fixed Asset — satu angka di dua tempat
    pasti berselisih.

    **`location`/`facility` punya dua arti menurut status, dan hanya
    satu penulis di tiap arti** (`docs/claude/assets.md` §6):

    * DRAFT — penempatan awal yang diinginkan; disunting lewat form.
    * ACTIVE — salinan custody yang sedang terbuka. Authority-nya
      `AssetCustody`; kolom ini hanya ditulis `AssetCustodyService` di
      transaksi yang sama, dan PATCH yang mencoba memindahkannya ditolak.

    Salinan itu ada demi `data_scope` (satu jalur ORM untuk DRAFT dan
    ACTIVE) dan filter tabel. `location` wajib sejak DRAFT: dengan
    `DATA_SCOPE_INCLUDE_NULL=False`, draft tanpa lokasi tidak terlihat
    oleh siapa pun kecuali superuser, tanpa pesan.
    """

    company = models.ForeignKey(
        "administration.Company",
        on_delete=models.PROTECT,
        related_name="assets",
    )

    # Diisi service dari `DocumentNumberService` (AST). Tidak pernah
    # ditulis klien dan tidak berubah sesudah dibuat.
    asset_code = models.CharField(max_length=50)

    category = models.ForeignKey(
        "assets.AssetCategory",
        on_delete=models.PROTECT,
        related_name="assets",
    )

    name = models.CharField(max_length=200)
    description = models.TextField(blank=True, default="")

    manufacturer = models.CharField(max_length=100, blank=True, default="")
    model = models.CharField(max_length=100, blank=True, default="")

    # Identitas fisik, opsional. Kosong = tidak ada (bukan nilai). Unik
    # per company tanpa membedakan huruf di antara aset yang belum
    # dihapus — bukan pengenal bisnis; pengenalnya `asset_code`.
    serial_number = models.CharField(max_length=100, blank=True, default="")
    tag_number = models.CharField(max_length=100, blank=True, default="")

    # Metadata perolehan **non-moneter**. Referensi teks sampai SCM ada.
    acquisition_date = models.DateField(null=True, blank=True)
    acquisition_reference = models.CharField(
        max_length=150,
        blank=True,
        default="",
    )
    supplier_name = models.CharField(max_length=200, blank=True, default="")
    warranty_until = models.DateField(null=True, blank=True)

    condition = models.CharField(
        max_length=20,
        choices=AssetCondition.choices,
        default=AssetCondition.GOOD,
    )

    status = models.CharField(
        max_length=20,
        choices=AssetStatus.choices,
        default=AssetStatus.DRAFT,
        db_index=True,
    )

    location = models.ForeignKey(
        "administration.Location",
        on_delete=models.PROTECT,
        related_name="assets",
    )

    facility = models.ForeignKey(
        "administration.Facility",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="assets",
    )

    current_custody = models.OneToOneField(
        "assets.AssetCustody",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    activated_at = models.DateTimeField(null=True, blank=True)

    activated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    class Meta:
        db_table = "assets_asset"
        ordering = ["company", "asset_code"]
        verbose_name = "Asset"
        verbose_name_plural = "Assets"

        constraints = [
            models.UniqueConstraint(
                fields=["company", "asset_code"],
                condition=Q(is_deleted=False),
                name="uniq_active_assets_asset_company_code",
            ),
            # Serial dan tag: unik per company **tanpa membedakan
            # huruf**, hanya bila terisi, hanya di antara baris yang
            # belum dihapus. Company berbeda boleh punya serial sama.
            models.UniqueConstraint(
                F("company"),
                Upper("serial_number"),
                condition=Q(is_deleted=False) & ~Q(serial_number=""),
                name="uniq_active_assets_asset_company_serial",
            ),
            models.UniqueConstraint(
                F("company"),
                Upper("tag_number"),
                condition=Q(is_deleted=False) & ~Q(tag_number=""),
                name="uniq_active_assets_asset_company_tag",
            ),
            models.CheckConstraint(
                condition=~Q(asset_code=""),
                name="ck_assets_asset_code_present",
            ),
            # ACTIVE ⇔ punya custody terbuka. DRAFT tidak punya custody.
            models.CheckConstraint(
                condition=(
                    Q(status=AssetStatus.DRAFT, current_custody__isnull=True)
                    | Q(status=AssetStatus.ACTIVE, current_custody__isnull=False)
                ),
                name="ck_assets_asset_status_custody",
            ),
        ]

        indexes = [
            models.Index(
                fields=["company", "status"],
                name="idx_asset_company_status",
            ),
            models.Index(
                fields=["location", "status"],
                name="idx_asset_location_status",
            ),
        ]

    def __str__(self):
        return f"{self.asset_code} — {self.name}"

    def clean(self):
        """
        Lapisan terakhir — pola `Facility.clean()`.

        Dropdown yang tersaring bisa dilewati dengan menembak API
        langsung; ini yang menolak lokasi atau fasilitas company lain.
        """
        super().clean()

        errors = {}

        if self.location_id and self.company_id:
            if self.location.company_id != self.company_id:
                errors["location"] = (
                    "Lokasi ini bukan milik company aset."
                )

        if self.facility_id:
            if self.company_id and self.facility.company_id != self.company_id:
                errors["facility"] = (
                    "Fasilitas ini bukan milik company aset."
                )
            elif self.location_id and self.facility.location_id != self.location_id:
                errors["facility"] = (
                    "Fasilitas ini tidak berada di lokasi yang dipilih."
                )

        if errors:
            raise ValidationError(errors)
