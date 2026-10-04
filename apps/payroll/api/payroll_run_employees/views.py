from django.db.models import Prefetch

from apps.administration.models import EmployeeDataSubject
from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin
from apps.hr.api.employee.visibility import EmployeeDataSubjectMixin
from apps.payroll.models import PayrollRunComponent, PayrollRunEmployee
from apps.payroll.scoping import PAYROLL_RUN_EMPLOYEE_SCOPE
from apps.payroll.services import PayrollRunEmployeeService

from .schema import PAYROLL_RUN_EMPLOYEE_SCHEMA
from .serializers import PayrollRunEmployeeSerializer


class PayrollRunEmployeeViewSet(
    ServiceWriteMixin,
    EmployeeDataSubjectMixin,
    BaseMasterViewSet,
):
    """
    Hasil perhitungan per pegawai.

    Dua lapis penjagaan, dan keduanya memang harus ada:
    `data_scope` menjawab "baris milik siapa" lewat snapshot organisasi
    yang tersimpan di baris ini, `data_subject` menjawab "jenis data
    apa" — dan gaji adalah `FIELD_PAYROLL`, kelompok yang sama dengan
    tab Payroll di kartu pegawai. Menyandarkan keduanya pada satu lapis
    berarti kehilangan salah satunya begitu ada yang menghapus baris
    master policy.
    """

    # Petanya datang dari `apps.payroll.scoping`, bukan ditulis di sini.
    #
    # Endpoint lain membaca baris payroll di luar `filter_queryset()` —
    # `payroll-runs/<id>/summary/` menjumlahkannya langsung — dan dua
    # salinan peta yang harus tetap sepakat adalah cara paling pasti
    # membuat satu endpoint menyaring lebih longgar dari yang lain
    # tanpa ada yang menyadarinya.
    # Sensitif: baca ikut menuntut `view_<model>`. Lihat
    # `BaseMasterViewSet.require_view_permission`.
    require_view_permission = True

    data_scope = PAYROLL_RUN_EMPLOYEE_SCOPE

    data_subject = EmployeeDataSubject.FIELD_PAYROLL

    serializer_class = PayrollRunEmployeeSerializer
    service_class = PayrollRunEmployeeService

    framework_module = "payroll/payroll-run-employees"
    schema = PAYROLL_RUN_EMPLOYEE_SCHEMA

    # Baris ini tidak punya kolom `code`/`name`; bawaan base akan
    # membalas 500 begitu kotak pencarian diketik.
    search_fields = [
        "employee__employee_number",
        "employee__first_name",
        "employee__last_name",
        "run__document_number",
    ]

    filterset_fields = [
        "run",
        "employee",
        "company",
        "branch",
        "location",
        "department",
        "section",
        "status",
        "is_excluded",
    ]

    ordering = ["run", "employee__employee_number"]

    ordering_fields = [
        "employee__employee_number",
        "basic_salary",
        "gross_earning",
        "total_deduction",
        "tax_amount",
        "net_pay",
        "status",
    ]

    def get_queryset(self):
        return (
            PayrollRunEmployee.objects
            .filter(is_deleted=False)
            .select_related(
                "run",
                "run__period",
                "employee",
                "company",
                "branch",
                "location",
                "division",
                "department",
                "section",
                "position",
                "payroll_group",
                "salary_grade",
                "salary_level",
                "tax_status",
                "overtime_group",
                "allowance_template",
                "deduction_template",
                "payroll_policy",
                "currency",
            )
            .prefetch_related(
                Prefetch(
                    "components",
                    queryset=(
                        PayrollRunComponent.objects
                        .filter(is_deleted=False)
                        .order_by("component_type", "sequence", "code")
                    ),
                ),
            )
        )
