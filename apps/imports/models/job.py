from __future__ import annotations

import uuid

from django.conf import settings
from django.db import models

from apps.core.models import BaseModel
from apps.uploads.models import UploadedFile

class ImportJobStatus(models.TextChoices):

    PENDING = ("pending","Pending")
    PROCESSING = ("processing","Processing")
    COMPLETED = ("completed","Completed")
    PARTIAL = ("partial","Partial")
    FAILED = ("failed","Failed")


class ImportJob(BaseModel,):
    public_id = models.UUIDField(default=uuid.uuid4,editable=False,unique=True)

    module = models.CharField(max_length=100,db_index=True)

    profile_code = models.CharField(max_length=100,blank=True,default="",)
    profile_name = models.CharField(max_length=200,blank=True,default="")

    filename = models.CharField(max_length=255,blank=True,default="")
    source_type = models.CharField(max_length=50,blank=True,default="")
    source_file = models.ForeignKey(UploadedFile,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="import_jobs",
    )

    status = models.CharField(
        max_length=20,
        choices=ImportJobStatus.choices,
        default=ImportJobStatus.PENDING,
        db_index=True,
    )

    total_rows = models.PositiveIntegerField(default=0)
    valid_rows = models.PositiveIntegerField(default=0)
    invalid_rows = models.PositiveIntegerField(default=0)

    created_rows = models.PositiveIntegerField(default=0)
    updated_rows = models.PositiveIntegerField(default=0)

    duplicate_rows = models.PositiveIntegerField(default=0)
    skipped_rows = models.PositiveIntegerField(default=0)
    failed_rows = models.PositiveIntegerField(default=0)

    started_at = models.DateTimeField(null=True,blank=True)
    finished_at = models.DateTimeField(null=True,blank=True)
    duration_ms = models.PositiveBigIntegerField(default=0,)
    error_message = models.TextField(blank=True,default="")
    metadata = models.JSONField(default=dict,blank=True)

    imported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="import_jobs",
    )

    class Meta:
        db_table = "imports_import_job"

        ordering = [
            "-created_at",
            "-id",
        ]

        indexes = [
            models.Index(
                fields=[
                    "module",
                    "created_at",
                ],
            ),
            models.Index(
                fields=[
                    "status",
                    "created_at",
                ],
            ),
        ]

    @classmethod
    def readable_for(cls, user):
        """
        Baris yang boleh dibaca `user` — jawaban model ini sendiri.

        `ImportJob` dilayani sekumpulan `APIView`, bukan viewset, jadi
        tidak ada `data_scope`/`require_view_permission` yang bisa
        dibaca `framework.authority`. Hook ini yang menjawabkannya,
        dan lewat hook inilah `source_file` ikut menyempit tanpa
        `apps/uploads` perlu tahu bahwa import itu ada.
        """
        from apps.imports.authority import readable_jobs

        return readable_jobs(cls.objects.filter(is_deleted=False), user)

    def __str__(self) -> str:
        return (
            f"{self.module} - "
            f"{self.filename or self.public_id}"
        )