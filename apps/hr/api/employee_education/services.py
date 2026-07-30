from __future__ import annotations

from typing import Any

from django.db import transaction

from apps.hr.models import EmployeeEducation


class EmployeeEducationService:
    FIELDS = {
        "employee",
        "education",
        "degree",
        "study_field",
        "institution_name",
        "city",
        "country",
        "start_date",
        "end_date",
        "graduation_year",
        "gpa",
        "certificate_number",
        "is_highest_education",
        "is_active",
        "notes",
    }

    @classmethod
    def normalize_highest(
        cls,
        *,
        instance: EmployeeEducation,
    ) -> None:
        if not instance.is_highest_education:
            return

        (
            EmployeeEducation.objects
            .filter(
                employee=instance.employee,
                is_highest_education=True,
                is_deleted=False,
            )
            .exclude(pk=instance.pk)
            .update(is_highest_education=False)
        )

    @classmethod
    @transaction.atomic
    def create(
        cls,
        *,
        data: dict[str, Any],
        user=None,
    ) -> EmployeeEducation:
        payload = {
            key: value
            for key, value in data.items()
            if key in cls.FIELDS
        }

        education = EmployeeEducation(
            **payload,
        )

        if user is not None:
            education.created_by = user
            education.updated_by = user

        education.full_clean()
        education.save()

        cls.normalize_highest(
            instance=education,
        )

        return education

    @classmethod
    @transaction.atomic
    def update(
        cls,
        *,
        instance: EmployeeEducation,
        data: dict[str, Any],
        user=None,
    ) -> EmployeeEducation:
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

        cls.normalize_highest(
            instance=instance,
        )

        return instance