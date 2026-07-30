from rest_framework import serializers


class MenuPermissionSaveSerializer(serializers.Serializer):
    role = serializers.IntegerField()
    menus = serializers.ListField(
        child=serializers.IntegerField(),
        allow_empty=True,
    )