from rest_framework import serializers

from apps.finance.models import AccountingDimension


class AccountingDimensionSerializer(serializers.ModelSerializer):
    data_type_label = serializers.CharField(
        source="get_data_type_display", read_only=True,
    )

    # Dimensi inti tidak bisa dihapus maupun diganti kodenya: kodenya
    # adalah nama kolom pada baris jurnal, dan mengubahnya memutus
    # pemetaan tanpa satu pun pesan.
    is_locked = serializers.BooleanField(source="is_core", read_only=True)

    can_delete = serializers.SerializerMethodField()

    class Meta:
        model = AccountingDimension
        fields = "__all__"

        read_only_fields = [
            "is_core",
            "is_locked",
            "data_type_label",
            "can_delete",
        ]

    def get_can_delete(self, obj) -> bool:
        return not obj.is_core
