from __future__ import annotations

from typing import Any

from django.db import transaction

from apps.hr.models import EmployeeTraining


class EmployeeTrainingService:
    FIELDS = {
        "employee",
        "training_category",
        "training_name",
        "provider",
        "start_date",
        "end_date",
        "duration_hours",
        "score",
        "certificate_number",
        "expiry_date",
        "attachment",
        "is_mandatory",
        "is_completed",
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
    ) -> EmployeeTraining:
        payload = cls.build_payload(data)

        training = EmployeeTraining(
            **payload,
        )

        if user is not None:
            training.created_by = user
            training.updated_by = user

        training.full_clean()
        training.save()

        return training

    @classmethod
    @transaction.atomic
    def update(
        cls,
        *,
        instance: EmployeeTraining,
        data: dict[str, Any],
        user=None,
    ) -> EmployeeTraining:
        payload = cls.build_payload(data)

        for key, value in payload.items():
            setattr(instance, key, value)

        if user is not None:
            instance.updated_by = user

        instance.full_clean()
        instance.save()

        return instance