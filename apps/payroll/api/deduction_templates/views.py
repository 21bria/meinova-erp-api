from apps.framework.views.master import BaseMasterViewSet

from .serializers import DeductionTemplateSerializer
from .services import DeductionTemplateService


class DeductionTemplateViewSet(BaseMasterViewSet):
    serializer_class = DeductionTemplateSerializer
    service_class = DeductionTemplateService

    framework_module = "payroll/deduction-templates"

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