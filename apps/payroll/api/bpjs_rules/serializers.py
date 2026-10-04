from rest_framework import serializers

from apps.payroll.models import BpjsRule


class BpjsRuleSerializer(serializers.ModelSerializer):
    program_name = serializers.CharField(
        source="program.name", read_only=True, default=None,
    )
    company_name = serializers.CharField(
        source="company.name", read_only=True, default=None,
    )
    risk_class_name = serializers.CharField(
        source="risk_class.name", read_only=True, default=None,
    )

    # Cakupan dibaca sebagai kata, bukan sebagai kolom company yang
    # kosong. Kosong pada aturan bawaan berarti "semua perusahaan", dan
    # sel kosong tidak pernah menyampaikan itu.
    scope_label = serializers.CharField(read_only=True)

    base_definition_label = serializers.SerializerMethodField()

    def get_base_definition_label(self, instance) -> str:
        definition = instance.base_definition

        return f"{definition.code} v{definition.version}"

    class Meta:
        model = BpjsRule
        fields = "__all__"
        read_only_fields = [
            "id", "created_at", "updated_at", "created_by",
            "updated_by", "deleted_at", "deleted_by", "is_deleted",
        ]
