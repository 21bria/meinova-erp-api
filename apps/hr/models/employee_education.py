from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models.base import BaseModel
from apps.administration.models import (
    Degree,
    Education,
    StudyField,
)

from .employee import Employee


class EmployeeEducation(BaseModel):
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="educations",
    )

    education = models.ForeignKey(
        Education,
        on_delete=models.PROTECT,
        related_name="employee_educations",
    )

    degree = models.ForeignKey(
        Degree,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_educations",
    )

    study_field = models.ForeignKey(
        StudyField,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_educations",
    )

    institution_name = models.CharField(
        max_length=200,
    )

    city = models.CharField(
        max_length=150,
        blank=True,
        default="",
    )

    country = models.CharField(
        max_length=100,
        blank=True,
        default="",
    )

    start_date = models.DateField(
        null=True,
        blank=True,
    )

    end_date = models.DateField(
        null=True,
        blank=True,
    )

    graduation_year = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
    )

    gpa = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
    )

    certificate_number = models.CharField(
        max_length=100,
        blank=True,
        default="",
    )

    is_highest_education = models.BooleanField(
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
        db_table = "hr_employee_education"
        ordering = [
            "-is_highest_education",
            "-graduation_year",
            "institution_name",
        ]
        indexes = [
            models.Index(
                fields=["employee"],
                name="idx_emp_edu_employee",
            ),
            models.Index(
                fields=["education"],
                name="idx_emp_edu_level",
            ),
            models.Index(
                fields=["is_highest_education"],
                name="idx_emp_edu_highest",
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

        if (
            self.gpa is not None
            and (
                self.gpa < 0
                or self.gpa > 4
            )
        ):
            errors["gpa"] = (
                "GPA harus berada di antara 0 dan 4."
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return (
            f"{self.employee.employee_number} - "
            f"{self.institution_name}"
        )