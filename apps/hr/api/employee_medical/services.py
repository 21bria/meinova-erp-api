from __future__ import annotations

from typing import Any

from django.db import transaction

from apps.hr.models import EmployeeMedicalEvent
from apps.uploads.services import (
    AttachmentLifecycleService,
)


class EmployeeMedicalEventService(
    AttachmentLifecycleService,
):
    attachment_fields = (
        "uploaded_file",
    )

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
        "uploaded_file",
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

        instance = EmployeeMedicalEvent(
            **payload,
        )

        if user is not None:
            instance.created_by = user
            instance.updated_by = user

        instance.full_clean()
        instance.save()

        return instance

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
            setattr(
                instance,
                key,
                value,
            )

        update_fields = set(
            payload.keys(),
        )

        if user is not None:
            instance.updated_by = user
            update_fields.add(
                "updated_by",
            )

        instance.full_clean()

        if update_fields:
            update_fields.add(
                "updated_at",
            )

            instance.save(
                update_fields=list(
                    update_fields,
                ),
            )

        return instance