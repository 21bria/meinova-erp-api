from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models.base import BaseModel

from apps.administration.models import (
    TrainingCategory,
    TrainingProvider,
)

from .employee import Employee


class EmployeeTraining(BaseModel):
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="trainings",
    )

    training_category = models.ForeignKey(
        TrainingCategory,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_trainings",
    )

    training_name = models.CharField(
        max_length=200,
    )

    provider = models.ForeignKey(
        TrainingProvider,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_trainings",
    )

    start_date = models.DateField()

    end_date = models.DateField(
        null=True,
        blank=True,
    )

    duration_hours = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
    )

    score = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
    )

    certificate_number = models.CharField(
        max_length=100,
        blank=True,
        default="",
    )

    expiry_date = models.DateField(
        null=True,
        blank=True,
    )

    attachment = models.FileField(
        upload_to="employees/trainings/",
        null=True,
        blank=True,
    )

    is_mandatory = models.BooleanField(
        default=False,
    )

    is_completed = models.BooleanField(
        default=True,
    )

    is_active = models.BooleanField(
        default=True,
    )

    notes = models.TextField(
        blank=True,
        default="",
    )

    class Meta:
        db_table = "hr_employee_training"

        ordering = [
            "-start_date",
            "training_name",
        ]

        indexes = [
            models.Index(
                fields=["employee"],
                name="idx_emp_training_employee",
            ),
            models.Index(
                fields=["training_category"],
                name="idx_emp_training_category",
            ),
            models.Index(
                fields=["expiry_date"],
                name="idx_emp_training_expiry",
            ),
        ]

    def clean(self):
        super().clean()

        errors = {}

        if (
            self.start_date
            and self.end_date
            and self.end_date < self.start_date
        ):
            errors["end_date"] = (
                "End Date tidak boleh lebih awal dari Start Date."
            )

        if (
            self.end_date
            and self.expiry_date
            and self.expiry_date < self.end_date
        ):
            errors["expiry_date"] = (
                "Expiry Date tidak boleh lebih awal dari End Date."
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return (
            f"{self.employee.employee_number} - "
            f"{self.training_name}"
        )