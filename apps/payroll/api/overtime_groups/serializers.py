from rest_framework import serializers

from apps.payroll.models import OvertimeGroup


class OvertimeGroupSerializer(serializers.ModelSerializer):
    # Kolom tabel membaca label, bukan `daily`/`monthly`. Kosong bukan
    # nilai yang hilang melainkan keadaan — perusahaan belum memilih —
    # dan sel kosong terbaca seperti data gagal termuat.
    tier_basis_label = serializers.SerializerMethodField()

    # Berapa tingkat yang aktif. Satu angka yang menjawab "kelompok ini
    # pakai tingkat atau pengali tunggal" tanpa membuka layar lain.
    tier_count = serializers.SerializerMethodField()

    def get_tier_basis_label(self, instance) -> str:
        if not instance.tier_basis:
            return "Belum ditentukan"

        return instance.get_tier_basis_display()

    def get_tier_count(self, instance) -> int:
        return instance.active_tiers.count()

    class Meta:
        model = OvertimeGroup
        fields = "__all__"
