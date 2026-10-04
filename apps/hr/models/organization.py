from django.core.exceptions import ValidationError
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
    Location,
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

    location = models.ForeignKey(
        Location,
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

    # anak -> induk yang harus konsisten dengannya
    HIERARCHY_PARENTS = {
        "branch": ("company",),
        "location": ("company", "branch"),
        "division": ("company", "branch", "location"),
        "department": ("company", "branch", "location", "division"),
        "section": ("company", "branch", "location", "division", "department"),
        "position": ("company", "branch", "location", "division", "department"),
        "cost_center": ("company", "branch", "location", "division", "department"),
    }

    def clean(self):
        """
        Menjaga penempatan tetap masuk akal: location yang dipilih harus
        benar-benar milik branch yang dipilih, dan seterusnya ke atas.

        Cascade di form sudah membatasi pilihan user, tapi pemanggil API
        langsung dan proses import tidak lewat form — jadi aturannya
        ditegakkan di sini juga.
        """
        super().clean()

        errors = {}

        for child_field, parent_fields in self.HIERARCHY_PARENTS.items():
            child = getattr(self, child_field, None)

            if child is None:
                continue

            for parent_field in parent_fields:
                selected_parent = getattr(self, parent_field, None)

                if selected_parent is None:
                    continue

                # Induk pada master boleh kosong (hierarkinya opsional);
                # yang dilarang hanya bila terisi tapi berbeda.
                child_parent = getattr(child, parent_field, None)

                if child_parent is None:
                    continue

                if child_parent.pk != selected_parent.pk:
                    errors[child_field] = (
                        f"{child} tidak berada di bawah "
                        f"{selected_parent}."
                    )

                    break

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"Organization - {self.employee}"