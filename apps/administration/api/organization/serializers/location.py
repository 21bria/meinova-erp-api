from rest_framework import serializers
from apps.administration.models import Location


class LocationSerializer(serializers.ModelSerializer):
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
    location_type_name = serializers.CharField(
        source="location_type.name",
        read_only=True,
        default=None,
    )
    country_name = serializers.CharField(
        source="country.name",
        read_only=True,
        default=None,
    )
    province_name = serializers.CharField(
        source="province.name",
        read_only=True,
        default=None,
    )
    city_name = serializers.CharField(
        source="city.name",
        read_only=True,
        default=None,
    )

    class Meta:
        model = Location
        fields = "__all__"