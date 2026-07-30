from django.db import models

from apps.core.models import BaseModel


class PayrollGroup(BaseModel):
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
    pay_frequency = models.CharField(
        max_length=20,
        default="monthly",
    )
    is_active = models.BooleanField(
        default=True,
    )

    class Meta:
        db_table = "payroll_group"
        ordering = ["name"]
        verbose_name = "Payroll Group"
        verbose_name_plural = "Payroll Groups"

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"