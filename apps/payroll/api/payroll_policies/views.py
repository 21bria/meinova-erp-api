from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin
from apps.payroll.services import PayrollPolicyService

from .schema import PAYROLL_POLICY_SCHEMA
from .serializers import PayrollPolicySerializer


class PayrollPolicyViewSet(ServiceWriteMixin, BaseMasterViewSet):
    """
    Kebijakan perhitungan untuk sekelompok pegawai dalam satu
    perusahaan.

    Tidak ada konfigurasi per pegawai: pegawai memilih kebijakan lewat
    `PayrollAssignment.payroll_policy`, dan assignment itulah yang
    effective-dated.
    """

    serializer_class = PayrollPolicySerializer
    service_class = PayrollPolicyService

    framework_module = "payroll/payroll-policies"
    schema = PAYROLL_POLICY_SCHEMA

    search_fields = ["code", "name", "description", "company__name"]

    filterset_fields = ["company", "pay_basis", "is_active"]

    ordering = ["company__name", "code"]

    ordering_fields = [
        "code", "name", "pay_basis", "is_active", "created_at",
    ]

    # Base mencari `service_class.list()`; service payroll memakai
    # `get_queryset()` seperti `BaseMasterService` lain.
    def get_queryset(self):
        return PayrollPolicyService.get_queryset()
