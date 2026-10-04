"""
Asset Assignment — `/api/assets/assignments/`.

CRUD hanya untuk DRAFT (service yang menolak selebihnya). Perpindahan
status lewat aksi eksplisit: submit, approve/reject (hak milik engine
workflow), cancel, complete. Tidak ada jalur yang menulis custody selain
`complete` → `AssetCustodyService.move`.
"""

from rest_framework.decorators import action

from apps.assets.services import AssetAssignmentService
from apps.assets.services.operations.assignment import (
    CANCEL_PERMISSION,
    COMPLETE_PERMISSION,
    SUBMIT_PERMISSION,
    WORKFLOW_DOCUMENT_TYPE,
    WORKFLOW_MODULE,
)
from apps.core.responses.api import success_response
from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin

from .schema import ASSET_ASSIGNMENT_SCHEMA
from .scope import ASSIGNMENT_SCOPE
from .serializers import (
    AssetAssignmentSerializer,
    CompleteSerializer,
    NotesSerializer,
)


class AssetAssignmentViewSet(
    ServiceWriteMixin,
    BaseMasterViewSet,
):
    serializer_class = AssetAssignmentSerializer
    service_class = AssetAssignmentService

    framework_module = "assets/assignments"
    schema = ASSET_ASSIGNMENT_SCHEMA

    data_scope = ASSIGNMENT_SCOPE
    require_view_permission = True

    # Peserta alur membaca dan memutuskan dokumen yang ditagihkan
    # kepadanya walau di luar cakupan datanya. `approve`/`reject` sengaja
    # tidak di `action_scope_permissions`: haknya milik engine.
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
        "employee__employee_number",
    ]
    filterset_fields = [
        "status",
        "company",
        "asset",
        "target_custody_type",
        "employee",
        "department",
        "location",
        "source_location",
        "is_cross_company",
    ]
    ordering_fields = [
        "document_number",
        "status",
        "created_at",
        "submitted_at",
        "handover_date",
    ]
    ordering = ["-created_at", "-id"]

    def _respond(self, assignment, message):
        assignment.refresh_from_db()

        return success_response(
            data=self.get_serializer(assignment).data,
            message=message,
        )

    def _notes(self, request) -> str:
        payload = NotesSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        return payload.validated_data["notes"]

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        assignment = self.get_object()

        AssetAssignmentService.submit(
            assignment=assignment,
            user=self._service_user(),
            notes=self._notes(request),
        )

        return self._respond(assignment, "Assignment diajukan.")

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        assignment = self.get_object()

        AssetAssignmentService.decide(
            assignment=assignment,
            approved=True,
            user=self._service_user(),
            notes=self._notes(request),
        )

        return self._respond(assignment, "Keputusan dicatat.")

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        assignment = self.get_object()

        AssetAssignmentService.decide(
            assignment=assignment,
            approved=False,
            user=self._service_user(),
            notes=self._notes(request),
        )

        return self._respond(assignment, "Assignment ditolak.")

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        assignment = self.get_object()

        AssetAssignmentService.cancel(
            assignment=assignment,
            user=self._service_user(),
            notes=self._notes(request),
        )

        return self._respond(assignment, "Assignment dibatalkan.")

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        assignment = self.get_object()

        payload = CompleteSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        AssetAssignmentService.complete(
            assignment=assignment,
            user=self._service_user(),
            handover_date=payload.validated_data.get("handover_date"),
            condition=payload.validated_data["condition"],
            note=payload.validated_data["note"],
        )

        return self._respond(assignment, "Serah terima selesai.")
