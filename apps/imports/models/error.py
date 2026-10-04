from __future__ import annotations

from django.db import models

from apps.core.models import BaseModel

from .job import ImportJob


class ImportJobError(BaseModel):
    job = models.ForeignKey(ImportJob,on_delete=models.CASCADE,related_name="errors",)
    row_number = models.PositiveIntegerField(null=True,blank=True,)
    field_name = models.CharField(max_length=100,blank=True,default="",)
    code = models.CharField(max_length=100,blank=True,default="")
    message = models.TextField()
    employee_code = models.CharField(max_length=100,blank=True,default="",)
    raw_data = models.JSONField(default=dict,blank=True,)

    class Meta:
        db_table = "imports_import_job_error"

        ordering = [
            "row_number",
            "id",
        ]

        indexes = [
            models.Index(
                fields=[
                    "job",
                    "row_number",
                ],
            ),
            models.Index(
                fields=[
                    "job",
                    "field_name",
                ],
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.job_id} - "
            f"Row {self.row_number or '-'}"
        )