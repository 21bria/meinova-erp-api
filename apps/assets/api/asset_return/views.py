"""
Asset Return — `/api/assets/returns/`.

CRUD hanya untuk DRAFT (service yang menolak selebihnya). Perpindahan
status lewat aksi eksplisit: submit, approve/reject (hak milik engine
workflow), cancel, complete. Tidak ada jalur yang menulis custody atau
pemesanan selain service.

Cakupan = sisi asal ∪ sisi tujuan (`scope.py`); `complete` hanya sisi
tujuan.
"""

from rest_framework.decorators import action

from apps.assets.api.side_scope import SideScopedViewSetMixin
from apps.assets.services import AssetReturnService
from apps.assets.services.operations.asset_return import (
    CANCEL_PERMISSION,
    COMPLETE_PERMISSION,
    SUBMIT_PERMISSION,
    WORKFLOW_DOCUMENT_TYPE,
    WORKFLOW_MODULE,
)
from apps.core.responses.api import success_response
from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin

from .schema import ASSET_RETURN_SCHEMA
from .scope import RETURN_DESTINATION_SCOPE, RETURN_SOURCE_SCOPE
from .serializers import (
    AssetReturnSerializer,
    CompleteReturnSerializer,
    NotesSerializer,
)


class AssetReturnViewSet(
    SideScopedViewSetMixin,
    ServiceWriteMixin,
    BaseMasterViewSet,
):
    serializer_class = AssetReturnSerializer
    service_class = AssetReturnService

    framework_module = "assets/returns"
    schema = ASSET_RETURN_SCHEMA

    # Peta utama untuk alat audit/test yang membaca atribut ini; yang
    # benar-benar diterapkan adalah union di `filter_queryset`.
    data_scope = RETURN_SOURCE_SCOPE
    require_view_permission = True

    # Lihat dari asal atau tujuan; barang diterima (`complete`) hanya
    # oleh sisi tujuan. Submit/cancel dari sisi mana pun (ASSET-4).
    scope_sides = {
        "source": RETURN_SOURCE_SCOPE,
        "destination": RETURN_DESTINATION_SCOPE,
    }
    visible_sides = ("source", "destination")
    action_sides = {"complete": ("destination",)}

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
    ]
    filterset_fields = [
        "status",
        "company",
        "asset",
        "reason",
        "source_custody_type",
        "source_employee",
        "source_department",
        "source_location",
        "destination_location",
        "return_condition",
    ]
    ordering_fields = [
        "document_number",
        "status",
        "created_at",
        "submitted_at",
        "return_date",
    ]
    ordering = ["-created_at", "-id"]

    def _respond(self, asset_return, message):
        asset_return.refresh_from_db()

        return success_response(
            data=self.get_serializer(asset_return).data,
            message=message,
        )

    def _notes(self, request) -> str:
        payload = NotesSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        return payload.validated_data["notes"]

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        asset_return = self.get_object()

        AssetReturnService.submit(
            asset_return=asset_return,
            user=self._service_user(),
            notes=self._notes(request),
        )

        return self._respond(asset_return, "Return diajukan.")

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        asset_return = self.get_object()

        AssetReturnService.decide(
            asset_return=asset_return,
            approved=True,
            user=self._service_user(),
            notes=self._notes(request),
        )

        return self._respond(asset_return, "Keputusan dicatat.")

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        asset_return = self.get_object()

        AssetReturnService.decide(
            asset_return=asset_return,
            approved=False,
            user=self._service_user(),
            notes=self._notes(request),
        )

        return self._respond(asset_return, "Return ditolak.")

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        asset_return = self.get_object()

        AssetReturnService.cancel(
            asset_return=asset_return,
            user=self._service_user(),
            notes=self._notes(request),
        )

        return self._respond(asset_return, "Return dibatalkan.")

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        asset_return = self.get_object()

        payload = CompleteReturnSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        AssetReturnService.complete(
            asset_return=asset_return,
            user=self._service_user(),
            return_date=payload.validated_data.get("return_date"),
            condition=payload.validated_data["condition"],
            note=payload.validated_data["note"],
        )

        return self._respond(asset_return, "Pengembalian diterima.")
