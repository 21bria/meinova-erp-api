# apps/hr/api/employee_document/views.py

from apps.framework.views.master import BaseMasterViewSet

from apps.hr.models import EmployeeDocument

from .serializers import EmployeeDocumentSerializer
from .services import EmployeeDocumentService


class EmployeeDocumentViewSet(
    BaseMasterViewSet,
):
    serializer_class = EmployeeDocumentSerializer
    service_class = EmployeeDocumentService

    search_fields = [
        "document_name",
        "document_number",
        "issuing_authority",
    ]

    filterset_fields = [
        "employee",
        "document_type",
        "is_required",
        "is_verified",
        "is_active",
    ]

    ordering = [
        "document_type__sort_order",
        "document_name",
    ]

    def get_queryset(self):
        return (
            EmployeeDocument.objects
            .select_related(
                "employee",
                "document_type",
            )
            .filter(is_deleted=False)
        )