from django.db.models import Prefetch

from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin
from apps.payroll.models import PayrollPeriod, PayrollRun
from apps.payroll.services import PayrollPeriodService

from .schema import PAYROLL_PERIOD_SCHEMA
from .serializers import PayrollPeriodSerializer


class PayrollPeriodViewSet(ServiceWriteMixin, BaseMasterViewSet):
    """
    Periode payroll.

    Data payroll termasuk data sensitif, jadi cakupan baris dipasang
    sejak layar ini: pengguna yang dicakup ke satu company tidak boleh
    melihat periode perusahaan lain, apalagi total gajinya.
    """

    data_scope = {"company": "company"}

    serializer_class = PayrollPeriodSerializer
    service_class = PayrollPeriodService

    framework_module = "payroll/payroll-periods"
    schema = PAYROLL_PERIOD_SCHEMA

    search_fields = ["code", "name", "company__name", "payroll_group__name"]

    filterset_fields = [
        "company", "payroll_group", "status",
        "start_date", "end_date",
    ]

    ordering = ["-start_date", "code"]

    ordering_fields = [
        "code", "name", "start_date", "end_date",
        "payment_date", "status", "created_at",
    ]

    def get_queryset(self):
        return (
            PayrollPeriod.objects
            .filter(is_deleted=False)
            .select_related("company", "payroll_group")
            .prefetch_related(
                Prefetch(
                    "runs",
                    queryset=PayrollRun.objects.filter(is_deleted=False),
                ),
            )
        )
