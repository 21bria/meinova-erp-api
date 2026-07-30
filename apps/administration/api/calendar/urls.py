from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.administration.api.calendar.views.calendar import (
    FiscalYearViewSet,
    PostingPeriodViewSet,
    HolidayViewSet,
    WorkCalendarViewSet,
)

router = DefaultRouter()
router.register("fiscal-years", FiscalYearViewSet, basename="calendar-fiscal-year")
router.register("posting-periods", PostingPeriodViewSet, basename="calendar-posting-period")
router.register("holidays", HolidayViewSet, basename="calendar-holiday")
router.register("work-calendars", WorkCalendarViewSet, basename="calendar-work-calendar")

urlpatterns = [
     path(
        "lookup/",
        include("apps.administration.api.calendar.lookup.urls"),
    ),
    path("", include(router.urls)),
]