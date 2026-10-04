from rest_framework import serializers

from apps.payroll.models import BpjsEnrollment


class BpjsEnrollmentSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(
        source="employee.full_name", read_only=True, default=None,
    )
    employee_number = serializers.CharField(
        source="employee.employee_number", read_only=True, default=None,
    )
    program_name = serializers.CharField(
        source="program.name", read_only=True, default=None,
    )
    program_code = serializers.CharField(
        source="program.code", read_only=True, default=None,
    )
    risk_class_name = serializers.CharField(
        source="risk_class.name", read_only=True, default=None,
    )

    class Meta:
        model = BpjsEnrollment
        fields = "__all__"
        read_only_fields = [
            "id", "created_at", "updated_at", "created_by",
            "updated_by", "deleted_at", "deleted_by", "is_deleted",
        ]
