from django.db import models

from apps.core.models import BaseModel


class OvertimeGroup(BaseModel):
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

    hourly_multiplier = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        default=1,
    )
    maximum_hours_per_day = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
    )
    maximum_hours_per_month = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
    )

    is_active = models.BooleanField(
        default=True,
    )

    class Meta:
        db_table = "payroll_overtime_group"
        ordering = ["code"]
        verbose_name = "Overtime Group"
        verbose_name_plural = "Overtime Groups"

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"