from __future__ import annotations

from typing import Any

from django.db import transaction

from apps.hr.models import EmployeeMedicalEvent


class EmployeeMedicalEventService:
    FIELDS = {
        "employee",
        "medical_type",
        "event_date",
        "provider_name",
        "doctor_name",
        "result",
        "fitness_status",
        "restriction_notes",
        "next_due_date",
        "attachment",
        "is_confidential",
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
    ) -> EmployeeMedicalEvent:
        payload = cls.build_payload(data)

        event = EmployeeMedicalEvent(
            **payload,
        )

        if user is not None:
            event.created_by = user
            event.updated_by = user

        event.full_clean()
        event.save()

        return event

    @classmethod
    @transaction.atomic
    def update(
        cls,
        *,
        instance: EmployeeMedicalEvent,
        data: dict[str, Any],
        user=None,
    ) -> EmployeeMedicalEvent:
        payload = cls.build_payload(data)

        for key, value in payload.items():
            setattr(instance, key, value)

        if user is not None:
            instance.updated_by = user

        instance.full_clean()
        instance.save()

        return instance