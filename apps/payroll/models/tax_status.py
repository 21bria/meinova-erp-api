from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel


class TaxStatus(BaseModel):
    code = models.CharField(
        max_length=20,
    )
    name = models.CharField(
        max_length=150,
    )
    description = models.TextField(
        blank=True,
    )
    non_taxable_income = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        default=0,
    )
    is_active = models.BooleanField(
        default=True,
    )

    class Meta:
        db_table = "payroll_tax_status"
        ordering = ["code"]
        verbose_name = "Tax Status"
        verbose_name_plural = "Tax Statuses"

        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                condition=Q(is_deleted=False),
                name="uniq_active_payroll_taxstatus_code",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"