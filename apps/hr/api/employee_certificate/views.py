from apps.framework.views.master import BaseMasterViewSet

from apps.hr.models import EmployeeCertificate

from .serializers import EmployeeCertificateSerializer
from .services import EmployeeCertificateService
from apps.hr.api.employee.scope import EMPLOYEE_CHILD_SCOPE


class EmployeeCertificateViewSet(
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

    serializer_class = EmployeeCertificateSerializer
    service_class = EmployeeCertificateService

    search_fields = [
        "certificate_name",
        "certificate_number",
        "issuing_organization",
        "credential_id",
    ]

    filterset_fields = [
        "employee",
        "certificate_type",
        "is_lifetime",
        "is_verified",
        "is_active",
    ]

    ordering = [
        "-issue_date",
        "certificate_name",
    ]

    def get_queryset(self):
        return (
            EmployeeCertificate.objects
            .select_related(
                "employee",
                "certificate_type",
                "uploaded_file", 
            )
            .filter(
                is_deleted=False,
            )
        )