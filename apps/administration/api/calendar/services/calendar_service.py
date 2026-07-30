from apps.administration.models import FiscalYear, PostingPeriod, Holiday, WorkCalendar


class FiscalYearService:
    @staticmethod
    def list():
        return FiscalYear.objects.select_related("company").order_by("-year")


class PostingPeriodService:
    @staticmethod
    def list():
        return PostingPeriod.objects.select_related("fiscal_year").order_by(
            "fiscal_year__year",
            "period_no",
        )


class HolidayService:
    @staticmethod
    def list():
        return Holiday.objects.select_related("company", "site").order_by("date")


class WorkCalendarService:
    @staticmethod
    def list():
        return WorkCalendar.objects.select_related("company", "site").order_by("name")