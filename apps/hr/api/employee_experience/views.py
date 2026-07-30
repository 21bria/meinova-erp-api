from apps.framework.views.master import BaseMasterViewSet

from apps.hr.models import EmployeeExperience

from .serializers import EmployeeExperienceSerializer
from .services import EmployeeExperienceService


class EmployeeExperienceViewSet(
    BaseMasterViewSet,
):
    serializer_class = EmployeeExperienceSerializer
    service_class = EmployeeExperienceService

    search_fields = [
        "company_name",
        "position_name",
        "employment_type",
        "industry",
        "location",
        "reference_name",
        "reference_phone",
    ]

    filterset_fields = [
        "employee",
        "is_current",
        "is_verified",
        "is_active",
    ]

    ordering = [
        "-is_current",
        "-start_date",
        "company_name",
    ]

    def get_queryset(self):
        return (
            EmployeeExperience.objects
            .select_related(
                "employee",
            )
            .filter(is_deleted=False)
        )