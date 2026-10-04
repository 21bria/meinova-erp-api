from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin
from apps.payroll.services import DeductionTemplateLineService

from .schema import DEDUCTION_TEMPLATE_LINE_SCHEMA
from .serializers import DeductionTemplateLineSerializer


class DeductionTemplateLineViewSet(ServiceWriteMixin, BaseMasterViewSet):
    """
    Komponen di dalam Deduction Template — termasuk BPJS dan PPh21.

    Kembaran layar Allowance Components, dan sengaja dibiarkan kembar:
    keduanya mengonfigurasi hal yang sama di dua sisi neraca gaji.
    """

    serializer_class = DeductionTemplateLineSerializer
    service_class = DeductionTemplateLineService

    framework_module = "payroll/deduction-template-lines"
    schema = DEDUCTION_TEMPLATE_LINE_SCHEMA

    search_fields = ["code", "name", "template__code", "template__name"]

    filterset_fields = [
        "template",
        "basis",
        "reduces_taxable",
        "is_employer_cost",
        "is_active",
    ]

    ordering = ["template__code", "sequence", "code"]

    ordering_fields = [
        "template__code", "sequence", "code", "name",
        "basis", "amount", "rate", "is_active", "created_at",
    ]

    def get_queryset(self):
        return DeductionTemplateLineService.get_queryset()
