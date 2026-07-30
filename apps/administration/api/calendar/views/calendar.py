from apps.framework.views.master import BaseMasterViewSet

from apps.administration.api.calendar.serializers.calendar import (
    FiscalYearSerializer,
    PostingPeriodSerializer,
    HolidaySerializer,
    WorkCalendarSerializer,
)
from apps.administration.api.calendar.services.calendar_service import (
    FiscalYearService,
    PostingPeriodService,
    HolidayService,
    WorkCalendarService,
)


class FiscalYearViewSet(BaseMasterViewSet):
    serializer_class = FiscalYearSerializer
    service_class = FiscalYearService
    framework_module = "administration/calendar/fiscal-year"
    schema_type = "crud"
    schema = {
        "title": "Fiscal Year",
        "description": "Manage fiscal years used for accounting and reporting.",
    }
    ordering = ["name"]
    search_fields = ["code", "name"]
    filterset_fields = ["is_active"]


class PostingPeriodViewSet(BaseMasterViewSet):
    serializer_class = PostingPeriodSerializer
    service_class = PostingPeriodService
    framework_module = "administration/calendar/posting-period"
    schema_type = "crud"
    schema = {
        "title": "Posting Period",
        "description": "Manage posting periods for financial transactions.",
    }
    ordering = ["name"]
    search_fields = ["code", "name"]
    filterset_fields = ["is_active", "fiscal_year"]


class HolidayViewSet(BaseMasterViewSet):
    serializer_class = HolidaySerializer
    service_class = HolidayService
    framework_module = "administration/calendar/holiday"
    schema_type = "crud"
    schema = {
        "title": "Holiday",
        "description": "Manage public holidays and non-working days.",
    }
    ordering = ["date"]
    search_fields = ["name"]
    filterset_fields = ["calendar", "is_active"]


class WorkCalendarViewSet(BaseMasterViewSet):
    serializer_class = WorkCalendarSerializer
    service_class = WorkCalendarService
    framework_module = "administration/calendar/work-calendar"
    schema_type = "crud"
    schema = {
        "title": "Work Calendar",
        "description": "Manage work calendars and business schedules.",
    }
    ordering = ["name"]
    search_fields = ["code", "name"]
    filterset_fields = ["is_active"]