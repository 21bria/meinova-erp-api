from apps.framework.views.master import BaseMasterViewSet

from apps.hr.api.employee_education.serializers import (
    EmployeeEducationSerializer,
)
from apps.hr.api.employee_education.services import (
    EmployeeEducationService,
)
from apps.hr.models import EmployeeEducation
from apps.hr.api.employee.scope import EMPLOYEE_CHILD_SCOPE


class EmployeeEducationViewSet(
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