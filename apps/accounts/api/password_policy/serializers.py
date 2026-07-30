from rest_framework import serializers

from apps.accounts.models import PasswordPolicy


class PasswordPolicySerializer(serializers.ModelSerializer):
    class Meta:
        model = PasswordPolicy
        fields = "__all__"