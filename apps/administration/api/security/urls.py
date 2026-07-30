from django.urls import path

from apps.administration.api.security.views.security import (
    SecuritySettingAPIView,
    SessionSettingAPIView,
    LoginHistoryAPIView,
    UserSessionAPIView,
)

urlpatterns = [
    path("settings/", SecuritySettingAPIView.as_view()),
    path("sessions/settings/", SessionSettingAPIView.as_view()),
    path("login-history/", LoginHistoryAPIView.as_view()),
    path("user-sessions/", UserSessionAPIView.as_view()),
]