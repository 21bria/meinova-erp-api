"""
Asset Register — `/api/assets/assets/`.

Tulis lewat `AssetService` (create/update/soft delete) dan dua aksi
eksplisit: `activate` dan `record-condition`. Tidak ada jalur API yang
menulis custody; status tidak bisa di-PATCH.

Baca riwayat (ASSET-6): `GET {id}/custody-history/` dan
`GET {id}/condition-history/`. Keduanya lewat `get_object()`, jadi tunduk
pada izin baca **dan** cakupan aset yang sama — yang tidak bisa melihat
asetnya mendapat 404, bukan riwayatnya.
"""

from rest_framework.decorators import action

from apps.assets.services import AssetService
from apps.assets.services.operations.history import AssetHistoryService
from apps.core.responses.api import success_response
from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin

from .schema import ASSET_SCHEMA
from .scope import ASSET_SCOPE
from .serializers import (
    AssetSerializer,
    ConditionLogSerializer,
    CustodyRowSerializer,
    RecordConditionSerializer,
)


CHANGE_PERMISSION = "assets.change_asset"


class AssetViewSet(
    ServiceWriteMixin,
    BaseMasterViewSet,
):
    serializer_class = AssetSerializer
    service_class = AssetService

    framework_module = "assets/register"
    schema = ASSET_SCHEMA

    data_scope = ASSET_SCOPE
    require_view_permission = True

    # Aksi yang mengubah aset dicakup dari izin ubah, bukan izin baca.
    action_scope_permissions = {
        "activate": CHANGE_PERMISSION,
        "record_condition": CHANGE_PERMISSION,
    }

    search_fields = [
        "asset_code",
        "serial_number",
        "tag_number",
        "name",
        "manufacturer",
        "model",
    ]
    filterset_fields = [
        "company",
        "category",
        "location",
        "facility",
        "condition",
        "status",
    ]
    ordering_fields = [
        "asset_code",
        "name",
        "serial_number",
        "status",
        "condition",
        "created_at",
        "activated_at",
    ]
    ordering = ["company", "asset_code"]

    @action(detail=True, methods=["post"])
    def activate(self, request, pk=None):
        asset = AssetService.activate(
            asset=self.get_object(),
            user=self._service_user(),
        )

        return success_response(
            data=self.get_serializer(asset).data,
            message="Aset diaktifkan.",
        )

    @action(detail=True, methods=["post"], url_path="record-condition")
    def record_condition(self, request, pk=None):
        payload = RecordConditionSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        asset = AssetService.record_condition(
            asset=self.get_object(),
            condition=payload.validated_data["condition"],
            note=payload.validated_data["note"],
            user=self._service_user(),
        )

        return success_response(
            data=self.get_serializer(asset).data,
            message="Kondisi aset dicatat.",
        )

    @action(detail=True, methods=["get"], url_path="custody-history")
    def custody_history(self, request, pk=None):
        rows = AssetHistoryService.custody_rows(self.get_object())

        data = CustodyRowSerializer(
            rows,
            many=True,
            context={
                **self.get_serializer_context(),
                "provenance": AssetHistoryService.provenance(rows),
            },
        ).data

        return success_response(data=data, meta={"count": len(data)})

    @action(detail=True, methods=["get"], url_path="condition-history")
    def condition_history(self, request, pk=None):
        rows = AssetHistoryService.condition_rows(self.get_object())

        data = ConditionLogSerializer(rows, many=True).data

        return success_response(data=data, meta={"count": len(data)})
