from django.db import models

from apps.core.models import BaseModel


class SalaryGrade(BaseModel):
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
    minimum_salary = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
    )
    maximum_salary = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
    )
    is_active = models.BooleanField(
        default=True,
    )

    class Meta:
        db_table = "payroll_salary_grade"
        ordering = ["code"]
        verbose_name = "Salary Grade"
        verbose_name_plural = "Salary Grades"

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"