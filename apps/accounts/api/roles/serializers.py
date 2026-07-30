from rest_framework import serializers

from apps.accounts.models import Role


class RoleSerializer(serializers.ModelSerializer):
    class Meta:
        model = Role
        fields = [
            "id",
            "code",
            "name",
            "description",
            "permissions",
            "is_active",
        ]