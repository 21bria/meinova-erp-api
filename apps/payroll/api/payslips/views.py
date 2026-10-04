from rest_framework.decorators import action

from apps.administration.models import EmployeeDataSubject
from apps.core.responses.api import success_response
from apps.framework.views.master import BaseMasterViewSet
from apps.hr.api.employee.scope import EMPLOYEE_CHILD_SCOPE
from apps.hr.api.employee.visibility import EmployeeDataSubjectMixin
from apps.payroll.models import Payslip
from apps.payroll.services import PayslipService

from .schema import PAYSLIP_SCHEMA
from .serializers import PayslipSerializer


class PayslipViewSet(EmployeeDataSubjectMixin, BaseMasterViewSet):
    """
    Slip gaji, read-only.

    Metode tulisnya dimatikan lewat `http_method_names`, **bukan**
    dengan tidak mendaftarkan route-nya: `framework_schema_view` hanya
    menemukan turunan `BaseMasterViewSet`, dan viewset yang tidak
    ketemu berarti module-nya 404 di generator frontend.

    Cakupannya sama dengan sub-resource kartu pegawai lain, plus
    `own` — pegawai memang harus bisa membuka slipnya sendiri, dan
    itulah satu-satunya baris payroll yang boleh ia lihat.
    """

    http_method_names = ["get", "head", "options"]

    # Sensitif: baca ikut menuntut `view_<model>`. Lihat
    # `BaseMasterViewSet.require_view_permission`.
    require_view_permission = True

    data_scope = EMPLOYEE_CHILD_SCOPE

    data_subject = EmployeeDataSubject.FIELD_PAYROLL

    serializer_class = PayslipSerializer
    service_class = PayslipService

    framework_module = "payroll/payslips"
    schema = PAYSLIP_SCHEMA

    search_fields = [
        "document_number",
        "employee__employee_number",
        "employee__first_name",
        "employee__last_name",
        "period__code",
        "period__name",
    ]

    filterset_fields = [
        "period",
        "run",
        "employee",
        "company",
        "branch",
        "location",
        "department",
        "section",
        "status",
    ]

    ordering = ["-period__start_date", "employee__employee_number"]

    ordering_fields = [
        "document_number", "issue_date", "gross_earning",
        "total_deduction", "net_pay", "status",
    ]

    def get_queryset(self):
        return PayslipService.get_queryset()

    @action(detail=True, methods=["get"], url_path="detail")
    def slip_detail(self, request, pk=None):
        """
        Isi slip apa adanya dari snapshot yang dibekukan.

        Dilayani terpisah dari `retrieve` supaya halaman cetak tidak
        perlu ikut membawa seluruh kolom tabel — dan supaya jelas bahwa
        yang dicetak adalah snapshot, bukan hasil hitung ulang.
        """
        instance = self.get_object()

        return success_response(
            data={
                "document_number": instance.document_number,
                "issue_date": instance.issue_date,
                "status": instance.status,
                "payslip": instance.snapshot or {},
            },
            message="Detail payslip.",
        )
