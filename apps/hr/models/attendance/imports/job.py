from django.db import models

from apps.core.models import (
    BaseModel,
)
from .profile import (
    AttendanceImportProfile,
)


class AttendanceImportJob(
    BaseModel,
):
    profile = models.ForeignKey(
        AttendanceImportProfile,
        on_delete=models.PROTECT,
        related_name="jobs",
    )

    filename = models.CharField(
        max_length=255,
    )

    source_type = models.CharField(
        max_length=20,
    )

    status = models.CharField(
        max_length=30,
        default="pending",
    )

    total_rows = models.PositiveIntegerField(
        default=0,
    )

    valid_rows = models.PositiveIntegerField(
        default=0,
    )

    invalid_rows = models.PositiveIntegerField(
        default=0,
    )

    created_rows = models.PositiveIntegerField(
        default=0,
    )

    updated_rows = models.PositiveIntegerField(
        default=0,
    )

    skipped_rows = models.PositiveIntegerField(
        default=0,
    )

    failed_rows = models.PositiveIntegerField(
        default=0,
    )

    started_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    finished_at = models.DateTimeField(
        null=True,
        blank=True,
    )

    error_message = models.TextField(
        blank=True,
    )

    class Meta:
        ordering = [
            "-created_at",
        ]

    def __str__(self):
        return f"{self.filename} ({self.status})"