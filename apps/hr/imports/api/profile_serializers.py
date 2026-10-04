from __future__ import annotations

from rest_framework import serializers

from apps.hr.models import (
    AttendanceImportProfile,
)


class AttendanceImportProfileLookupSerializer(
    serializers.ModelSerializer,
):
    value = serializers.IntegerField(
        source="id",
        read_only=True,
    )

    label = serializers.CharField(
        source="name",
        read_only=True,
    )

    company_label = serializers.CharField(
        source="company.name",
        read_only=True,
        default=None,
    )

    branch_label = serializers.CharField(
        source="branch.name",
        read_only=True,
        default=None,
    )

    location_label = serializers.CharField(
        source="location.name",
        read_only=True,
        default=None,
    )

    class Meta:
        model = AttendanceImportProfile
        fields = [
            "id",
            "value",
            "name",
            "label",
            "code",
            "company",
            "company_label",
            "branch",
            "branch_label",
            "location",
            "location_label",
            "delimiter",
            "encoding",
            "datetime_formats",
        ]