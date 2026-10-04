from apps.administration.models import EmployeeDataSubject
from apps.hr.api.employee.visibility import EmployeeDataSubjectMixin
from apps.framework.views.master import BaseMasterViewSet

from apps.hr.api.employee_family.serializers import (
    EmployeeFamilySerializer,
)
from apps.hr.api.employee_family.services import (
    EmployeeFamilyService,
)
from apps.hr.models import EmployeeFamily
from apps.hr.api.employee.scope import EMPLOYEE_CHILD_SCOPE


class EmployeeFamilyViewSet(
    EmployeeDataSubjectMixin,
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

    # Kelompok `EmployeeDataPolicy` yang mengatur resource ini.
    # Tanpa ini tabnya tetap terbaca lewat endpoint-nya sendiri,
    # dan itu justru URL yang dipakai tab-nya di kartu pegawai.
    data_subject = EmployeeDataSubject.FIELD_FAMILY

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