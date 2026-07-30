from rest_framework import serializers

from apps.accounts.models import UserSession


class UserSessionSerializer(serializers.ModelSerializer):
    username = serializers.CharField(source="user.username", read_only=True)
    email = serializers.CharField(source="user.email", read_only=True)
    full_name = serializers.SerializerMethodField()

    class Meta:
        model = UserSession
        fields = [
            "id",
            "user",
            "username",
            "email",
            "full_name",
            "ip_address",
            "browser",
            "os",
            "device",
            "login_at",
            "last_activity_at",
            "expires_at",
            "is_active_session",
        ]

    def get_full_name(self, obj):
        return obj.user.get_full_name() or obj.user.username