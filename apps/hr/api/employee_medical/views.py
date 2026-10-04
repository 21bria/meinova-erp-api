from apps.administration.models import EmployeeDataSubject
from apps.hr.api.employee.visibility import EmployeeDataSubjectMixin
from apps.framework.views.master import BaseMasterViewSet

from apps.hr.models import EmployeeMedicalEvent

from .serializers import EmployeeMedicalEventSerializer
from .services import EmployeeMedicalEventService
from apps.hr.api.employee.scope import EMPLOYEE_CHILD_SCOPE


class EmployeeMedicalEventViewSet(
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
    # Sensitif: baca ikut menuntut `view_<model>`. Lihat
    # `BaseMasterViewSet.require_view_permission`.
    require_view_permission = True

    data_scope = EMPLOYEE_CHILD_SCOPE

    # Kelompok `EmployeeDataPolicy` yang mengatur resource ini.
    # Tanpa ini tabnya tetap terbaca lewat endpoint-nya sendiri,
    # dan itu justru URL yang dipakai tab-nya di kartu pegawai.
    data_subject = EmployeeDataSubject.FIELD_MEDICAL

    serializer_class = EmployeeMedicalEventSerializer
    service_class = EmployeeMedicalEventService

    search_fields = [
        "medical_type",
        "fitness_status",
    ]

    filterset_fields = [
        "employee",
        "medical_type",
        "fitness_status",
        "is_confidential",
        "is_verified",
        "is_active",
    ]

    ordering_fields = [
        "event_date",
        "created_at",
        "provider_name",
        "doctor_name",
        "medical_type__name",
        "fitness_status__name",
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
                "uploaded_file"
            )
            .filter(is_deleted=False)
        )