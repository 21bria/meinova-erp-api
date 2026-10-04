from rest_framework import serializers

from apps.payroll.models import BpjsProgram


class BpjsProgramSerializer(serializers.ModelSerializer):
    class Meta:
        model = BpjsProgram
        fields = "__all__"
        read_only_fields = [
            "id", "created_at", "updated_at", "created_by",
            "updated_by", "deleted_at", "deleted_by", "is_deleted",
        ]
