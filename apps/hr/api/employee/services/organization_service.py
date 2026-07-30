from __future__ import annotations

from typing import Any

from apps.hr.models import (
    Employee,
    OrganizationAssignment,
)


class OrganizationService:
    FIELDS = {
        "company",
        "branch",
        "site",
        "division",
        "department",
        "section",
        "position",
        "job_level",
        "job_grade",
        "reports_to",
        "cost_center",
        "project",
        "organization_effective_date",
        "organization_notes",
    }

    @classmethod
    def extract(
        cls,
        validated_data: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            key: validated_data.pop(key)
            for key in list(validated_data.keys())
            if key in cls.FIELDS
        }

    @classmethod
    def save(
        cls,
        *,
        employee: Employee,
        data: dict[str, Any],
        user=None,
    ) -> OrganizationAssignment | None:
        if not data:
            return None

        try:
            assignment = employee.organization
            created = False
        except OrganizationAssignment.DoesNotExist:
            assignment = OrganizationAssignment(
                employee=employee,
            )
            created = True

        for key, value in data.items():
            setattr(assignment, key, value)

        if user is not None:
            if created:
                assignment.created_by = user

            assignment.updated_by = user

        assignment.full_clean()
        assignment.save()

        return assignment