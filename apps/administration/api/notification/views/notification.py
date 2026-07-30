from rest_framework.permissions import IsAuthenticated
from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.setting import BaseSettingAPIView

from apps.administration.api.notification.serializers.notification import (
    NotificationSerializer,
    NotificationSettingSerializer,
)
from apps.administration.api.notification.services.notification_service import (
    NotificationService,
    NotificationSettingService,
)


class NotificationViewSet(BaseMasterViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = NotificationSerializer
    service_class = NotificationService
    framework_module = "administration/notification/notification"
    schema_type = "crud"

    schema = {
        "title": "Notification",
        "description": "Manage user notifications.",
    }

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class NotificationSettingAPIView(BaseSettingAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = NotificationSettingSerializer
    service_class = NotificationSettingService
    framework_module = "administration/notification/notification-setting"
    schema_type = "setting"

    schema = {
        "title": "Notification Settings",
        "description": "Configure notification preferences.",
        "endpoint": "/api/core/notification/settings/",
        "ui": {
            "layout": "form",
            "show_header": True,
        },
    }

    def get_object(self):
        return self.service_class.get_settings(self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)