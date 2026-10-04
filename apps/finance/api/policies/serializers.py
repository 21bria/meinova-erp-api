from rest_framework import serializers

from apps.finance.models import (
    AccountingPolicy,
    AccountingPolicyLine,
    AccountingPolicyRule,
)


class AccountingPolicyLineSerializer(serializers.ModelSerializer):
    account_name = serializers.SerializerMethodField()

    side_label = serializers.CharField(
        source="get_side_display", read_only=True,
    )

    class Meta:
        model = AccountingPolicyLine
        fields = "__all__"
        read_only_fields = ["account_name", "side_label"]

    def get_account_name(self, obj) -> str | None:
        if obj.account_id is None:
            return None

        return f"{obj.account.code} — {obj.account.name}"


class AccountingPolicyRuleSerializer(serializers.ModelSerializer):
    policy_name = serializers.CharField(
        source="policy.name", read_only=True, default=None,
    )

    line_count = serializers.SerializerMethodField()

    class Meta:
        model = AccountingPolicyRule
        fields = "__all__"
        read_only_fields = ["policy_name", "line_count"]

    def get_line_count(self, obj) -> int:
        return obj.lines.filter(is_deleted=False).count()


class AccountingPolicySerializer(serializers.ModelSerializer):
    company_name = serializers.CharField(
        source="company.name", read_only=True, default=None,
    )

    rule_count = serializers.SerializerMethodField()

    class Meta:
        model = AccountingPolicy
        fields = "__all__"
        read_only_fields = ["company_name", "rule_count"]

    def get_rule_count(self, obj) -> int:
        return obj.rules.filter(is_deleted=False).count()
