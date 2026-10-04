from __future__ import annotations

from datetime import timedelta
from typing import Any

from django.db import transaction
from django.utils import timezone

from apps.hr.models import PayrollAssignment


class PayrollAssignmentService:
    FIELDS = {
        "employee",
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
        "basic_salary",
        "daily_rate",
        "payroll_policy",
        "allowance_template",
        "deduction_template",
        "effective_from",
        "payroll_notes",
    }

    @classmethod
    def build_payload(
        cls,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            key: value
            for key, value in data.items()
            if key in cls.FIELDS
        }

    @classmethod
    @transaction.atomic
    def create(
        cls,
        *,
        data: dict[str, Any],
        user=None,
    ) -> PayrollAssignment:
        payload = cls.build_payload(data)

        employee = payload["employee"]

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
                is_deleted=False,
            )
            .first()
        )

        if current is not None:
            if effective_from <= current.effective_from:
                raise ValueError(
                    "Effective From harus lebih besar "
                    "dari payroll assignment current."
                )

            current.is_current = False
            current.effective_to = (
                effective_from - timedelta(days=1)
            )

            if user is not None:
                current.updated_by = user

            current.full_clean()
            current.save(
                update_fields=[
                    "is_current",
                    "effective_to",
                    "updated_by",
                    "updated_at",
                ],
            )

        payload["effective_from"] = effective_from
        payload["effective_to"] = None
        payload["is_current"] = True

        assignment = PayrollAssignment(**payload)

        if user is not None:
            assignment.created_by = user
            assignment.updated_by = user

        assignment.full_clean()
        assignment.save()

        return assignment

    @classmethod
    @transaction.atomic
    def update(
        cls,
        *,
        instance: PayrollAssignment,
        data: dict[str, Any],
        user=None,
    ) -> PayrollAssignment:
        payload = cls.build_payload(data)

        # Edit hanya koreksi record, bukan membuat periode baru.
        payload.pop("employee", None)
        payload.pop("effective_from", None)

        for key, value in payload.items():
            setattr(instance, key, value)

        if user is not None:
            instance.updated_by = user

        instance.full_clean()
        instance.save()

        return instance