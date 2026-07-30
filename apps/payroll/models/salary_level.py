from django.db import models

from apps.core.models import BaseModel

from .salary_grade import SalaryGrade


class SalaryLevel(BaseModel):
    salary_grade = models.ForeignKey(
        SalaryGrade,
        on_delete=models.PROTECT,
        related_name="levels",
    )
    code = models.CharField(
        max_length=30,
    )
    name = models.CharField(
        max_length=150,
    )
    sequence = models.PositiveIntegerField(
        default=1,
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
        db_table = "payroll_salary_level"
        ordering = [
            "salary_grade__code",
            "sequence",
        ]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "salary_grade",
                    "code",
                ],
                name="uniq_salary_level_grade_code",
            ),
        ]
        verbose_name = "Salary Level"
        verbose_name_plural = "Salary Levels"

    def __str__(self) -> str:
        return (
            f"{self.salary_grade.code} - "
            f"{self.code} - {self.name}"
        )