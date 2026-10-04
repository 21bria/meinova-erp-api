from __future__ import annotations

from rest_framework import serializers


class AttendanceSyncRecordSerializer(
    serializers.Serializer,
):
    source_key = serializers.CharField(
        max_length=128,
    )

    external_id = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        default="",
    )

    employee_code = serializers.CharField(
        max_length=100,
    )

    # Nama yang terdaftar di mesin absensi. Opsional
    # agar agent versi lama tetap diterima.
    employee_name = serializers.CharField(
        max_length=255,
        required=False,
        allow_blank=True,
        default="",
    )

    log_time = serializers.DateTimeField()

    log_type = serializers.ChoiceField(
        choices=[
            "in",
            "out",
            "unknown",
        ],
        required=False,
        default="unknown",
    )

    device_code = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
        default="",
    )

    raw_payload = serializers.JSONField(
        required=False,
        default=dict,
    )

    def validate_source_key(
        self,
        value: str,
    ) -> str:
        value = value.strip()

        if not value:
            raise serializers.ValidationError(
                "Source key is required.",
            )

        return value

    def validate_employee_code(
        self,
        value: str,
    ) -> str:
        value = value.strip()

        if not value:
            raise serializers.ValidationError(
                "Employee code is required.",
            )

        return value

    def validate_log_type(
        self,
        value: str,
    ) -> str:
        return str(
            value or "unknown",
        ).strip().lower()


class AttendanceSyncRequestSerializer(
    serializers.Serializer,
):
    agent_code = serializers.CharField(
        max_length=100,
    )

    device_code = serializers.CharField(
        max_length=100,
        required=False,
        allow_blank=True,
        default="",
    )

    records = AttendanceSyncRecordSerializer(
        many=True,
        allow_empty=False,
    )

    def validate_agent_code(
        self,
        value: str,
    ) -> str:
        value = value.strip()

        if not value:
            raise serializers.ValidationError(
                "Agent code is required.",
            )

        return value

    def validate_records(
        self,
        value,
    ):
        if len(value) > 1000:
            raise serializers.ValidationError(
                "A maximum of 1000 records "
                "is allowed per request.",
            )

        source_keys: set[str] = set()
        duplicates: set[str] = set()

        for item in value:
            source_key = item[
                "source_key"
            ]

            if source_key in source_keys:
                duplicates.add(
                    source_key,
                )

            source_keys.add(
                source_key,
            )

        if duplicates:
            raise serializers.ValidationError(
                (
                    "Duplicate source keys were "
                    "found in the request: "
                    + ", ".join(
                        sorted(
                            duplicates,
                        )[:10]
                    )
                ),
            )

        return value