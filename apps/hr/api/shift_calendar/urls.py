from django.urls import path

from rest_framework.routers import DefaultRouter

from .views import (
    EmployeeShiftAssignmentViewSet,
    ShiftCalendarAccessView,
    ShiftCalendarView,
)


router = DefaultRouter()

router.register(
    "shift-assignments",
    EmployeeShiftAssignmentViewSet,
    basename="shift-assignment",
)

urlpatterns = [
    # Rute path-tetap di atas router supaya tidak tertelan `<str:pk>`.
    path(
        "shift-calendar/access/",
        ShiftCalendarAccessView.as_view(),
        name="shift-calendar-access",
    ),
    path("shift-calendar/", ShiftCalendarView.as_view(), name="shift-calendar"),
    *router.urls,
]
