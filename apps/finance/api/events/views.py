from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated

from apps.core.responses.api import success_response
from apps.framework.views.master import BaseMasterViewSet

from apps.finance.api.permissions import FinanceActionPermission
from apps.finance.models import AccountingEvent
from apps.finance.services import (
    RETRY_PERMISSION,
    AccountingEventProcessor,
)

from .schema import ACCOUNTING_EVENT_SCHEMA
from .serializers import AccountingEventSerializer


class AccountingEventViewSet(BaseMasterViewSet):
    """
    Pemantauan kejadian akuntansi.

    Baca saja plus satu aksi. `http_method_names` dibatasi, bukan
    sekadar `ui.create=False` di schema: yang kedua cuma menyembunyikan
    tombol, dan endpoint-nya tetap menerima POST yang diketik tangan.
    """

    serializer_class = AccountingEventSerializer

    framework_module = "finance/accounting-events"
    schema = ACCOUNTING_EVENT_SCHEMA

    http_method_names = ["get", "post", "head", "options"]

    data_scope = {"company": "company"}

    # `retry/` bisa menerbitkan — dan untuk kebijakan `auto_post=True`,
    # memosting — jurnal, jadi cakupan barisnya dihitung dari izin yang
    # mengotorisasi tindakan itu, bukan dari izin baca. Pola yang sama
    # dengan `finalize` di Payroll Run dan `record` di Cuti.
    #
    # Penolakannya sendiri tetap di service
    # (`AccountingEventProcessor.assert_may_retry`): `ModelPermission`
    # tidak menjaga `@action` kustom, dan jalur lain yang menyusul tidak
    # lewat viewset sama sekali.
    action_scope_permissions = {
        "retry": RETRY_PERMISSION,
    }

    permission_classes = [IsAuthenticated, FinanceActionPermission]

    search_fields = [
        "event_type",
        "source_id",
        "source_reference",
        "idempotency_key",
    ]

    filterset_fields = [
        "company",
        "event_type",
        "status",
        "source_module",
        "source_type",
        "event_date",
    ]

    ordering_fields = ["event_date", "event_type", "status", "created_at"]
    ordering = ["-event_date", "-id"]

    def get_queryset(self):
        return (
            AccountingEvent.objects
            .filter(is_deleted=False)
            .select_related("company", "generated_journal", "applied_policy")
        )

    # `create` dimatikan lewat `http_method_names`? Tidak — POST tetap
    # dibutuhkan aksi `retry/`. Jadi dimatikan di sini, satu per satu.
    def create(self, request, *args, **kwargs):
        from rest_framework import status
        from rest_framework.response import Response

        return Response(
            {
                "detail": (
                    "Kejadian akuntansi dicatat modul sumbernya lewat "
                    "AccountingEventProcessor.record(), bukan lewat API "
                    "ini."
                ),
            },
            status=status.HTTP_405_METHOD_NOT_ALLOWED,
        )

    @action(detail=True, methods=["post"])
    def retry(self, request, pk=None):
        event = AccountingEventProcessor.retry(
            event=self.get_object(),
            user=request.user,
        )

        return success_response(
            data=self.get_serializer(event).data,
            message=f"Event re-processed — status is now {event.status}.",
        )
