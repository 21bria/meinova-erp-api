from rest_framework import serializers

from apps.administration.models import DashboardWidget, UserDashboardLayout
from .widgets import DashboardWidgetSerializer


class UserDashboardLayoutSerializer(serializers.ModelSerializer):
    widget = DashboardWidgetSerializer(read_only=True)

    widget_id = serializers.PrimaryKeyRelatedField(
        source="widget",
        queryset=DashboardWidget.objects.filter(
            is_active=True,
            is_deleted=False,
        ),
        write_only=True,
    )

    class Meta:
        model = UserDashboardLayout
        fields = [
            "id",
            "widget",
            "widget_id",
            "x",
            "y",
            "width",
            "height",
            "config",
            "is_visible",
        ]