from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.reference import BaseReferenceViewSet

from apps.administration.api.reference.hr.serializers.hr_attendance import *
from apps.administration.api.reference.hr.services.hr_attendance import *


def reference_schema(slug):
    return {
        "endpoint": f"/api/administration/references/hr/{slug}/",
        "ui": {
            "editor": "dialog",
            "size": "lg",
            "columns": 2,
        },
        "fields": {
            "code": {
                "label": "Code",
                "form": True,
                "table": True,
                "order": 10,
            },
            "name": {
                "label": "Name",
                "form": True,
                "table": True,
                "order": 20,
            },
            "description": {
                "label": "Description",
                "form": True,
                "table": False,
                "filter": False,
                "widget": "textarea",
                "rows": 4,
                "layout": "full",
                "order": 30,
            },
            "is_active": {
                "label": "Active",
                "form": True,
                "table": True,
                "filter": True,
                "placement": "quick",
                "order": 999,
            },
        },
    }


# -----------------------------------------------------------------------------
# Shift Group
# -----------------------------------------------------------------------------


class ShiftGroupViewSet(BaseReferenceViewSet):
    serializer_class = ShiftGroupSerializer
    service_class = ShiftGroupService

    framework_module = "references/hr/shift-groups"
    schema = reference_schema("shift-groups")


# -----------------------------------------------------------------------------
# Shift
# -----------------------------------------------------------------------------


class ShiftViewSet(BaseMasterViewSet):
    serializer_class = ShiftSerializer
    service_class = ShiftService

    framework_module = "references/hr/shifts"
    schema_type = "crud"

    schema = {
        **reference_schema("shifts"),
        "title": "Shifts",
        "description": "Manage work shifts.",
        "fields": {
            **reference_schema("shifts")["fields"],
            "shift_group": {
                "label": "Shift Group",
                "form": True,
                "table": True,
                "filter": True,
                "widget": "lookup",
                "lookup_endpoint": (
                    "/api/administration/references/hr/"
                    "lookup/shift-groups/"
                ),
                "order": 30,
            },
            "start_time": {
                "label": "Start Time",
                "form": True,
                "table": True,
                "order": 40,
            },
            "end_time": {
                "label": "End Time",
                "form": True,
                "table": True,
                "order": 50,
            },
            "break_start_time": {
                "label": "Break Start",
                "form": True,
                "table": False,
                "order": 60,
            },
            "break_end_time": {
                "label": "Break End",
                "form": True,
                "table": False,
                "order": 70,
            },
            "crosses_midnight": {
                "label": "Crosses Midnight",
                "form": True,
                "table": True,
                "filter": True,
                "order": 80,
            },
        },
    }


# -----------------------------------------------------------------------------
# Work Schedule
# -----------------------------------------------------------------------------


class WorkScheduleViewSet(BaseMasterViewSet):
    serializer_class = WorkScheduleSerializer
    service_class = WorkScheduleService

    framework_module = "references/hr/work-schedules"
    schema_type = "crud"

    schema = {
        **reference_schema("work-schedules"),
        "title": "Work Schedules",
        "description": "Manage employee work schedules.",
        "fields": {
            **reference_schema("work-schedules")["fields"],
            "schedule_type": {
                "label": "Schedule Type",
                "form": True,
                "table": True,
                "filter": True,
                "order": 40,
            },
            "standard_hours_per_day": {
                "label": "Standard Hours per Day",
                "form": True,
                "table": True,
                "order": 50,
            },
            "standard_hours_per_week": {
                "label": "Standard Hours per Week",
                "form": True,
                "table": True,
                "order": 60,
            },
            "work_days": {
                "label": "Work Days",
                "form": True,
                "table": True,
                "order": 70,
            },
            "cycle_work_days": {
                "label": "Cycle Work Days",
                "form": True,
                "table": False,
                "order": 80,
            },
            "cycle_off_days": {
                "label": "Cycle Off Days",
                "form": True,
                "table": False,
                "order": 90,
            },
            "is_flexible": {
                "label": "Flexible",
                "form": True,
                "table": True,
                "filter": True,
                "order": 100,
            },
            "crosses_midnight": {
                "label": "Crosses Midnight",
                "form": True,
                "table": True,
                "filter": True,
                "order": 110,
            },
        },
    }


# -----------------------------------------------------------------------------
# Work Schedule Day
# -----------------------------------------------------------------------------


class WorkScheduleDayViewSet(BaseMasterViewSet):
    search_fields = [
        "work_schedule__code",
        "work_schedule__name",
        "shift__code",
        "shift__name",
    ]

    # `BaseMasterViewSet.ordering` bawaannya `["name"]`, dan model ini
    # tidak punya kolom itu — ia baris hari, bukan master bernama. Tanpa
    # ditimpa, **setiap** permintaan daftar dibalas 500 berbunyi "Cannot
    # resolve keyword 'name'". Jebakan yang sebentuk dengan
    # `search_fields`, cuma jalur gagalnya berbeda: pencarian sudah
    # dijaring `SafeSearchFilter`, pengurutan tidak.
    ordering = ["work_schedule__code", "weekday"]

    serializer_class = WorkScheduleDaySerializer
    service_class = WorkScheduleDayService

    framework_module = "references/hr/work-schedule-days"
    schema_type = "crud"

    schema = {
        "title": "Work Schedule Days",
        "description": "Manage work schedule details.",
        "endpoint": (
            "/api/administration/references/hr/"
            "work-schedule-days/"
        ),
        "ui": {
            "editor": "dialog",
            "size": "lg",
            "columns": 2,
        },
        "fields": {
            "work_schedule": {
                "label": "Work Schedule",
                "form": True,
                "table": True,
                "filter": True,
                "widget": "lookup",
                "lookup_endpoint": (
                    "/api/administration/references/hr/"
                    "lookup/work-schedules/"
                ),
                "order": 10,
            },
            "weekday": {
                "label": "Weekday",
                "form": True,
                "table": True,
                "filter": True,
                "order": 20,
            },
            "shift": {
                "label": "Shift",
                "form": True,
                "table": True,
                "filter": True,
                "widget": "lookup",
                "lookup_endpoint": (
                    "/api/administration/references/hr/"
                    "lookup/shifts/"
                ),
                "order": 30,
            },
            "is_working_day": {
                "label": "Working Day",
                "form": True,
                "table": True,
                "filter": True,
                "order": 40,
            },
            "start_time": {
                "label": "Start Time",
                "form": True,
                "table": True,
                "order": 50,
            },
            "end_time": {
                "label": "End Time",
                "form": True,
                "table": True,
                "order": 60,
            },
            "break_start_time": {
                "label": "Break Start",
                "form": True,
                "table": False,
                "order": 70,
            },
            "break_end_time": {
                "label": "Break End",
                "form": True,
                "table": False,
                "order": 80,
            },
            "break_minutes": {
                "label": "Break Minutes",
                "form": True,
                "table": True,
                "order": 90,
            },
            "tolerance_in_minutes": {
                "label": "Check-in Tolerance",
                "form": True,
                "table": False,
                "order": 100,
            },
            "tolerance_out_minutes": {
                "label": "Check-out Tolerance",
                "form": True,
                "table": False,
                "order": 110,
            },
        },
    }