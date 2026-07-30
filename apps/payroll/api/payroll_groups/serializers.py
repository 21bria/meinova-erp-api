# serializers.py
from rest_framework import serializers

from apps.payroll.models import PayrollGroup


class PayrollGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = PayrollGroup
        fields = "__all__"