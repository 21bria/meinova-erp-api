from rest_framework import serializers

from apps.administration.models import Division


class DivisionSerializer(serializers.ModelSerializer):
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

    class Meta:
        model = Division
        fields = [
            "id",
            "company",
            "company_name",
            "branch",
            "branch_name",
            "location",
            "location_name",
            "code",
            "name",
            "is_active",
            "created_at",
            "updated_at",
        ]

        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
        ]