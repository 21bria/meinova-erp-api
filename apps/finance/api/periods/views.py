from django.db.models import Count, Q

from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated

from apps.core.responses.api import success_response
from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin

from apps.finance.models import AccountingPeriod, JournalStatus
from apps.finance.api.permissions import FinanceActionPermission
from apps.finance.services import CHANGE_PERIOD_PERMISSION, AccountingPeriodService

from .schema import ACCOUNTING_PERIOD_SCHEMA
from .serializers import (
    AccountingPeriodSerializer,
    PeriodStatusChangeSerializer,
)


class AccountingPeriodViewSet(ServiceWriteMixin, BaseMasterViewSet):
    serializer_class = AccountingPeriodSerializer
    service_class = AccountingPeriodService

    framework_module = "finance/accounting-periods"
    schema = ACCOUNTING_PERIOD_SCHEMA

    # Periode tidak menyimpan company sendiri — ia milik tahun bukunya.
    # Petanya karena itu menembus satu relasi; menyalin kolomnya ke sini
    # akan membuat dua sumber untuk satu fakta yang bisa berselisih.
    data_scope = {"company": "fiscal_year__company"}

    # FIN-B1/B2. Aksi kustom ini mengubah kalender akuntansi; izinnya
    # ditagih service, dan dicerminkan di sini sebagai 403 awal.
    action_scope_permissions = {
        "change_status": CHANGE_PERIOD_PERMISSION,
    }

    permission_classes = [IsAuthenticated, FinanceActionPermission]

    search_fields = ["code", "name", "fiscal_year__code"]
    filterset_fields = ["fiscal_year", "status", "is_active"]
    ordering_fields = ["period_number", "start_date", "end_date", "status"]
    ordering = ["fiscal_year__start_date", "period_number"]

    def get_queryset(self):
        return (
            AccountingPeriod.objects
            .filter(is_deleted=False)
            .select_related(
                "fiscal_year",
                "fiscal_year__company",
                "closed_by",
                "reopened_by",
            )
            .annotate(
                posted_journal_count=Count(
                    "journals",
                    filter=Q(
                        journals__is_deleted=False,
                        journals__status=JournalStatus.POSTED,
                    ),
                ),
            )
        )

    @action(detail=True, methods=["post"], url_path="change-status")
    def change_status(self, request, pk=None):
        """
        Satu endpoint untuk keempat tombol.

        Bukan empat endpoint: aturan perpindahannya sudah tinggal di
        satu peta di service, dan empat rute yang masing-masing
        memanggil peta yang sama cuma menambah empat tempat yang bisa
        lupa memanggilnya.
        """
        period = self.get_object()

        payload = PeriodStatusChangeSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        updated = AccountingPeriodService.change_status(
            period=period,
            status=payload.validated_data["status"],
            user=request.user,
            reason=payload.validated_data.get("reason", ""),
        )

        return success_response(
            data=AccountingPeriodSerializer(updated).data,
            message=f"Period {updated.code} is now {updated.get_status_display()}.",
        )
