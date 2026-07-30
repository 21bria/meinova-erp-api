from apps.framework.views.master import BaseMasterViewSet

from apps.hr.api.employee_education.serializers import (
    EmployeeEducationSerializer,
)
from apps.hr.api.employee_education.services import (
    EmployeeEducationService,
)
from apps.hr.models import EmployeeEducation


class EmployeeEducationViewSet(
    BaseMasterViewSet,
):
    serializer_class = EmployeeEducationSerializer
    service_class = EmployeeEducationService

    search_fields = [
        "institution_name",
        "city",
        "country",
        "certificate_number",
    ]

    filterset_fields = [
        "employee",
        "education",
        "degree",
        "study_field",
        "graduation_year",
        "is_highest_education",
        "is_active",
    ]

    ordering = [
        "-is_highest_education",
        "-graduation_year",
        "institution_name",
    ]

    def get_queryset(self):
        return (
            EmployeeEducation.objects
            .select_related(
                "employee",
                "education",
                "degree",
                "study_field",
            )
            .filter(is_deleted=False)
        )