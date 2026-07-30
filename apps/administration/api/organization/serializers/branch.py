
from rest_framework import serializers
from apps.administration.models import Branch


class BranchSerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(
            source="company.name",
            read_only=True,
            default=None,
        )
    class Meta:
        model = Branch
        fields = "__all__"