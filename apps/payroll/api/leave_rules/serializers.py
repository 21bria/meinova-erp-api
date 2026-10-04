from rest_framework import serializers

from apps.payroll.models import PayrollLeaveRule


class PayrollLeaveRuleSerializer(serializers.ModelSerializer):
    leave_type_code = serializers.CharField(
        source="leave_type.code", read_only=True, default=None,
    )
    leave_type_name = serializers.CharField(
        source="leave_type.name", read_only=True, default=None,
    )

    class Meta:
        model = PayrollLeaveRule
        fields = "__all__"
        read_only_fields = [
            "id", "created_at", "updated_at", "created_by",
            "updated_by", "deleted_at", "deleted_by", "is_deleted",
        ]
