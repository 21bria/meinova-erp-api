from rest_framework import serializers

from apps.payroll.models import AllowanceTemplate


class AllowanceTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = AllowanceTemplate
        fields = "__all__"