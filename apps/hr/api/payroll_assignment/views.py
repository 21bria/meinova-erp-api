from apps.administration.models import EmployeeDataSubject
from apps.hr.api.employee.visibility import EmployeeDataSubjectMixin
from apps.framework.views.master import BaseMasterViewSet
from apps.hr.models import PayrollAssignment

from .serializers import PayrollAssignmentSerializer
from .services import PayrollAssignmentService
from apps.hr.api.employee.scope import EMPLOYEE_CHILD_SCOPE


class PayrollAssignmentViewSet(
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
    data_subject = EmployeeDataSubject.FIELD_PAYROLL

    serializer_class = PayrollAssignmentSerializer
    service_class = PayrollAssignmentService

    search_fields = [
        # Employee
        "employee__employee_number",
        "employee__first_name",
        "employee__last_name",

        # Payroll
        "payroll_group__name",
        "salary_grade__name",
        "salary_level__name",

        # Currency
        "currency__name",
        "currency__code",

        # Payment
        "payment_method",

        # Optional
        "tax_number_payroll",
        "bpjs_kesehatan_number",
        "bpjs_ketenagakerjaan_number",
    ]

    filterset_fields = [
        "employee",
        "payroll_group",
        "salary_grade",
        "salary_level",
        "currency",
        "tax_status",
        "overtime_eligible",
        "overtime_group",
        "payroll_policy",
        "is_current",
    ]

    ordering = [
        "-is_current",
        "-effective_from",
    ]

    def get_queryset(self):
        return (
            PayrollAssignment.objects
            .select_related(
                "employee",
                "payroll_group",
                "salary_grade",
                "salary_level",
                "currency",
                "tax_status",
                "overtime_group",
                "allowance_template",
                "deduction_template",
                "payroll_policy",
            )
            .filter(is_deleted=False)
        )