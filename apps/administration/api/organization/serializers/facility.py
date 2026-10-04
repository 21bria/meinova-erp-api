from rest_framework import serializers

from apps.administration.models import Facility


class FacilitySerializer(serializers.ModelSerializer):
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
    facility_type_name = serializers.CharField(
        source="facility_type.name",
        read_only=True,
        default=None,
    )

    class Meta:
        model = Facility
        fields = "__all__"
