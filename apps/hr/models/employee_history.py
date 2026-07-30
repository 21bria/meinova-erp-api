from django.db import models
from apps.core.models.base import BaseModel
from apps.hr.models import (
    Employee,
)

class EmployeeMovement(BaseModel):
    MOVEMENT_TYPES = [
        ("promotion", "Promotion"),
        ("transfer", "Transfer"),
        ("termination", "Termination"),
        ("retirement", "Retirement"),
        ("rehire", "Rehire"),
    ]

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="movements",
    )

    movement_type = models.CharField(
        max_length=30,
        choices=MOVEMENT_TYPES,
    )

    effective_date = models.DateField()

    reason = models.TextField(
        blank=True,
        default="",
    )

    from_company = models.ForeignKey(
        "administration.Company",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    to_company = models.ForeignKey(
        "administration.Company",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    from_position = models.ForeignKey(
        "administration.Position",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    to_position = models.ForeignKey(
        "administration.Position",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    notes = models.TextField(
        blank=True,
        default="",
    )

    class Meta:
        db_table = "hr_employee_movement"
        ordering = ["-effective_date", "-created_at"]