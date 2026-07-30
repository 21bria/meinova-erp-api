from __future__ import annotations

from typing import Any

from apps.hr.models import EmployeeFamily


class EmployeeFamilyService:
    FIELDS = {
        "employee",
        "relationship",
        "full_name",
        "birth_place",
        "birth_date",
        "gender",
        "occupation",
        "phone",
        "is_dependent",
        "is_emergency_contact",
        "is_active",
        "notes",
    }

    @classmethod
    def create(
        cls,
        *,
        data: dict[str, Any],
        user=None,
    ) -> EmployeeFamily:
        payload = {
            key: value
            for key, value in data.items()
            if key in cls.FIELDS
        }

        family = EmployeeFamily(
            **payload,
        )

        if user is not None:
            family.created_by = user
            family.updated_by = user

        family.full_clean()
        family.save()

        return family

    @classmethod
    def update(
        cls,
        *,
        instance: EmployeeFamily,
        data: dict[str, Any],
        user=None,
    ) -> EmployeeFamily:
        payload = {
            key: value
            for key, value in data.items()
            if key in cls.FIELDS
        }

        for key, value in payload.items():
            setattr(instance, key, value)

        if user is not None:
            instance.updated_by = user

        instance.full_clean()
        instance.save()

        return instance