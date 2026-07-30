from rest_framework import serializers

from apps.administration.models import WorkCalendar
from apps.administration.models.references.hr import (
    ContractType,
    EmployeeGroup,
    EmploymentStatus,
    EmploymentType,
    ProbationType,
)
from apps.administration.models.references.hr_attendance import (
    Shift,
    WorkSchedule,
)


class EmployeeEmploymentFieldsMixin(
    serializers.Serializer,
):
    employment_status = serializers.PrimaryKeyRelatedField(
        source="employment.employment_status",
        queryset=EmploymentStatus.objects.all(),
        required=False,
        allow_null=True,
    )

    employment_type = serializers.PrimaryKeyRelatedField(
        source="employment.employment_type",
        queryset=EmploymentType.objects.all(),
        required=False,
        allow_null=True,
    )

    employee_group = serializers.PrimaryKeyRelatedField(
        source="employment.employee_group",
        queryset=EmployeeGroup.objects.all(),
        required=False,
        allow_null=True,
    )

    contract_type = serializers.PrimaryKeyRelatedField(
        source="employment.contract_type",
        queryset=ContractType.objects.all(),
        required=False,
        allow_null=True,
    )

    probation_type = serializers.PrimaryKeyRelatedField(
        source="employment.probation_type",
        queryset=ProbationType.objects.all(),
        required=False,
        allow_null=True,
    )

    work_schedule = serializers.PrimaryKeyRelatedField(
        source="employment.work_schedule",
        queryset=WorkSchedule.objects.all(),
        required=False,
        allow_null=True,
    )

    working_calendar = serializers.PrimaryKeyRelatedField(
        source="employment.working_calendar",
        queryset=WorkCalendar.objects.all(),
        required=False,
        allow_null=True,
    )

    shift = serializers.PrimaryKeyRelatedField(
        source="employment.shift",
        queryset=Shift.objects.all(),
        required=False,
        allow_null=True,
    )

    employment_effective_date = serializers.DateField(
        source="employment.effective_from",
        required=False,
        allow_null=True,
    )

    join_date = serializers.DateField(
        source="employment.join_date",
        required=False,
        allow_null=True,
    )

    confirmation_date = serializers.DateField(
        source="employment.confirmation_date",
        required=False,
        allow_null=True,
    )

    probation_start = serializers.DateField(
        source="employment.probation_start",
        required=False,
        allow_null=True,
    )

    probation_end = serializers.DateField(
        source="employment.probation_end",
        required=False,
        allow_null=True,
    )

    contract_start = serializers.DateField(
        source="employment.contract_start",
        required=False,
        allow_null=True,
    )

    contract_end = serializers.DateField(
        source="employment.contract_end",
        required=False,
        allow_null=True,
    )

    notice_period_days = serializers.IntegerField(
        source="employment.notice_period_days",
        required=False,
        allow_null=True,
    )

    employment_notes = serializers.CharField(
        source="employment.employment_notes",
        required=False,
        allow_blank=True,
        default="",
    )