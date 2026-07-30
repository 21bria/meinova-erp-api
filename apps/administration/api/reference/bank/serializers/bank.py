from rest_framework import serializers

from apps.administration.models import Bank, BankBranch


class BankSerializer(serializers.ModelSerializer):
    class Meta:
        model = Bank
        fields = "__all__"


class BankBranchSerializer(serializers.ModelSerializer):
    class Meta:
        model = BankBranch
        fields = "__all__"