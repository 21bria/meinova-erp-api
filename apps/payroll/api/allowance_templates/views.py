from apps.framework.views.master import BaseMasterViewSet

from .serializers import AllowanceTemplateSerializer
from .services import AllowanceTemplateService


class AllowanceTemplateViewSet(BaseMasterViewSet):
    serializer_class = AllowanceTemplateSerializer
    service_class = AllowanceTemplateService

    framework_module = "payroll/allowance-templates"

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