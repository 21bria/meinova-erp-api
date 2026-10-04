from rest_framework import serializers

from apps.payroll.models import BpjsBaseDefinition


class BpjsBaseDefinitionSerializer(serializers.ModelSerializer):
    # Dibaca sebagai satu kalimat, bukan disuruh disusun sendiri dari
    # tabel anak: "Gaji Pokok + TUNJ-TETAP" menjawab pertanyaannya.
    component_summary = serializers.SerializerMethodField()
    is_referenced = serializers.SerializerMethodField()

    def get_component_summary(self, instance) -> str:
        parts = []

        if instance.include_basic:
            parts.append("Gaji Pokok")

        parts.extend(
            row.allowance_code
            for row in instance.components.filter(is_deleted=False)
        )

        return " + ".join(parts) if parts else "-"

    def get_is_referenced(self, instance) -> bool:
        return instance.is_referenced

    class Meta:
        model = BpjsBaseDefinition
        fields = "__all__"
        read_only_fields = [
            "id", "created_at", "updated_at", "created_by",
            "updated_by", "deleted_at", "deleted_by", "is_deleted",
        ]
