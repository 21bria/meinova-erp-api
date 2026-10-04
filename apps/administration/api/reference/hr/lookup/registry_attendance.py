from apps.framework.lookup import (
    BaseLookup,
    register_lookup,
)

from apps.administration.models import (
    ShiftGroup,
    Shift,
    WorkSchedule,
)


class BaseHRAttendanceLookup(BaseLookup):
    search_fields = [
        "code",
        "name",
    ]

    ordering = [
        "name",
    ]


@register_lookup
class ShiftGroupLookup(BaseHRAttendanceLookup):
    name = "shift-groups"
    model = ShiftGroup


@register_lookup
class ShiftLookup(BaseHRAttendanceLookup):
    name = "shifts"
    model = Shift


@register_lookup
class WorkScheduleLookup(BaseHRAttendanceLookup):
    name = "work-schedules"
    model = WorkSchedule

    # Tanpa didaftarkan di sini, `?schedule_type=ROSTER` diterima lalu
    # diabaikan diam-diam — form Roster Crew akan menampilkan seluruh
    # jadwal, termasuk yang mingguan.
    filter_fields = [
        "schedule_type",
        "is_flexible",
    ]