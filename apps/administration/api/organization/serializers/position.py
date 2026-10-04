from rest_framework import serializers
from apps.administration.models import Position


class PositionSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(
        source="company.name",
        read_only=True,
        default=None,
    )
    branch_name = serializers.CharField(
        source="branch.name",
        read_only=True,
        default=None,
    )
    location_name = serializers.CharField(
        source="location.name",
        read_only=True,
        default=None,
    )
    division_name = serializers.CharField(
        source="division.name",
        read_only=True,
        default=None,
    )
    department_name = serializers.CharField(
        source="department.name",
        read_only=True,
        default=None,
    )
    section_name = serializers.CharField(
        source="section.name",
        read_only=True,
        default=None,
    )
    job_category_name = serializers.CharField(
        source="job_category.name",
        read_only=True,
        default=None,
    )
    job_level_name = serializers.CharField(
        source="job_level.name",
        read_only=True,
        default=None,
    )

    class Meta:
        model = Position
        fields = "__all__"