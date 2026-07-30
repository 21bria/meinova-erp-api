from django.db import models

from apps.core.models import BaseModel


class DeductionTemplate(BaseModel):
    code = models.CharField(
        max_length=30,
        unique=True,
    )
    name = models.CharField(
        max_length=150,
    )
    description = models.TextField(
        blank=True,
    )

    is_active = models.BooleanField(
        default=True,
    )

    class Meta:
        db_table = "payroll_deduction_template"
        ordering = ["code"]
        verbose_name = "Deduction Template"
        verbose_name_plural = "Deduction Templates"

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"