from django.db import models

from apps.core.models.base import BaseModel
from apps.administration.models import FamilyRelationship

from .employee import Employee


class EmployeeFamily(BaseModel):
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="family_members",
    )

    relationship = models.ForeignKey(
        FamilyRelationship,
        on_delete=models.PROTECT,
        related_name="employee_families",
    )

    full_name = models.CharField(
        max_length=200,
    )

    birth_place = models.CharField(
        max_length=150,
        blank=True,
        default="",
    )

    birth_date = models.DateField(
        null=True,
        blank=True,
    )

    gender = models.ForeignKey(
        "administration.Gender",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employee_family_members",
    )

    occupation = models.CharField(
        max_length=150,
        blank=True,
        default="",
    )

    phone = models.CharField(
        max_length=50,
        blank=True,
        default="",
    )

    is_dependent = models.BooleanField(
        default=False,
    )

    is_emergency_contact = models.BooleanField(
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
        db_table = "hr_employee_family"
        ordering = [
            "relationship__sort_order",
            "full_name",
        ]
        indexes = [
            models.Index(
                fields=["employee"],
                name="idx_emp_family_employee",
            ),
            models.Index(
                fields=["relationship"],
                name="idx_emp_family_relation",
            ),
            models.Index(
                fields=["is_dependent"],
                name="idx_emp_family_dependent",
            ),
        ]

    def __str__(self):
        return (
            f"{self.employee.employee_number} - "
            f"{self.full_name}"
        )