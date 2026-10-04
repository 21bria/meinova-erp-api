from rest_framework.decorators import action

from apps.core.responses.api import success_response
from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin

from apps.finance.models import AccountMapping
from apps.finance.services import AccountMappingService

from .schema import ACCOUNT_MAPPING_SCHEMA
from .serializers import AccountMappingSerializer


class AccountMappingViewSet(ServiceWriteMixin, BaseMasterViewSet):
    serializer_class = AccountMappingSerializer
    service_class = AccountMappingService

    framework_module = "finance/account-mappings"
    schema = ACCOUNT_MAPPING_SCHEMA

    # Baris bercompany kosong berlaku untuk semua perusahaan, jadi
    # `allow_null` harus menyala — kalau tidak, justru baris yang paling
    # umum yang hilang dari layar setiap admin yang bercakupan. Sama
    # alasannya dengan master kalender.
    data_scope = {"company": "company"}

    search_fields = ["code", "name", "mapping_key", "event_type"]
    filterset_fields = [
        "mapping_key",
        "company",
        "event_type",
        "account",
        "location",
        "department",
        "cost_center",
        "is_active",
    ]
    ordering_fields = ["mapping_key", "specificity", "code"]
    ordering = ["mapping_key", "-specificity", "code"]

    def get_queryset(self):
        return (
            AccountMapping.objects
            .filter(is_deleted=False)
            .select_related(
                "company", "account", "location", "department", "cost_center",
            )
        )

    def filter_queryset(self, queryset):
        """
        Menimpa hanya untuk mengoper `allow_null=True`.

        Pola yang sama dengan `CalendarScopedViewSetMixin`: kolom
        company yang kosong di master ini berarti "berlaku untuk semua",
        bukan "belum diisi", dan bawaan `DATA_SCOPE_INCLUDE_NULL=False`
        akan menyembunyikannya justru dari admin yang bercakupan.
        """
        from rest_framework.viewsets import ModelViewSet

        from apps.accounts.scoping import DataScopeService

        queryset = ModelViewSet.filter_queryset(self, queryset)

        return DataScopeService.filter(
            queryset,
            self.data_scope,
            getattr(getattr(self, "request", None), "user", None),
            allow_null=True,
        )

    @action(detail=False, methods=["get"])
    def conflicts(self, request):
        """
        Pemetaan yang berpotensi ambigu.

        Dilaporkan, **tidak** ditolak: konfigurasi ambigu untuk
        kombinasi yang tidak pernah terjadi tidak merugikan siapa pun,
        dan menolak simpanan karenanya akan menghalangi orang menyusun
        konfigurasinya secara bertahap. Yang menolak sungguhan
        `AccountMappingService.resolve()` — saat baris itu benar-benar
        dipakai menerbitkan jurnal.
        """
        company_id = request.query_params.get("company_id")

        conflicts = AccountMappingService.detect_conflicts(
            company_id=int(company_id) if company_id else None,
        )

        actionable = [row for row in conflicts if not row["same_account"]]

        return success_response(
            data={
                "conflicts": conflicts,
                "count": len(conflicts),
                "actionable": len(actionable),
            },
            message=(
                f"{len(actionable)} ambiguous mapping(s) need attention."
                if actionable
                else "No ambiguous mappings."
            ),
        )
