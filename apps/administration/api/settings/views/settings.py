from rest_framework.permissions import IsAuthenticated
from apps.framework.views.setting import BaseSettingAPIView

from apps.administration.api.settings.serializers.settings import (
    TenantSettingSerializer,
    SystemSettingSerializer,
    PrintSettingSerializer,
)

from apps.administration.api.settings.services.settings_service import (
    TenantSettingService,
    SystemSettingService,
    PrintSettingService,
)


class TenantSettingAPIView(BaseSettingAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = TenantSettingSerializer
    service_class = TenantSettingService

    framework_module = "administration/settings/tenant-setting"
    schema_type = "setting"

    schema = {
        "title": "Tenant Settings",
        "description": "Configure tenant-specific application settings.",
        "endpoint": "/api/administration/settings/tenant/",
        "ui": {
            "layout": "form",
            "show_header": True,
        },
    }

    def get_object(self):
        return self.service_class.get_settings()


class SystemSettingAPIView(BaseSettingAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = SystemSettingSerializer
    service_class = SystemSettingService
    
    framework_module = "administration/settings/system-setting"
    schema_type = "setting"
    schema = {
        "title": "System Settings",
        "description": "Configure global system settings.",
        "endpoint": "/api/administration/settings/system/",
        "ui": {
            "layout": "form",
            "show_header": True,
        },
    }

    def get_object(self):
        return self.service_class.get_settings()


class PrintSettingAPIView(BaseSettingAPIView):
    permission_classes = [IsAuthenticated]
    serializer_class = PrintSettingSerializer
    service_class = PrintSettingService
    framework_module = "administration/settings/print-setting"
    schema_type = "setting"
    schema = {
        "title": "Print Settings",
        "description": "Configure document and printing settings.",
        "endpoint": "/api/administration/settings/print/",
        "ui": {
            "layout": "form",
            "show_header": True,
        },
    }

    def get_object(self):
        return self.service_class.get_settings()