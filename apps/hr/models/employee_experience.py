from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models.base import BaseModel

from .employee import Employee


class EmployeeExperience(BaseModel):
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="experiences",
    )

    company_name = models.CharField(
        max_length=200,
    )

    position_name = models.CharField(
        max_length=200,
    )

    employment_type = models.CharField(
        max_length=100,
        blank=True,
        default="",
    )

    industry = models.CharField(
        max_length=150,
        blank=True,
        default="",
    )

    location = models.CharField(
        max_length=200,
        blank=True,
        default="",
    )

    start_date = models.DateField()

    end_date = models.DateField(
        null=True,
        blank=True,
    )

    is_current = models.BooleanField(
        default=False,
    )

    last_salary = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
    )

    job_description = models.TextField(
        blank=True,
        default="",
    )

    reason_for_leaving = models.TextField(
        blank=True,
        default="",
    )

    reference_name = models.CharField(
        max_length=200,
        blank=True,
        default="",
    )

    reference_phone = models.CharField(
        max_length=50,
        blank=True,
        default="",
    )

    is_verified = models.BooleanField(
        default=False,
    )

    is_active = models.BooleanField(
        default=True,
    )

    notes = models.TextField(
        blank=True,
        default="",
    )

    class Meta:
        db_table = "hr_employee_experience"

        ordering = [
            "-is_current",
            "-start_date",
            "company_name",
        ]

        indexes = [
            models.Index(
                fields=["employee"],
                name="idx_emp_exp_employee",
            ),
            models.Index(
                fields=["company_name"],
                name="idx_emp_exp_company",
            ),
            models.Index(
                fields=["is_current"],
                name="idx_emp_exp_current",
            ),
            models.Index(
                fields=["is_verified"],
                name="idx_emp_exp_verified",
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
                "End Date tidak boleh lebih awal "
                "dari Start Date."
            )

        if self.is_current and self.end_date:
            errors["end_date"] = (
                "End Date harus kosong jika pengalaman "
                "masih berlangsung."
            )

        if (
            self.last_salary is not None
            and self.last_salary < 0
        ):
            errors["last_salary"] = (
                "Last Salary tidak boleh bernilai negatif."
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return (
            f"{self.employee.employee_number} - "
            f"{self.company_name} - "
            f"{self.position_name}"
        )