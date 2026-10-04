from rest_framework import serializers

from apps.administration.models import (
    TenantSetting,
    SystemSetting,
    PrintSetting,
)


class TenantSettingSerializer(serializers.ModelSerializer):
    # Tanpa ini kolom Company menampilkan **pk mentah** — layar Print
    # Settings sempat menulis "20" di tempat nama perusahaan. Generator
    # memetakan field lookup ke `<field>_name`; serializer yang cuma
    # `fields = "__all__"` tidak pernah mengirimnya.
    company_name = serializers.CharField(
        source="company.name",
        read_only=True,
        default=None,
    )

    currency_name = serializers.CharField(
        source="currency.name",
        read_only=True,
        default=None,
    )

    class Meta:
        model = TenantSetting
        fields = "__all__"

        read_only_fields = ["company_name", "currency_name"]


class SystemSettingSerializer(serializers.ModelSerializer):
    class Meta:
        model = SystemSetting
        fields = "__all__"


class PrintSettingSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(
        source="company.name",
        read_only=True,
        default=None,
    )

    class Meta:
        model = PrintSetting
        fields = "__all__"

        read_only_fields = ["company_name"]