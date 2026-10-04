from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.administration.api.calendar.views.calendar import (
    HolidayViewSet,
    WorkCalendarViewSet,
    RosterCrewViewSet,
)

router = DefaultRouter()
# `fiscal-years/` dan `posting-periods/` pindah ke Finance:
# `/api/finance/fiscal-years/` dan `/api/finance/accounting-periods/`.
router.register("holidays", HolidayViewSet, basename="calendar-holiday")
router.register("work-calendars", WorkCalendarViewSet, basename="calendar-work-calendar")
router.register("roster-crews", RosterCrewViewSet, basename="calendar-roster-crew")

urlpatterns = [
     path(
        "lookup/",
        include("apps.administration.api.calendar.lookup.urls"),
    ),
    path("", include(router.urls)),
]