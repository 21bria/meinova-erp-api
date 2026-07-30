from rest_framework import serializers
from apps.administration.models import CostCenter


class CostCenterSerializer(serializers.ModelSerializer):
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
    site_name = serializers.CharField(
        source="site.name",
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
        model = CostCenter
        fields = "__all__"