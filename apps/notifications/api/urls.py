from django.urls import include, path
from rest_framework.routers import DefaultRouter

from .log.views import NotificationLogViewSet
from .rule.views import NotificationRuleViewSet
from .setting.views import (
    NotificationEventCatalogView,
    NotificationSettingAPIView,
)
from .template.views import EmailTemplateViewSet

router = DefaultRouter()
router.register("templates", EmailTemplateViewSet, basename="email-template")
router.register("rules", NotificationRuleViewSet, basename="notification-rule")
router.register("logs", NotificationLogViewSet, basename="notification-log")

urlpatterns = [
    # Rute spesifik di atas router — kalau tidak, `settings/` dan
    # `events/` bisa tertelan pola detail milik router.
    path(
        "settings/",
        NotificationSettingAPIView.as_view(),
        name="notification-setting",
    ),
    path(
        "events/",
        NotificationEventCatalogView.as_view(),
        name="notification-event-catalog",
    ),

    path("", include(router.urls)),
]
