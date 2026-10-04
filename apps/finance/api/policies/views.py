from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin

from apps.finance.models import (
    AccountingPolicy,
    AccountingPolicyLine,
    AccountingPolicyRule,
)
from apps.finance.services import (
    AccountingPolicyLineService,
    AccountingPolicyRuleService,
    AccountingPolicyService,
)

from .schema import (
    ACCOUNTING_POLICY_LINE_SCHEMA,
    ACCOUNTING_POLICY_RULE_SCHEMA,
    ACCOUNTING_POLICY_SCHEMA,
)
from .serializers import (
    AccountingPolicyLineSerializer,
    AccountingPolicyRuleSerializer,
    AccountingPolicySerializer,
)


class AccountingPolicyViewSet(ServiceWriteMixin, BaseMasterViewSet):
    serializer_class = AccountingPolicySerializer
    service_class = AccountingPolicyService

    framework_module = "finance/accounting-policies"
    schema = ACCOUNTING_POLICY_SCHEMA

    # Kosong = berlaku untuk semua perusahaan, jadi cakupannya tidak
    # boleh membuang baris ber-company NULL. Ditangani `allow_null` di
    # bawah, sama seperti Account Mapping.
    data_scope = {"company": "company"}

    search_fields = ["code", "name", "event_type", "description"]
    filterset_fields = ["company", "event_type", "is_active"]
    ordering_fields = ["code", "name", "event_type"]
    ordering = ["event_type", "code"]

    def get_queryset(self):
        return (
            AccountingPolicy.objects
            .filter(is_deleted=False)
            .select_related("company")
            .prefetch_related("rules")
        )

    def filter_queryset(self, queryset):
        from rest_framework.viewsets import ModelViewSet

        from apps.accounts.scoping import DataScopeService

        queryset = ModelViewSet.filter_queryset(self, queryset)

        return DataScopeService.filter(
            queryset,
            self.data_scope,
            getattr(getattr(self, "request", None), "user", None),
            allow_null=True,
        )


class AccountingPolicyRuleViewSet(ServiceWriteMixin, BaseMasterViewSet):
    serializer_class = AccountingPolicyRuleSerializer
    service_class = AccountingPolicyRuleService

    framework_module = "finance/accounting-policy-rules"
    schema = ACCOUNTING_POLICY_RULE_SCHEMA

    data_scope = None

    search_fields = ["name", "policy__code", "policy__name"]
    filterset_fields = ["policy", "is_active"]
    ordering_fields = ["sequence", "name"]
    ordering = ["policy__code", "sequence"]

    def get_queryset(self):
        return (
            AccountingPolicyRule.objects
            .filter(is_deleted=False)
            .select_related("policy")
            .prefetch_related("lines")
        )


class AccountingPolicyLineViewSet(ServiceWriteMixin, BaseMasterViewSet):
    serializer_class = AccountingPolicyLineSerializer
    service_class = AccountingPolicyLineService

    framework_module = "finance/accounting-policy-lines"
    schema = ACCOUNTING_POLICY_LINE_SCHEMA

    data_scope = None

    search_fields = ["mapping_key", "amount_source", "rule__name"]
    filterset_fields = ["rule", "side", "is_active"]
    ordering_fields = ["sequence", "side"]
    ordering = ["rule__sequence", "sequence"]

    def get_queryset(self):
        return (
            AccountingPolicyLine.objects
            .filter(is_deleted=False)
            .select_related("rule", "rule__policy", "account")
        )
