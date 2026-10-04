from apps.administration.models import EmployeeDataSubject
from apps.hr.api.employee.visibility import EmployeeDataSubjectMixin
from apps.framework.views.master import BaseMasterViewSet

from apps.hr.models import EmployeeBankAccount
from .serializers import EmployeeBankAccountSerializer
from apps.hr.api.employee.scope import EMPLOYEE_CHILD_SCOPE


class EmployeeBankAccountViewSet(
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
    data_subject = EmployeeDataSubject.FIELD_BANK

    search_fields = [
        "employee__employee_number",
        "employee__first_name",
        "account_name",
        "account_number",
        "bank__name",
    ]

    serializer_class = EmployeeBankAccountSerializer

    filterset_fields = [
        "employee",
        "bank",
        "is_primary",
        "is_active",
    ]

    ordering = [
        "-is_primary",
        "bank__name",
        "account_number",
    ]

    def get_queryset(self):
        return (
            EmployeeBankAccount.objects
            .select_related(
                "employee",
                "bank",
                "currency",
            )
            .filter(is_deleted=False)
        )