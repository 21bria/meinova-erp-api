from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.utils import timezone

from apps.hr.models import (
    Employee,
    PayrollAssignment,
)


class PayrollService:
    FIELDS = {
        "payroll_group",
        "salary_grade",
        "salary_level",
        "currency",
        "payment_method",
        "tax_status",
        "tax_number_payroll",
        "bpjs_kesehatan_number",
        "bpjs_ketenagakerjaan_number",
        "overtime_eligible",
        "overtime_group",
        "effective_from",
        "effective_to",
        "basic_salary",
        "allowance_template",
        "deduction_template",
        "payroll_notes",
    }

    FIELD_MAP = {
        "tax_number_payroll": "tax_number",
        "payroll_notes": "notes",
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
    ) -> PayrollAssignment | None:
        if not data:
            return None

        payload = dict(data)

        payload["effective_from"] = (
            payload.get("effective_from")
            or timezone.localdate()
        )

        payload["effective_to"] = None

        assignment = PayrollAssignment(
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
    def replace_current(
        cls,
        *,
        employee: Employee,
        data: dict[str, Any],
        user=None,
    ) -> PayrollAssignment | None:
        if not data:
            return None

        payload = dict(data)

        effective_from = (
            payload.get("effective_from")
            or timezone.localdate()
        )

        current = (
            PayrollAssignment.objects
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
    
    @classmethod
    def update_current(
        cls,
        *,
        employee: Employee,
        data: dict[str, Any],
        user=None,
    ) -> PayrollAssignment | None:
        if not data:
            return None

        assignment = (
            PayrollAssignment.objects
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

        for key, value in data.items():
            setattr(assignment, key, value)

        if user is not None:
            assignment.updated_by = user

        assignment.full_clean()
        assignment.save()

        return assignment