from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin
from apps.payroll.services import BpjsRuleService

from .schema import BPJS_RULE_SCHEMA
from .serializers import BpjsRuleSerializer


class BpjsRuleViewSet(ServiceWriteMixin, BaseMasterViewSet):
    """
    Tarif BPJS yang berlaku pada satu rentang tanggal.

    Cakupannya perusahaan atau seluruh tenant; resolusinya
    `COMPANY -> tenant`, dan override perusahaan mengganti aturan
    secara utuh.
    """

    serializer_class = BpjsRuleSerializer
    service_class = BpjsRuleService

    framework_module = "payroll/bpjs-rules"
    schema = BPJS_RULE_SCHEMA

    search_fields = ["program__code", "program__name", "description"]

    filterset_fields = [
        "program", "company", "base_definition", "reduces_taxable",
        "is_active",
    ]

    ordering = ["program__sequence", "-effective_from"]

    ordering_fields = [
        "effective_from", "effective_to", "employee_rate", "employer_rate",
        "is_active", "created_at",
    ]

    def get_queryset(self):
        return BpjsRuleService.get_queryset()
