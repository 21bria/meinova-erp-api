from rest_framework import serializers

from apps.payroll.models import TaxStatus


class TaxStatusSerializer(serializers.ModelSerializer):
    class Meta:
        model = TaxStatus
        fields = "__all__"