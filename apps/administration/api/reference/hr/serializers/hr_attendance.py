from rest_framework import serializers

from apps.administration.models.references.hr_attendance import (
    ShiftGroup,
    Shift,
    WorkSchedule,
    WorkScheduleDay,
)


class ShiftGroupSerializer(serializers.ModelSerializer):
    class Meta:
        model = ShiftGroup
        fields = "__all__"


class ShiftSerializer(serializers.ModelSerializer):
    shift_group_name = serializers.CharField(
        source="shift_group.name",
        read_only=True,
    )

    class Meta:
        model = Shift
        fields = "__all__"


class WorkScheduleDaySerializer(serializers.ModelSerializer):
    weekday_name = serializers.CharField(
        source="get_weekday_display",
        read_only=True,
    )

    shift_name = serializers.CharField(
        source="shift.name",
        read_only=True,
    )

    class Meta:
        model = WorkScheduleDay
        fields = "__all__"


class WorkScheduleSerializer(serializers.ModelSerializer):
    schedule_days = WorkScheduleDaySerializer(
        many=True,
        read_only=True,
    )

    schedule_type_name = serializers.CharField(
        source="get_schedule_type_display",
        read_only=True,
    )

    class Meta:
        model = WorkSchedule
        fields = "__all__"