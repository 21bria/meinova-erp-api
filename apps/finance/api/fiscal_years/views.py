from django.db.models import Count, Q

from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated

from apps.core.responses.api import success_response
from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin

from apps.finance.models import FiscalYear
from apps.finance.api.permissions import FinanceActionPermission
from apps.finance.services import ADD_PERIOD_PERMISSION, FiscalYearService

from .schema import FISCAL_YEAR_SCHEMA
from .serializers import FiscalYearSerializer, GeneratePeriodsSerializer


class FiscalYearViewSet(ServiceWriteMixin, BaseMasterViewSet):
    serializer_class = FiscalYearSerializer
    service_class = FiscalYearService

    framework_module = "finance/fiscal-years"
    schema = FISCAL_YEAR_SCHEMA

    data_scope = {"company": "company"}

    # FIN-B1/B2. Aksi kustom ini mengubah kalender akuntansi; izinnya
    # ditagih service, dan dicerminkan di sini sebagai 403 awal.
    action_scope_permissions = {
        "generate_periods": ADD_PERIOD_PERMISSION,
    }

    permission_classes = [IsAuthenticated, FinanceActionPermission]

    search_fields = ["code", "name"]
    filterset_fields = ["company", "status", "is_current", "is_active"]
    ordering_fields = ["code", "start_date", "end_date", "status"]
    ordering = ["company_id", "-start_date"]

    def get_queryset(self):
        return (
            FiscalYear.objects
            .filter(is_deleted=False)
            .select_related("company")
            .annotate(
                period_total=Count(
                    "periods",
                    filter=Q(periods__is_deleted=False),
                ),
            )
        )

    @action(detail=True, methods=["post"], url_path="generate-periods")
    def generate_periods(self, request, pk=None):
        fiscal_year = self.get_object()

        payload = GeneratePeriodsSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        periods = FiscalYearService.generate_periods(
            fiscal_year=fiscal_year,
            count=payload.validated_data["count"],
            user=request.user,
        )

        return success_response(
            data={
                "created": len(periods),
                "periods": [
                    {
                        "id": period.pk,
                        "code": period.code,
                        "name": period.name,
                        "start_date": period.start_date,
                        "end_date": period.end_date,
                    }
                    for period in periods
                ],
            },
            message=f"{len(periods)} accounting periods created.",
        )
