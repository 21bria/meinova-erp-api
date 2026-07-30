from rest_framework import serializers

from apps.payroll.models import DeductionTemplate


class DeductionTemplateSerializer(serializers.ModelSerializer):
    class Meta:
        model = DeductionTemplate
        fields = "__all__"