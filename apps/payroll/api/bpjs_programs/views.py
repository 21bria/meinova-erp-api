from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin
from apps.payroll.services import BpjsProgramService

from .schema import BPJS_PROGRAM_SCHEMA
from .serializers import BpjsProgramSerializer


class BpjsProgramViewSet(ServiceWriteMixin, BaseMasterViewSet):
    """Identitas program BPJS — tanpa angka."""

    serializer_class = BpjsProgramSerializer
    service_class = BpjsProgramService

    framework_module = "payroll/bpjs-programs"
    schema = BPJS_PROGRAM_SCHEMA

    search_fields = ["code", "name", "description"]

    filterset_fields = ["is_active"]

    ordering = ["sequence", "code"]

    ordering_fields = ["code", "name", "sequence", "is_active", "created_at"]

    def get_queryset(self):
        return BpjsProgramService.get_queryset()
