from django.db import models
from django.db.models import F, Q

from apps.core.models.base import BaseModel

from .choices import AssetCondition, CustodyType


class AssetCustody(BaseModel):
    """
    Satu periode penguasaan aset — authority untuk "di mana / pada siapa
    aset ini sekarang" dan satu-satunya sumber riwayat custody **dan**
    riwayat lokasi (`docs/claude/assets.md` §8, §12).

    Ditulis hanya oleh `AssetCustodyService`. Isinya tidak pernah
    disunting dan barisnya tidak pernah dihapus; yang boleh berubah
    hanya penutupnya, sekali.

    Bentuk pemegang per jenis dijaga database
    (`ck_assets_custody_holder_shape`), bukan hanya service:

    * STORAGE — tanpa pegawai, department, maupun PIC;
    * EMPLOYEE — `employee` wajib; department dan PIC kosong (pegawai
      lintas company boleh, O-8 — pemiliknya tetap `company`);
    * ORGANIZATION — `department` wajib, `pic_employee` opsional,
      `employee` kosong. PIC = penanggung jawab resmi; pemakai harian
      tidak pernah dicatat di sini.

    `location` selalu milik company pemilik — juga untuk pegawai lintas
    company — supaya cakupan lokasi company penerima tidak membuka
    register milik company lain.
    """

    asset = models.ForeignKey(
        "assets.Asset",
        on_delete=models.PROTECT,
        related_name="custodies",
    )

    # Salinan `asset.company` — untuk scope dan constraint tanpa join.
    company = models.ForeignKey(
        "administration.Company",
        on_delete=models.PROTECT,
        related_name="asset_custodies",
    )

    custody_type = models.CharField(
        max_length=20,
        choices=CustodyType.choices,
    )

    employee = models.ForeignKey(
        "hr.Employee",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="asset_custodies",
    )

    pic_employee = models.ForeignKey(
        "hr.Employee",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="asset_pic_custodies",
    )

    department = models.ForeignKey(
        "administration.Department",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="asset_custodies",
    )

    # Wajib untuk semua jenis — di mana barangnya secara fisik.
    location = models.ForeignKey(
        "administration.Location",
        on_delete=models.PROTECT,
        related_name="asset_custodies",
    )

    facility = models.ForeignKey(
        "administration.Facility",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="asset_custodies",
    )

    started_on = models.DateField()
    ended_on = models.DateField(null=True, blank=True)

    start_condition = models.CharField(
        max_length=20,
        choices=AssetCondition.choices,
    )
    end_condition = models.CharField(
        max_length=20,
        choices=AssetCondition.choices,
        blank=True,
        default="",
    )

    # Dokumen sumber — pola module+type+id seperti engine workflow,
    # bukan GenericForeignKey: `registration`, `asset_assignment`, …
    opened_by_type = models.CharField(max_length=50)
    opened_by_id = models.CharField(max_length=50)
    closed_by_type = models.CharField(max_length=50, blank=True, default="")
    closed_by_id = models.CharField(max_length=50, blank=True, default="")

    class Meta:
        db_table = "assets_asset_custody"
        ordering = ["asset", "started_on", "id"]
        verbose_name = "Asset Custody"
        verbose_name_plural = "Asset Custodies"

        constraints = [
            # Invariant §12: satu aset, tepat satu custody terbuka.
            models.UniqueConstraint(
                fields=["asset"],
                condition=Q(ended_on__isnull=True, is_deleted=False),
                name="uniq_open_assets_custody_per_asset",
            ),
            models.CheckConstraint(
                condition=Q(ended_on__isnull=True) | Q(ended_on__gte=F("started_on")),
                name="ck_assets_custody_period",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        custody_type=CustodyType.STORAGE,
                        employee__isnull=True,
                        department__isnull=True,
                        pic_employee__isnull=True,
                    )
                    | Q(
                        custody_type=CustodyType.EMPLOYEE,
                        employee__isnull=False,
                        department__isnull=True,
                        pic_employee__isnull=True,
                    )
                    | Q(
                        custody_type=CustodyType.ORGANIZATION,
                        employee__isnull=True,
                        department__isnull=False,
                    )
                ),
                name="ck_assets_custody_holder_shape",
            ),
        ]

        indexes = [
            models.Index(
                fields=["location", "ended_on"],
                name="idx_assets_custody_loc_open",
            ),
            # "Apa saja yang dipegang pegawai ini sekarang" — dibaca
            # offboarding (§19) dan layar pegawai. Sengaja **bukan**
            # unique: satu pegawai boleh memegang banyak aset.
            models.Index(
                fields=["employee", "ended_on"],
                name="idx_assets_custody_emp_open",
            ),
            models.Index(
                fields=["pic_employee", "ended_on"],
                name="idx_assets_custody_pic_open",
            ),
        ]

    def __str__(self):
        return f"{self.asset_id} {self.custody_type} @ {self.location_id}"
