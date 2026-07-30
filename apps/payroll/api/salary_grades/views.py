from apps.framework.views.master import BaseMasterViewSet

from .serializers import SalaryGradeSerializer
from .services import SalaryGradeService


class SalaryGradeViewSet(BaseMasterViewSet):
    serializer_class = SalaryGradeSerializer
    service_class = SalaryGradeService

    framework_module = "payroll/salary-grades"

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