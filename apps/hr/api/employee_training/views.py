from apps.framework.views.master import BaseMasterViewSet

from apps.hr.models import EmployeeTraining

from .serializers import EmployeeTrainingSerializer
from .services import EmployeeTrainingService


class EmployeeTrainingViewSet(
    BaseMasterViewSet,
):
    serializer_class = EmployeeTrainingSerializer
    service_class = EmployeeTrainingService

    search_fields = [
        "training_name",
        "certificate_number",
        "notes",
    ]

    filterset_fields = [
        "employee",
        "training_category",
        "provider",
        "is_mandatory",
        "is_completed",
        "is_active",
    ]

    ordering = [
        "-start_date",
        "training_name",
    ]

    def get_queryset(self):
        return (
            EmployeeTraining.objects
            .select_related(
                "employee",
                "training_category",
                "provider",
            )
            .filter(is_deleted=False)
        )