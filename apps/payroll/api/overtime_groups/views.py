from apps.framework.views.master import BaseMasterViewSet

from .schema import OVERTIME_GROUP_SCHEMA
from .serializers import OvertimeGroupSerializer
from .services import OvertimeGroupService


class OvertimeGroupViewSet(BaseMasterViewSet):
    serializer_class = OvertimeGroupSerializer
    service_class = OvertimeGroupService

    framework_module = "payroll/overtime-groups"
    schema = OVERTIME_GROUP_SCHEMA

    search_fields = [
        "code",
        "name",
        "description",
    ]

    filterset_fields = [
        "is_active",
        "tier_basis",
    ]

    ordering_fields = [
        "code",
        "name",
        "is_active",
        "created_at",
    ]

    ordering = ["code"]