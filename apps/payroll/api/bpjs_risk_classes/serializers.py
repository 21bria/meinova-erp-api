from rest_framework import serializers

from apps.payroll.models import BpjsRiskClass


class BpjsRiskClassSerializer(serializers.ModelSerializer):
    class Meta:
        model = BpjsRiskClass
        fields = "__all__"
        read_only_fields = [
            "id", "created_at", "updated_at", "created_by",
            "updated_by", "deleted_at", "deleted_by", "is_deleted",
        ]
