from apps.administration.models import EmployeeDataSubject
from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin
from apps.hr.api.employee.scope import EMPLOYEE_CHILD_SCOPE
from apps.hr.api.employee.visibility import EmployeeDataSubjectMixin
from apps.payroll.models import PayrollInput
from apps.payroll.services import PayrollInputService

from .schema import PAYROLL_INPUT_SCHEMA
from .serializers import PayrollInputSerializer


class PayrollInputViewSet(
    ServiceWriteMixin,
    EmployeeDataSubjectMixin,
    BaseMasterViewSet,
):
    """
    Nilai transaksi payroll per periode.

    Barisnya menunjuk satu pegawai, jadi cakupannya persis cakupan
    Employee digeser satu relasi — peta yang sama dengan seluruh
    sub-resource kartu pegawai, dipakai ulang dari satu konstanta supaya
    tidak ada salinan yang menyimpang.
    """

    # Sensitif: baca ikut menuntut `view_<model>`. Lihat
    # `BaseMasterViewSet.require_view_permission`.
    require_view_permission = True

    data_scope = EMPLOYEE_CHILD_SCOPE

    data_subject = EmployeeDataSubject.FIELD_PAYROLL

    serializer_class = PayrollInputSerializer
    service_class = PayrollInputService

    framework_module = "payroll/payroll-inputs"
    schema = PAYROLL_INPUT_SCHEMA

    search_fields = [
        "code",
        "name",
        "reference",
        "employee__employee_number",
        "employee__first_name",
        "employee__last_name",
        "period__code",
        "period__name",
    ]

    filterset_fields = [
        "period",
        "employee",
        "input_type",
        "component_type",
        "allowance_line",
        "deduction_line",
        "status",
    ]

    ordering = ["-period__start_date", "employee__employee_number", "code"]

    ordering_fields = [
        "code", "name", "amount", "quantity", "status", "created_at",
    ]

    def get_queryset(self):
        return (
            PayrollInput.objects
            .filter(is_deleted=False)
            .select_related(
                "period",
                "employee",
                "allowance_line",
                "allowance_line__template",
                "deduction_line",
                "deduction_line__template",
            )
        )
