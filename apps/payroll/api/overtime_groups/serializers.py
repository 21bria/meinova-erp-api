from rest_framework import serializers

from apps.payroll.models import OvertimeGroup


class OvertimeGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = OvertimeGroup
        fields = "__all__"