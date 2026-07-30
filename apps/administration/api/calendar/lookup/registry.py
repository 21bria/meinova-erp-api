from django.db.models import Q
from apps.framework.lookup import (
    BaseLookup,
    register_lookup,
)

from apps.administration.models import (
    FiscalYear,
    Holiday,
    PostingPeriod,
    WorkCalendar,
)


@register_lookup
class FiscalYearLookup(BaseLookup):
    name = "fiscal-years"
    model = FiscalYear

    search_fields = [
        "code",
        "name",
    ]

    filter_fields = [
        "company_id",
        "year",
        "is_closed",
    ]

    ordering = [
        "-year",
    ]


@register_lookup
class PostingPeriodLookup(BaseLookup):
    name = "posting-periods"
    model = PostingPeriod

    search_fields = [
        "code",
        "name",
    ]

    filter_fields = [
        "fiscal_year_id",
        "status",
    ]

    ordering = [
        "start_date",
    ]


@register_lookup
class HolidayLookup(BaseLookup):
    name = "holidays"
    model = Holiday

    search_fields = [
        "code",
        "name",
    ]

    filter_fields = [
        "company_id",
        "site_id",
        "date",
        "is_national",
        "is_recurring",
    ]

    ordering = [
        "date",
    ]


# @register_lookup
# class WorkCalendarLookup(BaseLookup):
#     name = "work-calendars"
#     model = WorkCalendar

#     search_fields = [
#         "code",
#         "name",
#     ]

#     filter_fields = [
#         "company_id",
#         "site_id",
#         "is_default",
#     ]

#     ordering = [
#         "name",
#     ]
@register_lookup

class WorkCalendarLookup(BaseLookup):

    name = "work-calendars"

    model = WorkCalendar

    search_fields = [

        "code",

        "name",

    ]

    filter_fields = [

        "company_id",

    ]

    ordering = [

        "-is_default",

        "name",

    ]

    @classmethod

    def apply_filters(

        cls,

        queryset,

        request,

    ):

        company_id = request.query_params.get(

            "company_id",

        )

        site_id = request.query_params.get(

            "site_id",

        )

        if company_id:

            queryset = queryset.filter(

                company_id=company_id,

            )

        if site_id:

            queryset = queryset.filter(

                Q(site_id=site_id)

                | Q(

                    site__isnull=True,

                    is_default=True,

                )

            )

        else:

            queryset = queryset.filter(

                site__isnull=True,

            )

        return queryset
