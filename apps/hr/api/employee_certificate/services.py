from __future__ import annotations

from typing import Any

from django.db import transaction

from apps.hr.models import EmployeeCertificate
from apps.uploads.services import (
    AttachmentLifecycleService,
)


class EmployeeCertificateService(
    AttachmentLifecycleService,
):
    attachment_fields = (
        "uploaded_file",
    )

    FIELDS = {
        "employee",
        "certificate_type",
        "certificate_name",
        "certificate_number",
        "issuing_organization",
        "issue_date",
        "expiry_date",
        "credential_id",
        "credential_url",
        "uploaded_file",
        "is_lifetime",
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
        payload = {
            key: value
            for key, value in data.items()
            if key in cls.FIELDS
        }

        if payload.get("is_lifetime"):
            payload["expiry_date"] = None

        return payload

    @classmethod
    @transaction.atomic
    def create(
        cls,
        *,
        data: dict[str, Any],
        user=None,
    ) -> EmployeeCertificate:
        payload = cls.build_payload(data)

        certificate = EmployeeCertificate(
            **payload,
        )

        if user is not None:
            certificate.created_by = user
            certificate.updated_by = user

        certificate.full_clean()
        certificate.save()

        return certificate

    @classmethod
    @transaction.atomic
    def update(
        cls,
        *,
        instance: EmployeeCertificate,
        data: dict[str, Any],
        user=None,
    ) -> EmployeeCertificate:
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