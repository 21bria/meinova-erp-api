from rest_framework import serializers
from apps.administration.models import Section


class SectionSerializer(serializers.ModelSerializer):
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
    
    class Meta:
        model =Section
        fields = "__all__"