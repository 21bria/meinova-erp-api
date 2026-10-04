from rest_framework import serializers

from apps.administration.models.references.organization import (
    BranchType,
    CompanyType,
    FacilityType,
    LocationType,
)


class CompanyTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = CompanyType
        fields = "__all__"


class BranchTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = BranchType
        fields = "__all__"


class LocationTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = LocationType
        fields = "__all__"



class FacilityTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = FacilityType
        fields = "__all__"
