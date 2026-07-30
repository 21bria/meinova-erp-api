from apps.framework.views.master import BaseMasterViewSet

from apps.hr.models import EmployeeMedicalEvent

from .serializers import EmployeeMedicalEventSerializer
from .services import EmployeeMedicalEventService


class EmployeeMedicalEventViewSet(
    BaseMasterViewSet,
):
    serializer_class = EmployeeMedicalEventSerializer
    service_class = EmployeeMedicalEventService

    search_fields = [
        "provider_name",
        "doctor_name",
        "result",
        "restriction_notes",
        "notes",
    ]

    filterset_fields = [
        "employee",
        "medical_type",
        "fitness_status",
        "is_confidential",
        "is_verified",
        "is_active",
    ]

    ordering = [
        "-event_date",
        "-created_at",
    ]

    def get_queryset(self):
        return (
            EmployeeMedicalEvent.objects
            .select_related(
                "employee",
            )
            .filter(is_deleted=False)
        )