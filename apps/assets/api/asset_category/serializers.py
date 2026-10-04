from rest_framework import serializers

from apps.assets.models import AssetCategory


class AssetCategorySerializer(serializers.ModelSerializer):
    # Daftar kolom eksplisit, bukan `"__all__"`. Dengan `"__all__"` kolom
    # `is_deleted`/`deleted_*` ikut bisa ditulis lewat PATCH, dan itu
    # jalan pintas menghidupkan kembali kategori terhapus tanpa lewat
    # `restore()` — tanpa jejak audit penghapusannya dibatalkan.
    class Meta:
        model = AssetCategory

        fields = [
            "id",
            "code",
            "name",
            "description",
            "sort_order",
            "is_active",
            "requires_serial_number",
            "allow_employee_custody",
            "allow_organization_custody",
            "created_at",
            "updated_at",
        ]

        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
        ]
