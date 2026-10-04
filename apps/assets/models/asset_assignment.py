from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models.base import BaseModel

from .choices import (
    AssetCondition,
    AssignmentStatus,
    CustodyType,
)


class AssetAssignment(BaseModel):
    """
    Penyerahan satu aset dari STORAGE ke pemakaian — pegawai (EMPLOYEE)
    atau unit (ORGANIZATION). **Bukan perubahan kepemilikan.**

    Satu dokumen = satu aset. Pemesanan asetnya dipegang
    `AssetOperationReservation` — authority bersama Assignment, Return,
    dan kelak Transfer (sejak ASSET-4; sebelumnya constraint per tabel
    ini). Serah terima beberapa aset ke satu penerima = beberapa dokumen.

    Approval **tidak** memindahkan custody. Custody hanya berpindah saat
    `complete` (barang benar-benar diserahkan), lewat
    `AssetCustodyService.move`. Kontraknya: `docs/claude/assets.md` §9.
    """

    document_number = models.CharField(max_length=50, blank=True, default="")

    # Pemilik aset — disalin dari `asset.company`, tidak pernah berubah.
    company = models.ForeignKey(
        "administration.Company",
        on_delete=models.PROTECT,
        related_name="asset_assignments",
    )

    asset = models.ForeignKey(
        "assets.Asset",
        on_delete=models.PROTECT,
        related_name="assignments",
    )

    status = models.CharField(
        max_length=20,
        choices=AssignmentStatus.choices,
        default=AssignmentStatus.DRAFT,
        db_index=True,
    )

    # ------------------------------------------------------------------
    # Asal — custody STORAGE yang diharapkan saat dokumen dibuat/diajukan.
    # `complete` menolak bila custody aset sudah bukan baris ini lagi.
    # ------------------------------------------------------------------

    source_custody = models.ForeignKey(
        "assets.AssetCustody",
        on_delete=models.PROTECT,
        related_name="+",
    )

    # Lokasi penyimpanan asal — juga jalur cakupan data dokumen ini
    # (lokasi pemilik, bukan lokasi penerima).
    source_location = models.ForeignKey(
        "administration.Location",
        on_delete=models.PROTECT,
        related_name="+",
    )

    # ------------------------------------------------------------------
    # Tujuan
    # ------------------------------------------------------------------

    target_custody_type = models.CharField(
        max_length=20,
        choices=[
            (CustodyType.EMPLOYEE, CustodyType.EMPLOYEE.label),
            (CustodyType.ORGANIZATION, CustodyType.ORGANIZATION.label),
        ],
    )

    employee = models.ForeignKey(
        "hr.Employee",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="asset_assignments",
    )

    department = models.ForeignKey(
        "administration.Department",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="asset_assignments",
    )

    pic_employee = models.ForeignKey(
        "hr.Employee",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="asset_pic_assignments",
    )

    # Lokasi fisik tujuan — selalu milik company pemilik. Boleh berbeda
    # dari penempatan pegawai (O-2); penempatannya tidak disentuh.
    location = models.ForeignKey(
        "administration.Location",
        on_delete=models.PROTECT,
        related_name="asset_assignments",
    )

    facility = models.ForeignKey(
        "administration.Facility",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="asset_assignments",
    )

    # ------------------------------------------------------------------
    # Jejak organisasi penerima (EMPLOYEE) — referensi ke master kanonik
    # dari `OrganizationAssignment`, dibekukan saat complete. Bukan master
    # baru: hanya FK, supaya "saat diserahkan ia bekerja di mana" tetap
    # terbaca sesudah pegawainya dimutasi.
    # ------------------------------------------------------------------

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

    # Penerima berpenempatan di company lain (O-8). Diturunkan service,
    # tidak pernah dari klien — dan tidak pernah implisit: dokumen
    # lintas company harus menyatakannya lewat `cross_company_reason`.
    is_cross_company = models.BooleanField(default=False)
    cross_company_reason = models.TextField(blank=True, default="")

    # ------------------------------------------------------------------
    # Isi
    # ------------------------------------------------------------------

    purpose = models.TextField(blank=True, default="")
    notes = models.TextField(blank=True, default="")

    # Tanggal serah terima sungguhan — diisi saat complete (bawaan hari
    # itu), tidak boleh di masa depan.
    handover_date = models.DateField(null=True, blank=True)
    handover_condition = models.CharField(
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
        db_table = "assets_asset_assignment"
        ordering = ["-created_at", "-id"]
        verbose_name = "Asset Assignment"
        verbose_name_plural = "Asset Assignments"

        # Aksi alur punya izinnya sendiri — "boleh mengubah draft" tidak
        # sama dengan "boleh menyerahkan barang". Approve/reject bukan di
        # sini: haknya milik engine workflow (pemegang meja).
        permissions = [
            ("submit_assetassignment", "Can submit asset assignment"),
            ("complete_assetassignment", "Can complete asset assignment"),
            ("cancel_assetassignment", "Can cancel asset assignment"),
        ]

        constraints = [
            models.UniqueConstraint(
                fields=["company", "document_number"],
                condition=Q(is_deleted=False) & ~Q(document_number=""),
                name="uniq_active_assets_assignment_number",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        target_custody_type=CustodyType.EMPLOYEE,
                        employee__isnull=False,
                        department__isnull=True,
                        pic_employee__isnull=True,
                    )
                    | Q(
                        target_custody_type=CustodyType.ORGANIZATION,
                        employee__isnull=True,
                        department__isnull=False,
                    )
                ),
                name="ck_assets_assignment_target_shape",
            ),
            models.CheckConstraint(
                condition=(
                    ~Q(status=AssignmentStatus.COMPLETED)
                    | Q(
                        resulting_custody__isnull=False,
                        handover_date__isnull=False,
                    )
                ),
                name="ck_assets_assignment_completed_has_custody",
            ),
            models.CheckConstraint(
                condition=Q(is_cross_company=False) | ~Q(cross_company_reason=""),
                name="ck_assets_assignment_cross_company_reason",
            ),
        ]

        indexes = [
            models.Index(
                fields=["company", "status"],
                name="idx_assets_assign_co_status",
            ),
            models.Index(
                fields=["employee", "status"],
                name="idx_assets_assign_emp_status",
            ),
        ]

    def __str__(self):
        return self.document_number or f"Assignment #{self.pk}"
