from rest_framework import serializers


class DataPermissionSaveSerializer(serializers.Serializer):
    role = serializers.IntegerField()

    resources = serializers.DictField(
        child=serializers.ListField(
            child=serializers.IntegerField(),
            allow_empty=True,
        )
    )