from django.urls import path

from .views import (
    AttendanceSyncAPIView,
)


urlpatterns = [
    path("attendance/sync/",AttendanceSyncAPIView.as_view(),name="attendance-sync"),
]