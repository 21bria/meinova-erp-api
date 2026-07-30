from django.db import models

from apps.core.models.base import BaseModel
from apps.administration.models import (
    Branch,
    Company,
    CostCenter,
    Department,
    Division,
    Position,
    Section,
    Site,
)
from apps.administration.models.references.hr import (
    JobGrade,
    JobLevel,
)

from .employee import Employee


class OrganizationAssignment(BaseModel):
    employee = models.OneToOneField(
        Employee,
        on_delete=models.CASCADE,
        related_name="organization",
    )

    company = models.ForeignKey(
        Company,
        on_delete=models.PROTECT,
        related_name="employee_organizations",
    )

    branch = models.ForeignKey(
        Branch,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_organizations",
    )

    site = models.ForeignKey(
        Site,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_organizations",
    )

    division = models.ForeignKey(
        Division,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_organizations",
    )

    department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_organizations",
    )

    section = models.ForeignKey(
        Section,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_organizations",
    )

    position = models.ForeignKey(
        Position,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_organizations",
    )

    job_level = models.ForeignKey(
        JobLevel,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_organizations",
    )

    job_grade = models.ForeignKey(
        JobGrade,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_organizations",
    )

    reports_to = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="direct_reports",
    )

    cost_center = models.ForeignKey(
        CostCenter,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_organizations",
    )

    organization_effective_date = models.DateField()

    organization_notes = models.TextField(blank=True)

    class Meta:
        db_table = "hr_employee_organization"

    def __str__(self):
        return f"Organization - {self.employee}"