# views.py
from apps.framework.views.master import BaseMasterViewSet

from .serializers import PayrollGroupSerializer
from .services import PayrollGroupService


class PayrollGroupViewSet(BaseMasterViewSet):
    serializer_class = PayrollGroupSerializer
    service_class = PayrollGroupService

    framework_module = "payroll/payroll-groups"

    search_fields = [
        "code",
        "name",
        "description",
    ]

    filterset_fields = [
        "pay_frequency",
        "is_active",
    ]

    ordering_fields = [
        "code",
        "name",
        "pay_frequency",
        "is_active",
        "created_at",
    ]

    ordering = ["name"]