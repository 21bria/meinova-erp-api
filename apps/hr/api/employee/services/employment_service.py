from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.utils import timezone

from apps.hr.models import (
    Employee,
    EmploymentAssignment,
)


class EmploymentService:
    FIELDS = {
        "employment_status",
        "employment_type",
        "employee_group",
        "contract_type",
        "probation_type",
        "join_date",
        "confirmation_date",
        "probation_start",
        "probation_end",
        "contract_start",
        "contract_end",
        "termination_date",
        "termination_reason",
        "retirement_date",
        "work_schedule",
        "working_calendar",
        "shift",
        "notice_period_days",
        "employment_notes",
        "employment_effective_date",
    }

    FIELD_MAP = {
        "employment_effective_date": "effective_from",
        "employment_notes": "notes",
    }

    @classmethod
    def extract(
        cls,
        validated_data: dict[str, Any],
    ) -> dict[str, Any]:
        extracted = {
            key: validated_data.pop(key)
            for key in list(validated_data.keys())
            if key in cls.FIELDS
        }

        return {
            cls.FIELD_MAP.get(key, key): value
            for key, value in extracted.items()
        }

    @classmethod
    def create_initial(
        cls,
        *,
        employee: Employee,
        data: dict[str, Any],
        user=None,
    ) -> EmploymentAssignment | None:
        if not data:
            return None

        payload = dict(data)

        effective_from = (
            payload.get("effective_from")
            or payload.get("join_date")
            or timezone.localdate()
        )

        payload["effective_from"] = effective_from
        payload["effective_to"] = None

        assignment = EmploymentAssignment(
            employee=employee,
            is_current=True,
            **payload,
        )

        if user is not None:
            assignment.created_by = user
            assignment.updated_by = user

        assignment.full_clean()
        assignment.save()

        return assignment

    @classmethod
    def update_current(
        cls,
        *,
        employee: Employee,
        data: dict[str, Any],
        user=None,
    ) -> EmploymentAssignment | None:
        if not data:
            return None

        assignment = (
            EmploymentAssignment.objects
            .select_for_update()
            .filter(
                employee=employee,
                is_current=True,
            )
            .first()
        )

        if assignment is None:
            return cls.create_initial(
                employee=employee,
                data=data,
                user=user,
            )

        payload = dict(data)

        for key, value in payload.items():
            setattr(assignment, key, value)

        if user is not None:
            assignment.updated_by = user

        assignment.full_clean()
        assignment.save()

        return assignment

    @classmethod
    def replace_current(
        cls,
        *,
        employee: Employee,
        data: dict[str, Any],
        user=None,
    ) -> EmploymentAssignment | None:
        if not data:
            return None

        payload = dict(data)

        effective_from = (
            payload.get("effective_from")
            or payload.get("join_date")
            or timezone.localdate()
        )

        current = (
            EmploymentAssignment.objects
            .select_for_update()
            .filter(
                employee=employee,
                is_current=True,
            )
            .first()
        )

        if current is not None:
            if (
                current.effective_from
                and effective_from <= current.effective_from
            ):
                effective_from = current.effective_from

            current.effective_to = (
                effective_from - timedelta(days=1)
            )
            current.is_current = False

            if user is not None:
                current.updated_by = user

            current.full_clean()
            current.save()

        payload["effective_from"] = effective_from
        payload["effective_to"] = None

        return cls.create_initial(
            employee=employee,
            data=payload,
            user=user,
        )