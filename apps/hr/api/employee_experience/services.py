from __future__ import annotations

from typing import Any

from django.db import transaction

from apps.hr.models import EmployeeExperience


class EmployeeExperienceService:
    FIELDS = {
        "employee",
        "company_name",
        "position_name",
        "employment_type",
        "industry",
        "location",
        "start_date",
        "end_date",
        "is_current",
        "last_salary",
        "job_description",
        "reason_for_leaving",
        "reference_name",
        "reference_phone",
        "is_verified",
        "is_active",
        "notes",
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
    ) -> EmployeeExperience:
        payload = cls.build_payload(data)

        experience = EmployeeExperience(
            **payload,
        )

        if user is not None:
            experience.created_by = user
            experience.updated_by = user

        experience.full_clean()
        experience.save()

        return experience

    @classmethod
    @transaction.atomic
    def update(
        cls,
        *,
        instance: EmployeeExperience,
        data: dict[str, Any],
        user=None,
    ) -> EmployeeExperience:
        payload = cls.build_payload(data)

        for key, value in payload.items():
            setattr(instance, key, value)

        if user is not None:
            instance.updated_by = user

        instance.full_clean()
        instance.save()

        return instance