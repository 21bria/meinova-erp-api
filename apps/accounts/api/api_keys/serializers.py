from rest_framework import serializers

from apps.accounts.models import APIKey


class APIKeySerializer(serializers.ModelSerializer):
    user_name = serializers.CharField(
        source="user.username",
        read_only=True,
    )

    class Meta:
        model = APIKey
        fields = [
            "id",
            "user",
            "user_name",
            "name",
            "prefix",
            "hashed_key",
            "allowed_ips",
            "scopes",
            "last_used_at",
            "expires_at",
            "is_active",
        ]
        read_only_fields = [
            "prefix",
            "hashed_key",
            "last_used_at",
        ]