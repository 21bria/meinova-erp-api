from rest_framework import serializers

from apps.payroll.models import BpjsBaseComponent


class BpjsBaseComponentSerializer(serializers.ModelSerializer):
    definition_label = serializers.SerializerMethodField()

    def get_definition_label(self, instance) -> str:
        definition = instance.definition

        return f"{definition.code} v{definition.version}"

    class Meta:
        model = BpjsBaseComponent
        fields = "__all__"
        read_only_fields = [
            "id", "created_at", "updated_at", "created_by",
            "updated_by", "deleted_at", "deleted_by", "is_deleted",
        ]
