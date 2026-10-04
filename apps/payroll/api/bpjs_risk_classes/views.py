from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin
from apps.payroll.services import BpjsRiskClassService

from .schema import BPJS_RISK_CLASS_SCHEMA
from .serializers import BpjsRiskClassSerializer


class BpjsRiskClassViewSet(ServiceWriteMixin, BaseMasterViewSet):
    """Kelas risiko kerja — identitas saja, tanpa tarif."""

    serializer_class = BpjsRiskClassSerializer
    service_class = BpjsRiskClassService

    framework_module = "payroll/bpjs-risk-classes"
    schema = BPJS_RISK_CLASS_SCHEMA

    search_fields = ["code", "name", "description"]

    filterset_fields = ["is_active"]

    ordering = ["sequence", "code"]

    ordering_fields = ["code", "name", "sequence", "is_active", "created_at"]

    def get_queryset(self):
        return BpjsRiskClassService.get_queryset()
