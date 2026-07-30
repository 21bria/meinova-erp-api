from rest_framework import serializers

from apps.administration.models import (
    TenantSetting,
    SystemSetting,
    PrintSetting,
)


class TenantSettingSerializer(serializers.ModelSerializer):
    class Meta:
        model = TenantSetting
        fields = "__all__"


class SystemSettingSerializer(serializers.ModelSerializer):
    class Meta:
        model = SystemSetting
        fields = "__all__"


class PrintSettingSerializer(serializers.ModelSerializer):
    class Meta:
        model = PrintSetting
        fields = "__all__"