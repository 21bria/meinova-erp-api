from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.administration.api.notification.views.notification import (
    NotificationViewSet,
    NotificationSettingAPIView,
)

router = DefaultRouter()
router.register("notifications", NotificationViewSet, basename="notification")

urlpatterns = [
    path("", include(router.urls)),
    path(
        "settings/",
        NotificationSettingAPIView.as_view(),
        name="notification-setting",
    ),
]