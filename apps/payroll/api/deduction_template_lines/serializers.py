from rest_framework import serializers

from apps.payroll.models import DeductionTemplateLine


class DeductionTemplateLineSerializer(serializers.ModelSerializer):
    template_code = serializers.CharField(
        source="template.code", read_only=True, default=None,
    )
    template_name = serializers.CharField(
        source="template.name", read_only=True, default=None,
    )

    class Meta:
        model = DeductionTemplateLine
        fields = "__all__"
        read_only_fields = [
            "id", "created_at", "updated_at", "created_by",
            "updated_by", "deleted_at", "deleted_by", "is_deleted",
        ]
