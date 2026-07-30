from rest_framework import serializers

from apps.administration.models.references.organization import CompanyType, BranchType, SiteType


class CompanyTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = CompanyType
        fields = "__all__"


class BranchTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = BranchType
        fields = "__all__"


class SiteTypeSerializer(serializers.ModelSerializer):
    class Meta:
        model = SiteType
        fields = "__all__"

