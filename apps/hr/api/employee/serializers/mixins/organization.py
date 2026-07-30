from rest_framework import serializers

from apps.administration.models import (
    Branch,
    Company,
    CostCenter,
    Department,
    Division,
    Position,
    Section,
    Site,
)

from apps.administration.models.references.hr import (
    JobGrade,
    JobLevel,
)

from apps.hr.models import Employee


class EmployeeOrganizationFieldsMixin(
    serializers.Serializer,
):
    company = serializers.PrimaryKeyRelatedField(
        source="organization.company",
        queryset=Company.objects.all(),
        required=False,
        allow_null=True,
    )

    branch = serializers.PrimaryKeyRelatedField(
        source="organization.branch",
        queryset=Branch.objects.all(),
        required=False,
        allow_null=True,
    )

    site = serializers.PrimaryKeyRelatedField(
        source="organization.site",
        queryset=Site.objects.all(),
        required=False,
        allow_null=True,
    )

    division = serializers.PrimaryKeyRelatedField(
        source="organization.division",
        queryset=Division.objects.all(),
        required=False,
        allow_null=True,
    )

    department = serializers.PrimaryKeyRelatedField(
        source="organization.department",
        queryset=Department.objects.all(),
        required=False,
        allow_null=True,
    )

    section = serializers.PrimaryKeyRelatedField(
        source="organization.section",
        queryset=Section.objects.all(),
        required=False,
        allow_null=True,
    )

    position = serializers.PrimaryKeyRelatedField(
        source="organization.position",
        queryset=Position.objects.all(),
        required=False,
        allow_null=True,
    )

    job_level = serializers.PrimaryKeyRelatedField(
        source="organization.job_level",
        queryset=JobLevel.objects.all(),
        required=False,
        allow_null=True,
    )

    job_grade = serializers.PrimaryKeyRelatedField(
        source="organization.job_grade",
        queryset=JobGrade.objects.all(),
        required=False,
        allow_null=True,
    )

    reports_to = serializers.PrimaryKeyRelatedField(
        source="organization.reports_to",
        queryset=Employee.objects.all(),
        required=False,
        allow_null=True,
    )

    cost_center = serializers.PrimaryKeyRelatedField(
        source="organization.cost_center",
        queryset=CostCenter.objects.all(),
        required=False,
        allow_null=True,
    )

    organization_effective_date = serializers.DateField(
        source="organization.organization_effective_date",
        required=False,
        allow_null=True,
    )

    organization_notes = serializers.CharField(
        source="organization.organization_notes",
        required=False,
        allow_blank=True,
    )