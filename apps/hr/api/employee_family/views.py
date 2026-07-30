from apps.framework.views.master import BaseMasterViewSet

from apps.hr.api.employee_family.serializers import (
    EmployeeFamilySerializer,
)
from apps.hr.api.employee_family.services import (
    EmployeeFamilyService,
)
from apps.hr.models import EmployeeFamily


class EmployeeFamilyViewSet(
    BaseMasterViewSet,
):
    serializer_class = EmployeeFamilySerializer
    service_class = EmployeeFamilyService

    search_fields = [
        "full_name",
        "occupation",
        "phone",
    ]

    filterset_fields = [
        "employee",
        "relationship",
        "gender",
        "is_dependent",
        "is_emergency_contact",
        "is_active",
    ]

    ordering = [
        "relationship__sort_order",
        "full_name",
    ]

    def get_queryset(self):
        return (
            EmployeeFamily.objects
            .select_related(
                "employee",
                "relationship",
                "gender",
            )
            .filter(is_deleted=False)
        )