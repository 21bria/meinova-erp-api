from django.urls import include, path

from rest_framework.routers import DefaultRouter

from apps.administration.api.settings.views.settings import (
    PrintSettingAPIView,
    PrintSettingViewSet,
    SystemSettingAPIView,
    TenantSettingAPIView,
    TenantSettingViewSet,
)


router = DefaultRouter()

router.register(
    "tenant-settings",
    TenantSettingViewSet,
    basename="tenant-settings",
)

router.register(
    "print-settings",
    PrintSettingViewSet,
    basename="print-settings",
)


urlpatterns = [
    # Jalur lama — satu record, diambil `.first()`. Dibiarkan hidup
    # sebagai transisi: layar Settings yang sekarang masih memakainya,
    # dan mematikannya berarti halaman itu 404 sebelum penggantinya ada.
    path("tenant/", TenantSettingAPIView.as_view(), name="tenant-setting"),
    path("system/", SystemSettingAPIView.as_view(), name="system-setting"),
    path("print/", PrintSettingAPIView.as_view(), name="print-setting"),

    # Jalur baru — satu baris per company, dengan tombol Add.
    path("", include(router.urls)),
]
