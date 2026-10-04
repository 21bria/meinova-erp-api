from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin
from apps.payroll.services import OvertimeGroupTierService

from .schema import OVERTIME_GROUP_TIER_SCHEMA
from .serializers import OvertimeGroupTierSerializer


class OvertimeGroupTierViewSet(ServiceWriteMixin, BaseMasterViewSet):
    """
    Tingkat pengali di dalam Overtime Group.

    Tidak ada konfigurasi lembur per pegawai: pegawai memilih kelompok
    lewat `PayrollAssignment.overtime_group`, dan kelompok itu yang
    membawa tingkatnya.
    """

    serializer_class = OvertimeGroupTierSerializer
    service_class = OvertimeGroupTierService

    framework_module = "payroll/overtime-group-tiers"
    schema = OVERTIME_GROUP_TIER_SCHEMA

    search_fields = ["group__code", "group__name", "description"]

    filterset_fields = ["group", "is_active"]

    ordering = ["group__code", "sequence"]

    ordering_fields = [
        "group__code", "sequence", "hour_from", "multiplier",
        "is_active", "created_at",
    ]

    # Base mencari `service_class.list()`; service payroll memakai
    # `get_queryset()` seperti `BaseMasterService` lain.
    def get_queryset(self):
        return OvertimeGroupTierService.get_queryset()
