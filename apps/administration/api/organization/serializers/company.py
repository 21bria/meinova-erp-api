from rest_framework import serializers

from apps.administration.models import Company


class CompanySerializer(serializers.ModelSerializer):
    parent_name = serializers.CharField(
        source="parent.name",
        read_only=True,
    )

    company_type_name = serializers.CharField(
        source="company_type.name",
        read_only=True,
    )

    country_name = serializers.CharField(
        source="country.name",
        read_only=True,
    )

    province_name = serializers.CharField(
        source="province.name",
        read_only=True,
    )

    city_name = serializers.CharField(
        source="city.name",
        read_only=True,
    )

    class Meta:
        model = Company
        fields = "__all__"