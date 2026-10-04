from rest_framework.parsers import (
    FormParser,
    JSONParser,
    MultiPartParser,
)

from apps.administration.models import EmployeeDataSubject
from apps.hr.api.employee.visibility import EmployeeDataSubjectMixin
from apps.framework.views.master import BaseMasterViewSet
from apps.hr.models import EmployeeDocument

from .serializers import EmployeeDocumentSerializer
from .services import EmployeeDocumentService
from apps.hr.api.employee.scope import EMPLOYEE_CHILD_SCOPE


class EmployeeDocumentViewSet(
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
    data_subject = EmployeeDataSubject.FIELD_DOCUMENT

    serializer_class = EmployeeDocumentSerializer
    service_class = EmployeeDocumentService

    parser_classes = [
        MultiPartParser,
        FormParser,
        JSONParser,
    ]

    search_fields = [
        "employee__employee_number",
        "employee__first_name",
        "employee__last_name",
        "document_type__name",
        "document_name",
        "document_number",
        "issuing_authority",
    ]

    filterset_fields = [
        "employee",
        "document_type",
        "is_required",
        "is_verified",
        "is_active",
    ]

    ordering_fields = [
        "document_type__sort_order",
        "document_type__name",
        "document_name",
        "document_number",
        "issue_date",
        "expiry_date",
        "issuing_authority",
        "is_required",
        "is_verified",
        "is_active",
        "created_at",
    ]

    ordering = [
        "document_type__sort_order",
        "document_name",
    ]

    def get_queryset(self):
        return (
            EmployeeDocument.objects
            .select_related(
                "employee",
                "document_type",
                "uploaded_file",   # tambahkan
            )
            .filter(is_deleted=False)
        )