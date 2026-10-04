from rest_framework import serializers


class RolePermissionSaveSerializer(serializers.Serializer):
    role = serializers.IntegerField()

    permissions = serializers.ListField(
        child=serializers.CharField(),
        allow_empty=True,
    )
