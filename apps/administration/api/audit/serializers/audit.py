from rest_framework import serializers

from apps.administration.models import AuditTrail


class AuditTrailSerializer(serializers.ModelSerializer):
    class Meta:
        model = AuditTrail
        fields = "__all__"