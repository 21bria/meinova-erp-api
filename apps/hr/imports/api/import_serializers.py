from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from rest_framework import serializers

from apps.hr.models import (
    AttendanceImportProfile,
)


class AttendanceImportBaseSerializer(
    serializers.Serializer,
):
    profile = serializers.PrimaryKeyRelatedField(
        queryset=(
            AttendanceImportProfile.objects
            .filter(
                is_active=True,
                is_deleted=False,
            )
        ),
    )

    file = serializers.FileField(
        required=True,
    )

    options = serializers.JSONField(
        required=False,
        default=dict,
    )

    def validate_options(
        self,
        value: Any,
    ) -> dict[str, Any]:
        if value in (None, ""):
            return {}

        if isinstance(value, dict):
            return value

        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as exc:
                raise serializers.ValidationError(
                    "Options must contain valid JSON.",
                ) from exc

            if not isinstance(parsed, dict):
                raise serializers.ValidationError(
                    "Options must be a JSON object.",
                )

            return parsed

        raise serializers.ValidationError(
            "Options must be an object.",
        )

    def validate_file(
        self,
        uploaded_file,
    ):
        extension = (
            Path(
                str(uploaded_file.name or "")
            )
            .suffix
            .lower()
        )

        if extension != ".csv":
            raise serializers.ValidationError(
                "Only CSV files are supported.",
            )

        return uploaded_file


class AttendanceImportPreviewSerializer(
    AttendanceImportBaseSerializer,
):
    pass


class AttendanceImportConfirmSerializer(
    AttendanceImportBaseSerializer,
):
    skip_invalid = serializers.BooleanField(
        required=False,
        default=True,
    )