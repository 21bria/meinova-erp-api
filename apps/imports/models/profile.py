from __future__ import annotations

from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel


class ImportProfile(BaseModel):
    """
    Konfigurasi import per module, tersimpan di database supaya klien
    dengan header file berbeda tidak perlu perubahan kode.

    `module` memakai nilai yang sama dengan `framework_module` pada
    ViewSet, mis. "hr/employees".
    """

    module = models.CharField(
        max_length=100,
        db_index=True,
    )

    code = models.CharField(
        max_length=50,
    )

    name = models.CharField(
        max_length=150,
    )

    description = models.TextField(
        blank=True,
        default="",
    )

    source_type = models.CharField(
        max_length=20,
        default="csv",
    )

    # Ruang lingkup opsional. Tidak dipakai saat memproses file, hanya
    # untuk menyaring pilihan profile — berguna pada klien multi-location
    # yang tiap lokasinya punya format file sendiri.
    company = models.ForeignKey(
        "administration.Company",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="import_profiles",
    )

    branch = models.ForeignKey(
        "administration.Branch",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="import_profiles",
    )

    location = models.ForeignKey(
        "administration.Location",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="import_profiles",
    )

    delimiter = models.CharField(
        max_length=5,
        default=",",
    )

    encoding = models.CharField(
        max_length=50,
        default="utf-8-sig",
    )

    # target -> alias header, menimpa mapping bawaan importer
    mapping = models.JSONField(
        default=dict,
        blank=True,
    )

    # target -> {nilai_file: nilai_sistem}
    value_mapping = models.JSONField(
        default=dict,
        blank=True,
    )

    datetime_formats = models.JSONField(
        default=list,
        blank=True,
    )

    # nilai default bila kolom kosong
    defaults = models.JSONField(
        default=dict,
        blank=True,
    )

    options = models.JSONField(
        default=dict,
        blank=True,
    )

    is_default = models.BooleanField(
        default=False,
    )

    sort_order = models.PositiveSmallIntegerField(
        default=0,
    )

    class Meta:
        db_table = "imports_import_profile"

        ordering = [
            "module",
            "sort_order",
            "name",
        ]

        indexes = [
            models.Index(
                fields=[
                    "module",
                    "is_active",
                ],
                name="idx_import_profile_module",
            ),
        ]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "module",
                    "code",
                ],
                condition=Q(is_deleted=False),
                name="uniq_active_import_profile_code",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.module} - {self.name}"

    @property
    def parser_options(self) -> dict:
        return {
            "encoding": self.encoding,
            "delimiter": self.delimiter,
        }
