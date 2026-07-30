from django.contrib.auth.models import Permission
from rest_framework import serializers


from django.contrib.auth.models import Permission
from rest_framework import serializers


class PermissionSerializer(serializers.ModelSerializer):
    code = serializers.CharField(source="codename", read_only=True)
    module = serializers.CharField(source="content_type.app_label",read_only=True)
    model = serializers.CharField(source="content_type.model",read_only=True)

    class Meta:
        model = Permission
        fields = [
            "id",
            "code",
            "name",
            "module",
            "model",
        ]

        read_only_fields = fields