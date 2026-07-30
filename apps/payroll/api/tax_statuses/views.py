from apps.framework.views.master import BaseMasterViewSet

from .serializers import TaxStatusSerializer
from .services import TaxStatusService


class TaxStatusViewSet(BaseMasterViewSet):
    serializer_class = TaxStatusSerializer
    service_class = TaxStatusService

    framework_module = "payroll/tax-statuses"

    search_fields = [
        "code",
        "name",
        "description",
    ]

    filterset_fields = [
        "is_active",
    ]

    ordering_fields = [
        "code",
        "name",
        "is_active",
        "created_at",
    ]

    ordering = ["code"]