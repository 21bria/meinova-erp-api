from rest_framework import serializers

from apps.hr.api.constants import AUDIT_READ_ONLY_FIELDS
from apps.hr.models import EmployeeOvertime


class EmployeeOvertimeSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(
        source="employee.full_name",
        read_only=True,
    )

    employee_number = serializers.CharField(
        source="employee.employee_number",
        read_only=True,
    )

    company_name = serializers.CharField(
        source="company.name",
        read_only=True,
        default=None,
    )

    branch_name = serializers.CharField(
        source="branch.name",
        read_only=True,
        default=None,
    )

    location_name = serializers.CharField(
        source="location.name",
        read_only=True,
        default=None,
    )

    overtime_type_name = serializers.CharField(
        source="overtime_type.name",
        read_only=True,
        default=None,
    )

    status_label = serializers.CharField(
        source="get_status_display",
        read_only=True,
    )

    duration_hours = serializers.FloatField(read_only=True)

    class Meta:
        model = EmployeeOvertime
        fields = "__all__"

        read_only_fields = AUDIT_READ_ONLY_FIELDS + [
            "employee_name",
            "employee_number",
            "company_name",
            "branch_name",
            "location_name",
            "overtime_type_name",
            "status_label",
            "duration_hours",
        ]

    def validate(self, attrs):
        instance = self.instance

        def resolved(field_name, default=None):
            if field_name in attrs:
                return attrs[field_name]

            return getattr(instance, field_name, default)

        duration_minutes = resolved("duration_minutes")

        errors = {}

        if duration_minutes is not None and duration_minutes <= 0:
            errors["duration_minutes"] = (
                "Duration must be greater than zero."
            )

        if duration_minutes is not None and duration_minutes > 16 * 60:
            errors["duration_minutes"] = (
                "Duration exceeds 16 hours — check the start and "
                "end time."
            )

        if errors:
            raise serializers.ValidationError(errors)

        return attrs
