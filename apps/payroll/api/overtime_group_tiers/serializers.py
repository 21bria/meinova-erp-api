from decimal import Decimal

from rest_framework import serializers

from apps.payroll.models import OvertimeGroupTier


class OvertimeGroupTierSerializer(serializers.ModelSerializer):
    group_code = serializers.CharField(
        source="group.code", read_only=True, default=None,
    )
    group_name = serializers.CharField(
        source="group.name", read_only=True, default=None,
    )

    # Rentangnya dibaca sebagai satu kalimat, bukan dua angka di dua
    # kolom. "Jam 1-2" menjawab pertanyaannya; "1,00" dan "2,00" di
    # kolom terpisah menyuruh orang menyusunnya sendiri.
    hour_range_label = serializers.SerializerMethodField()
    multiplier_label = serializers.SerializerMethodField()

    @staticmethod
    def _plain(value) -> str:
        """
        Angka tanpa nol berekor.

        `:g` saja tidak cukup: `Decimal("1.00")` menyimpan presisinya
        sendiri, jadi ia tetap tercetak "1.00" dan rentangnya terbaca
        "Jam ke-1.00 dan seterusnya". `normalize()` yang membuangnya,
        dan `:f` sesudahnya yang menahan 100 berubah jadi "1E+2".
        """
        return f"{Decimal(value or 0).normalize():f}"

    def get_hour_range_label(self, instance) -> str:
        start = self._plain(instance.hour_from)

        if instance.hour_to is None:
            return f"Jam ke-{start} dan seterusnya"

        return f"Jam ke-{start} sampai {self._plain(instance.hour_to)}"

    def get_multiplier_label(self, instance) -> str:
        return f"{self._plain(instance.multiplier)}x upah per jam"

    class Meta:
        model = OvertimeGroupTier
        fields = "__all__"
        read_only_fields = [
            "id", "created_at", "updated_at", "created_by",
            "updated_by", "deleted_at", "deleted_by", "is_deleted",
        ]
