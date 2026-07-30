from rest_framework import serializers

from apps.administration.models import FiscalYear, PostingPeriod, Holiday, WorkCalendar


class FiscalYearSerializer(serializers.ModelSerializer):
    class Meta:
        model = FiscalYear
        fields = "__all__"


class PostingPeriodSerializer(serializers.ModelSerializer):
    class Meta:
        model = PostingPeriod
        fields = "__all__"


class HolidaySerializer(serializers.ModelSerializer):
    class Meta:
        model = Holiday
        fields = "__all__"


class WorkCalendarSerializer(serializers.ModelSerializer):
    class Meta:
        model = WorkCalendar
        fields = "__all__"