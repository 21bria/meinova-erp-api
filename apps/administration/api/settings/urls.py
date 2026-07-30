from django.urls import path

from apps.administration.api.settings.views.settings import (
    TenantSettingAPIView,
    SystemSettingAPIView,
    PrintSettingAPIView,
)

urlpatterns = [
    path("tenant/", TenantSettingAPIView.as_view(), name="tenant-setting"),
    path("system/", SystemSettingAPIView.as_view(), name="system-setting"),
    path("print/", PrintSettingAPIView.as_view(), name="print-setting"),
]