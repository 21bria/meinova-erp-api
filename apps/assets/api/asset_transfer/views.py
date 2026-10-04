"""
Asset Transfer — `/api/assets/transfers/`.

CRUD hanya untuk DRAFT (service yang menolak selebihnya). Perpindahan
status lewat aksi eksplisit: submit, approve/reject (hak milik engine
workflow), cancel, complete. Tidak ada jalur yang menulis custody atau
pemesanan selain service.

Cakupan: lihat dari asal atau tujuan; sunting draft/submit/cancel hanya
asal; complete hanya tujuan (`scope.py`).
"""

from rest_framework.decorators import action

from apps.assets.api.side_scope import SideScopedViewSetMixin
from apps.assets.services import AssetTransferService
from apps.assets.services.operations.asset_transfer import (
    CANCEL_PERMISSION,
    COMPLETE_PERMISSION,
    SUBMIT_PERMISSION,
    WORKFLOW_DOCUMENT_TYPE,
    WORKFLOW_MODULE,
)
from apps.core.responses.api import success_response
from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin

from .schema import ASSET_TRANSFER_SCHEMA
from .scope import (
    SOURCE_ONLY_ACTIONS,
    TARGET_ONLY_ACTIONS,
    TRANSFER_SOURCE_SCOPE,
    TRANSFER_TARGET_SCOPE,
)
from .serializers import (
    AssetTransferSerializer,
    CompleteTransferSerializer,
    NotesSerializer,
)


class AssetTransferViewSet(
    SideScopedViewSetMixin,
    ServiceWriteMixin,
    BaseMasterViewSet,
):
    serializer_class = AssetTransferSerializer
    service_class = AssetTransferService

    framework_module = "assets/transfers"
    schema = ASSET_TRANSFER_SCHEMA

    # Peta utama untuk alat audit/test yang membaca atribut ini; yang
    # benar-benar diterapkan adalah `scope_sides` di bawah.
    data_scope = TRANSFER_SOURCE_SCOPE
    require_view_permission = True

    scope_sides = {
        "source": TRANSFER_SOURCE_SCOPE,
        "target": TRANSFER_TARGET_SCOPE,
    }
    visible_sides = ("source", "target")
    action_sides = {
        **{name: ("source",) for name in SOURCE_ONLY_ACTIONS},
        **{name: ("target",) for name in TARGET_ONLY_ACTIONS},
    }

    workflow_document = (WORKFLOW_MODULE, WORKFLOW_DOCUMENT_TYPE)

    action_scope_permissions = {
        "submit": SUBMIT_PERMISSION,
        "complete": COMPLETE_PERMISSION,
        "cancel": CANCEL_PERMISSION,
    }

    search_fields = [
        "document_number",
        "asset__asset_code",
        "asset__name",
        "source_employee__employee_number",
        "target_employee__employee_number",
    ]
    filterset_fields = [
        "status",
        "company",
        "asset",
        "reason",
        "source_custody_type",
        "target_custody_type",
        "source_employee",
        "target_employee",
        "source_department",
        "target_department",
        "source_location",
        "target_location",
        "is_cross_company",
    ]
    ordering_fields = [
        "document_number",
        "status",
        "created_at",
        "submitted_at",
        "transfer_date",
    ]
    ordering = ["-created_at", "-id"]

    def _respond(self, transfer, message):
        transfer.refresh_from_db()

        return success_response(
            data=self.get_serializer(transfer).data,
            message=message,
        )

    def _notes(self, request) -> str:
        payload = NotesSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        return payload.validated_data["notes"]

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        transfer = self.get_object()

        AssetTransferService.submit(
            transfer=transfer,
            user=self._service_user(),
            notes=self._notes(request),
        )

        return self._respond(transfer, "Transfer diajukan.")

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        transfer = self.get_object()

        AssetTransferService.decide(
            transfer=transfer,
            approved=True,
            user=self._service_user(),
            notes=self._notes(request),
        )

        return self._respond(transfer, "Keputusan dicatat.")

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        transfer = self.get_object()

        AssetTransferService.decide(
            transfer=transfer,
            approved=False,
            user=self._service_user(),
            notes=self._notes(request),
        )

        return self._respond(transfer, "Transfer ditolak.")

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        transfer = self.get_object()

        AssetTransferService.cancel(
            transfer=transfer,
            user=self._service_user(),
            notes=self._notes(request),
        )

        return self._respond(transfer, "Transfer dibatalkan.")

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        transfer = self.get_object()

        payload = CompleteTransferSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        AssetTransferService.complete(
            transfer=transfer,
            user=self._service_user(),
            transfer_date=payload.validated_data.get("transfer_date"),
            condition=payload.validated_data["condition"],
            note=payload.validated_data["note"],
        )

        return self._respond(transfer, "Transfer selesai.")
