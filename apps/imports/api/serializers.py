from __future__ import annotations

from rest_framework import serializers

from apps.imports.models import (
    ImportJob,
    ImportJobError,
)


class ImportJobErrorSerializer(
    serializers.ModelSerializer,
):
    class Meta:
        model = ImportJobError

        fields = [
            "id",
            "row_number",
            "field_name",
            "code",
            "message",
            "employee_code",
            "raw_data",
            "created_at",
        ]

        read_only_fields = fields


class ImportJobListSerializer(
    serializers.ModelSerializer,
):
    imported_by_name = (
        serializers.SerializerMethodField()
    )

    error_count = serializers.IntegerField(
        read_only=True,
    )

    duration_seconds = (
        serializers.SerializerMethodField()
    )

    class Meta:
        model = ImportJob

        fields = [
            "id",
            "public_id",

            "module",

            "profile_code",
            "profile_name",

            "filename",
            "source_type",
            "status",

            "total_rows",
            "valid_rows",
            "invalid_rows",

            "created_rows",
            "updated_rows",
            "duplicate_rows",
            "skipped_rows",
            "failed_rows",

            "started_at",
            "finished_at",
            "duration_ms",
            "duration_seconds",

            "error_count",

            "imported_by",
            "imported_by_name",

            "created_at",
            "updated_at",
        ]

        read_only_fields = fields

    def get_imported_by_name(
        self,
        obj: ImportJob,
    ) -> str:
        user = obj.imported_by

        if user is None:
            return ""

        full_name = ""

        if hasattr(
            user,
            "get_full_name",
        ):
            full_name = str(
                user.get_full_name()
                or "",
            ).strip()

        return (
            full_name
            or str(
                getattr(
                    user,
                    "email",
                    "",
                )
                or getattr(
                    user,
                    "username",
                    "",
                )
            )
        )

    def get_duration_seconds(
        self,
        obj: ImportJob,
    ) -> float:
        return round(
            (
                obj.duration_ms
                or 0
            )
            / 1000,
            3,
        )


class ImportJobDetailSerializer(
    ImportJobListSerializer,
):
    metadata = serializers.JSONField(
        read_only=True,
    )

    error_message = serializers.CharField(
        read_only=True,
    )

    class Meta(
        ImportJobListSerializer.Meta,
    ):
        fields = [
            *ImportJobListSerializer
            .Meta
            .fields,

            "metadata",
            "error_message",
        ]