from apps.framework.views.master import BaseMasterViewSet

from apps.hr.models import EmployeeExperience

from .serializers import EmployeeExperienceSerializer
from .services import EmployeeExperienceService
from apps.hr.api.employee.scope import EMPLOYEE_CHILD_SCOPE


class EmployeeExperienceViewSet(
    BaseMasterViewSet,
):
    # Penyaringan data per baris (kewenangan `RoleAssignment`).
    #
    # Lapisan yang menjawab "baris milik siapa", terpisah dari
    # `data_subject` yang menjawab "jenis data apa". Tanpa ini,
    # setiap pengguna terautentikasi membaca tabel ini utuh — baca
    # memang dibiarkan terbuka `ModelPermission`, jadi cakupan baris
    # adalah satu-satunya yang menutupnya.
    data_scope = EMPLOYEE_CHILD_SCOPE

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