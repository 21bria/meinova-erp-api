# ython manage.py tenant_command seed_hr_attendance --schema=demo

from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models.base_reference import BaseReference


class ShiftGroup(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_shift_group"


class Shift(BaseReference):
    shift_group = models.ForeignKey(
        ShiftGroup,
        on_delete=models.PROTECT,
        related_name="shifts",
        null=True,
        blank=True,
    )

    start_time = models.TimeField()
    end_time = models.TimeField()

    break_start_time = models.TimeField(
        null=True,
        blank=True,
    )
    break_end_time = models.TimeField(
        null=True,
        blank=True,
    )

    crosses_midnight = models.BooleanField(default=False)

    class Meta(BaseReference.Meta):
        db_table = "master_shift"
        ordering = ["sort_order", "name"]

    def clean(self):
        super().clean()

        if self.start_time == self.end_time:
            raise ValidationError(
                {
                    "end_time": (
                        "End time harus berbeda dari start time."
                    )
                }
            )


class WorkSchedule(BaseReference):
    class ScheduleType(models.TextChoices):
        WEEKLY = "WEEKLY", "Weekly"
        ROSTER = "ROSTER", "Roster"
        FLEXIBLE = "FLEXIBLE", "Flexible"

    schedule_type = models.CharField(
        max_length=20,
        choices=ScheduleType.choices,
        default=ScheduleType.WEEKLY,
    )

    standard_hours_per_day = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=8,
    )
    standard_hours_per_week = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=40,
    )

    work_days = models.PositiveSmallIntegerField(
        default=5,
        help_text="Jumlah hari kerja dalam satu minggu atau siklus.",
    )

    cycle_work_days = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Jumlah hari kerja pada pola roster, misalnya 14.",
    )
    cycle_off_days = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Jumlah hari libur pada pola roster, misalnya 14.",
    )

    is_flexible = models.BooleanField(default=False)
    crosses_midnight = models.BooleanField(default=False)

    class Meta(BaseReference.Meta):
        db_table = "master_work_schedule"
        ordering = ["sort_order", "name"]

    def clean(self):
        super().clean()

        errors = {}

        if self.schedule_type == self.ScheduleType.ROSTER:
            if not self.cycle_work_days:
                errors["cycle_work_days"] = (
                    "Cycle work days wajib diisi untuk jadwal roster."
                )

            if not self.cycle_off_days:
                errors["cycle_off_days"] = (
                    "Cycle off days wajib diisi untuk jadwal roster."
                )

        if errors:
            raise ValidationError(errors)


class WorkScheduleDay(models.Model):
    class Weekday(models.IntegerChoices):
        MONDAY = 1, "Monday"
        TUESDAY = 2, "Tuesday"
        WEDNESDAY = 3, "Wednesday"
        THURSDAY = 4, "Thursday"
        FRIDAY = 5, "Friday"
        SATURDAY = 6, "Saturday"
        SUNDAY = 7, "Sunday"

    work_schedule = models.ForeignKey(
        WorkSchedule,
        on_delete=models.CASCADE,
        related_name="schedule_days",
    )

    weekday = models.PositiveSmallIntegerField(
        choices=Weekday.choices,
    )

    shift = models.ForeignKey(
        Shift,
        on_delete=models.PROTECT,
        related_name="schedule_days",
        null=True,
        blank=True,
    )

    is_working_day = models.BooleanField(default=True)

    start_time = models.TimeField(null=True, blank=True)
    end_time = models.TimeField(null=True, blank=True)

    break_start_time = models.TimeField(null=True, blank=True)
    break_end_time = models.TimeField(null=True, blank=True)
    break_minutes = models.PositiveSmallIntegerField(default=60)

    tolerance_in_minutes = models.PositiveSmallIntegerField(default=0)
    tolerance_out_minutes = models.PositiveSmallIntegerField(default=0)

    class Meta:
        db_table = "master_work_schedule_day"
        ordering = ["weekday"]
        constraints = [
            models.UniqueConstraint(
                fields=["work_schedule", "weekday"],
                name="uniq_work_schedule_weekday",
            ),
        ]

    def clean(self):
        super().clean()

        errors = {}

        if self.is_working_day:
            has_shift = self.shift_id is not None
            has_manual_time = bool(self.start_time and self.end_time)

            if not has_shift and not has_manual_time:
                errors["shift"] = (
                    "Pilih shift atau isi start time dan end time."
                )

            if bool(self.start_time) != bool(self.end_time):
                errors["start_time"] = (
                    "Start time dan end time harus diisi bersamaan."
                )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return (
            f"{self.work_schedule.name} - "
            f"{self.get_weekday_display()}"
        )