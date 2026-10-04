from __future__ import annotations

from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel


class AttendanceImportProfile(
    BaseModel,
):
    name = models.CharField(
        max_length=150,
    )

    code = models.CharField(
        max_length=50,
    )

    description = models.TextField(
        blank=True,
    )

    company = models.ForeignKey(
        "administration.Company",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name=(
            "attendance_import_profiles"
        ),
    )

    branch = models.ForeignKey(
        "administration.Branch",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name=(
            "attendance_import_profiles"
        ),
    )

    location = models.ForeignKey(
        "administration.Location",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name=(
            "attendance_import_profiles"
        ),
    )

    delimiter = models.CharField(
        max_length=5,
        default=",",
    )

    encoding = models.CharField(
        max_length=50,
        default="utf-8-sig",
    )

    mapping = models.JSONField(
        default=dict,
    )

    value_mapping = models.JSONField(
        default=dict,
        blank=True,
    )

    datetime_formats = models.JSONField(
        default=list,
        blank=True,
    )

    defaults = models.JSONField(
        default=dict,
        blank=True,
    )

    options = models.JSONField(
        default=dict,
        blank=True,
    )

    is_active = models.BooleanField(
        default=True,
    )

    class Meta:
        ordering = [
            "name",
        ]

        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                condition=Q(is_deleted=False),
                name="uniq_active_hr_attendanceimportprofile_code",
            ),
        ]

    def __str__(self) -> str:
        return self.name