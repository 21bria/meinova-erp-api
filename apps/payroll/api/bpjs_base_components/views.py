from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin
from apps.payroll.services import BpjsBaseComponentService

from .schema import BPJS_BASE_COMPONENT_SCHEMA
from .serializers import BpjsBaseComponentSerializer


class BpjsBaseComponentViewSet(ServiceWriteMixin, BaseMasterViewSet):
    """Komponen tunjangan yang ikut jadi dasar iuran."""

    serializer_class = BpjsBaseComponentSerializer
    service_class = BpjsBaseComponentService

    framework_module = "payroll/bpjs-base-components"
    schema = BPJS_BASE_COMPONENT_SCHEMA

    search_fields = ["allowance_code", "definition__code", "definition__name"]

    filterset_fields = ["definition", "is_active"]

    ordering = ["definition__code", "sequence", "allowance_code"]

    ordering_fields = ["allowance_code", "sequence", "is_active", "created_at"]

    def get_queryset(self):
        return BpjsBaseComponentService.get_queryset()
