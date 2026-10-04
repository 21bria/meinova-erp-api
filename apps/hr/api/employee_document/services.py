# apps/hr/api/employee_document/services.py

from __future__ import annotations

from typing import Any

from django.db import transaction

from apps.hr.models import EmployeeDocument
from apps.uploads.services import (
    AttachmentLifecycleService,
)


class EmployeeDocumentService(
    AttachmentLifecycleService,
):
    attachment_fields = (
        "uploaded_file",
    )

    FIELDS = {
        "employee",
        "document_type",
        "document_name",
        "document_number",
        "issue_date",
        "expiry_date",
        "issuing_authority",
        "uploaded_file",
        "is_required",
        "is_verified",
        "verification_notes",
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
    ) -> EmployeeDocument:
        payload = cls.build_payload(data)

        document = EmployeeDocument(
            **payload,
        )

        if user is not None:
            document.created_by = user
            document.updated_by = user

        document.full_clean()
        document.save()

        return document

    @classmethod
    @transaction.atomic
    def update(
        cls,
        *,
        instance: EmployeeDocument,
        data: dict[str, Any],
        user=None,
    ) -> EmployeeDocument:
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