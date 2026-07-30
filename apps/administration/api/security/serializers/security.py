from rest_framework import serializers

from apps.administration.models import (
    SecuritySetting,
    SessionSetting,
    LoginHistory,
    UserSession,
)


class SecuritySettingSerializer(serializers.ModelSerializer):
    class Meta:
        model = SecuritySetting
        fields = "__all__"


class SessionSettingSerializer(serializers.ModelSerializer):
    class Meta:
        model = SessionSetting
        fields = "__all__"


class LoginHistorySerializer(serializers.ModelSerializer):
    class Meta:
        model = LoginHistory
        fields = "__all__"


class UserSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model = UserSession
        fields = "__all__"