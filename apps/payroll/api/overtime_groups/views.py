from apps.framework.views.master import BaseMasterViewSet

from .serializers import OvertimeGroupSerializer
from .services import OvertimeGroupService


class OvertimeGroupViewSet(BaseMasterViewSet):
    serializer_class = OvertimeGroupSerializer
    service_class = OvertimeGroupService

    framework_module = "payroll/overtime-groups"

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