from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin
from apps.payroll.services import BpjsBaseDefinitionService

from .schema import BPJS_BASE_DEFINITION_SCHEMA
from .serializers import BpjsBaseDefinitionSerializer


class BpjsBaseDefinitionViewSet(ServiceWriteMixin, BaseMasterViewSet):
    """Komposisi dasar iuran, bervariasi versi dan terkunci sesudah dipakai."""

    serializer_class = BpjsBaseDefinitionSerializer
    service_class = BpjsBaseDefinitionService

    framework_module = "payroll/bpjs-base-definitions"
    schema = BPJS_BASE_DEFINITION_SCHEMA

    search_fields = ["code", "name", "description"]

    filterset_fields = ["include_basic", "is_active"]

    ordering = ["code", "-version"]

    ordering_fields = ["code", "version", "name", "is_active", "created_at"]

    def get_queryset(self):
        return BpjsBaseDefinitionService.get_queryset().prefetch_related(
            "components",
        )
