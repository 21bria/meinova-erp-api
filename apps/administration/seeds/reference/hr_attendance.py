from datetime import time

from django.db import transaction

from apps.administration.models import (
    Shift,
    ShiftGroup,
    WorkSchedule,
    WorkScheduleDay,
)


@transaction.atomic
def seed():
    """Seed HR Attendance master data."""

    # -------------------------------------------------------------------------
    # Shift Groups
    # -------------------------------------------------------------------------

    office_group, _ = ShiftGroup.objects.update_or_create(
        code="OFFICE",
        defaults={
            "name": "Office Shift",
            "description": "Shift group for office employees.",
            "sort_order": 10,
            "is_active": True,
        },
    )

    mining_group, _ = ShiftGroup.objects.update_or_create(
        code="MINING",
        defaults={
            "name": "Mining Shift",
            "description": "Shift group for mining operations.",
            "sort_order": 20,
            "is_active": True,
        },
    )

    # -------------------------------------------------------------------------
    # Shifts
    # -------------------------------------------------------------------------

    office_shift, _ = Shift.objects.update_or_create(
        code="OFFICE",
        defaults={
            "name": "Office",
            "description": "Regular office shift.",
            "shift_group": office_group,
            "start_time": time(8, 0),
            "end_time": time(17, 0),
            "break_start_time": time(12, 0),
            "break_end_time": time(13, 0),
            "crosses_midnight": False,
            "sort_order": 10,
            "is_active": True,
        },
    )

    day_shift, _ = Shift.objects.update_or_create(
        code="DAY",
        defaults={
            "name": "Day Shift",
            "description": "Mining operational day shift.",
            "shift_group": mining_group,
            "start_time": time(7, 0),
            "end_time": time(19, 0),
            "break_start_time": time(12, 0),
            "break_end_time": time(13, 0),
            "crosses_midnight": False,
            "sort_order": 20,
            "is_active": True,
        },
    )

    night_shift, _ = Shift.objects.update_or_create(
        code="NIGHT",
        defaults={
            "name": "Night Shift",
            "description": "Mining operational night shift.",
            "shift_group": mining_group,
            "start_time": time(19, 0),
            "end_time": time(7, 0),
            "break_start_time": time(0, 0),
            "break_end_time": time(1, 0),
            "crosses_midnight": True,
            "sort_order": 30,
            "is_active": True,
        },
    )

    # -------------------------------------------------------------------------
    # Work Schedules
    # -------------------------------------------------------------------------

    regular_schedule, _ = WorkSchedule.objects.update_or_create(
        code="REG5",
        defaults={
            "name": "Regular 5 Days",
            "description": "Monday to Friday office schedule.",
            "schedule_type": WorkSchedule.ScheduleType.WEEKLY,
            "standard_hours_per_day": 8,
            "standard_hours_per_week": 40,
            "work_days": 5,
            "cycle_work_days": None,
            "cycle_off_days": None,
            "is_flexible": False,
            "crosses_midnight": False,
            "sort_order": 10,
            "is_active": True,
        },
    )

    roster_schedule, _ = WorkSchedule.objects.update_or_create(
        code="ROS14",
        defaults={
            "name": "Roster 14 On 14 Off",
            "description": (
                "Fourteen working days followed by fourteen off days."
            ),
            "schedule_type": WorkSchedule.ScheduleType.ROSTER,
            "standard_hours_per_day": 12,
            "standard_hours_per_week": 84,
            "work_days": 14,
            "cycle_work_days": 14,
            "cycle_off_days": 14,
            "is_flexible": False,
            "crosses_midnight": True,
            "sort_order": 20,
            "is_active": True,
        },
    )

    # -------------------------------------------------------------------------
    # Regular Schedule Days
    # -------------------------------------------------------------------------

    regular_schedule_day_count = 0

    for weekday in range(
        WorkScheduleDay.Weekday.MONDAY,
        WorkScheduleDay.Weekday.SUNDAY + 1,
    ):
        is_working_day = weekday <= WorkScheduleDay.Weekday.FRIDAY

        WorkScheduleDay.objects.update_or_create(
            work_schedule=regular_schedule,
            weekday=weekday,
            defaults={
                "shift": office_shift if is_working_day else None,
                "is_working_day": is_working_day,
                "start_time": (
                    time(8, 0)
                    if is_working_day
                    else None
                ),
                "end_time": (
                    time(17, 0)
                    if is_working_day
                    else None
                ),
                "break_start_time": (
                    time(12, 0)
                    if is_working_day
                    else None
                ),
                "break_end_time": (
                    time(13, 0)
                    if is_working_day
                    else None
                ),
                "break_minutes": (
                    60
                    if is_working_day
                    else 0
                ),
                "tolerance_in_minutes": (
                    15
                    if is_working_day
                    else 0
                ),
                "tolerance_out_minutes": (
                    15
                    if is_working_day
                    else 0
                ),
            },
        )

        regular_schedule_day_count += 1

    # -------------------------------------------------------------------------
    # Roster Template Days
    # -------------------------------------------------------------------------
    #
    # WorkScheduleDay masih berbasis weekday.
    #
    # Siklus 14 hari kerja dan 14 hari libur nantinya ditangani oleh model
    # roster assignment atau shift assignment berdasarkan tanggal.
    #
    # Detail di bawah hanya menjadi template default jam kerja operasional.
    # -------------------------------------------------------------------------

    roster_schedule_day_count = 0

    for weekday in range(
        WorkScheduleDay.Weekday.MONDAY,
        WorkScheduleDay.Weekday.SUNDAY + 1,
    ):
        WorkScheduleDay.objects.update_or_create(
            work_schedule=roster_schedule,
            weekday=weekday,
            defaults={
                "shift": day_shift,
                "is_working_day": True,
                "start_time": time(7, 0),
                "end_time": time(19, 0),
                "break_start_time": time(12, 0),
                "break_end_time": time(13, 0),
                "break_minutes": 60,
                "tolerance_in_minutes": 15,
                "tolerance_out_minutes": 15,
            },
        )

        roster_schedule_day_count += 1

    # -------------------------------------------------------------------------
    # Result
    # -------------------------------------------------------------------------

    return {
        "shift_groups": 2,
        "shifts": 3,
        "work_schedules": 2,
        "work_schedule_days": (
            regular_schedule_day_count
            + roster_schedule_day_count
        ),
        "objects": {
            "office_group": office_group,
            "mining_group": mining_group,
            "office_shift": office_shift,
            "day_shift": day_shift,
            "night_shift": night_shift,
            "regular_schedule": regular_schedule,
            "roster_schedule": roster_schedule,
        },
    }