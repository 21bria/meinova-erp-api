# apps/hr/api/employee_document/services.py

from __future__ import annotations

from typing import Any

from django.db import transaction

from apps.hr.models import EmployeeDocument


class EmployeeDocumentService:
    FIELDS = {
        "employee",
        "document_type",
        "document_name",
        "document_number",
        "issue_date",
        "expiry_date",
        "issuing_authority",
        "file",
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
            setattr(instance, key, value)

        if user is not None:
            instance.updated_by = user

        instance.full_clean()
        instance.save()

        return instance