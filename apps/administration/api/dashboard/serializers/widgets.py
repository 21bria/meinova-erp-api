from rest_framework import serializers

from apps.administration.models import DashboardWidget


class DashboardWidgetSerializer(serializers.ModelSerializer):
    class Meta:
        model = DashboardWidget
        fields = [
            "id",
            "code",
            "title",
            "description",
            "widget_type",
            "module",
            "is_active",
        ]