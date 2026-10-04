"""
ViewSet Business Trip (BT-2).

Tiga hal yang sengaja **tidak** ditiru dari Travel Request (temuan BT-1):

* approver yang cakupannya `own` harus bisa membuka dokumen yang
  ditagihkan kepadanya → `workflow_document`;
* endpoint anak (ruas perjalanan) disaring per baris lewat dokumen
  induknya, termasuk jalur create;
* baca menuntut izin + cakupan (`require_view_permission`) — keberadaan
  seseorang di luar kantor adalah data pribadi.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.utils.dateparse import parse_datetime

from rest_framework.decorators import action

from apps.accounts.scoping import DataScopeService
from apps.core.responses.api import success_response
from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin
from apps.hr.api.employee.write_scope import EmployeeSubjectWriteGuardMixin
from apps.hr.models import BusinessTrip, BusinessTripLeg

from .schema import BUSINESS_TRIP_LEG_SCHEMA, BUSINESS_TRIP_SCHEMA
from .serializers import BusinessTripLegSerializer, BusinessTripSerializer
from .services import BusinessTripLegService, BusinessTripService


# Cakupan dari **salinan** organisasi di dokumen, bukan dari penempatan
# pegawai hari ini: perjalanan yang sudah terjadi tetap milik unit yang
# memilikinya saat itu.
BUSINESS_TRIP_SCOPE = {
    "company": "company",
    "branch": "branch",
    "location": "location",
    "division": "division",
    "department": "department",
    "section": "section",
    "own": "employee__user_id",
}

CHANGE_PERMISSION = "hr.change_businesstrip"


def _prefixed(scope: dict, prefix: str) -> dict:
    return {key: f"{prefix}__{path}" for key, path in scope.items()}


class BusinessTripViewSet(
    EmployeeSubjectWriteGuardMixin,
    ServiceWriteMixin,
    BaseMasterViewSet,
):
    data_scope = BUSINESS_TRIP_SCOPE

    require_view_permission = True

    # Peserta alur membaca dan memutuskan dokumen yang ditagihkan
    # kepadanya walau di luar cakupan datanya — pola Cuti.
    workflow_document = (
        BusinessTripService.WORKFLOW_MODULE,
        BusinessTripService.WORKFLOW_DOCUMENT_TYPE,
    )

    # Aksi yang mengubah dokumen dicakup dari izin ubah, bukan izin baca.
    # `approve`/`reject`/`send_back` sengaja tidak di sini: haknya milik
    # engine alur, dan pesertanya dilebarkan `workflow_document`.
    action_scope_permissions = {
        "submit": CHANGE_PERMISSION,
        "withdraw": CHANGE_PERMISSION,
        "depart": CHANGE_PERMISSION,
        "complete": CHANGE_PERMISSION,
        "cancel": CHANGE_PERMISSION,
    }

    serializer_class = BusinessTripSerializer
    service_class = BusinessTripService

    framework_module = "hr/business-trips"
    schema = BUSINESS_TRIP_SCHEMA

    search_fields = [
        "document_number",
        "employee__employee_number",
        "employee__first_name",
        "employee__last_name",
        "destination_location__name",
        "destination_city__name",
        "destination_detail",
        "purpose",
    ]

    filterset_fields = [
        "document_number",
        "employee",
        "company",
        "branch",
        "location",
        "department",
        "status",
        "purpose_category",
        "destination_type",
        "destination_location",
        "supersedes",
    ]

    ordering_fields = [
        "document_number",
        "request_date",
        "departure_datetime",
        "return_datetime",
        "status",
        "employee__employee_number",
        "created_at",
    ]

    ordering = ["-departure_datetime", "-id"]

    def get_queryset(self):
        return (
            BusinessTrip.objects
            .select_related(
                "employee",
                "requester",
                "company",
                "branch",
                "location",
                "division",
                "department",
                "section",
                "position",
                "cost_center",
                "origin_location",
                "destination_location",
                "destination_city",
                "destination_country",
                "supersedes",
                "attachment",
            )
            .filter(is_deleted=False)
        )

    # ------------------------------------------------------------------

    def _user(self, request):
        return request.user if request.user.is_authenticated else None

    def _respond(self, *, instance, message):
        fresh = BusinessTrip.objects.get(pk=instance.pk)

        return success_response(
            data={
                "business_trip": BusinessTripSerializer(
                    fresh,
                    context=self.get_serializer_context(),
                ).data,
            },
            message=message,
        )

    @staticmethod
    def _notes(request) -> str:
        return str(request.data.get("notes", "") or "").strip()

    @staticmethod
    def _datetime(request, key):
        raw = request.data.get(key)

        if raw in (None, ""):
            return None

        value = parse_datetime(str(raw))

        if value is None:
            raise ValidationError({key: "Format waktu tidak dikenal."})

        return value

    # ------------------------------------------------------------------
    # Alur persetujuan
    # ------------------------------------------------------------------

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        instance = self.get_object()

        BusinessTripService.submit(
            trip=instance,
            user=self._user(request),
            notes=self._notes(request),
        )

        return self._respond(
            instance=instance,
            message="Business Trip diajukan.",
        )

    def _decide(self, request, decision, message, *, require_notes=False):
        instance = self.get_object()

        notes = self._notes(request)

        if require_notes and not notes:
            raise ValidationError({"notes": "Alasan wajib diisi."})

        BusinessTripService.decide(
            trip=instance,
            decision=decision,
            user=self._user(request),
            notes=notes,
        )

        return self._respond(instance=instance, message=message)

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        return self._decide(request, "approve", "Business Trip disetujui.")

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        return self._decide(
            request,
            "reject",
            "Business Trip ditolak.",
            require_notes=True,
        )

    @action(detail=True, methods=["post"], url_path="return")
    def send_back(self, request, pk=None):
        return self._decide(
            request,
            "return",
            "Business Trip dikembalikan ke pengaju.",
            require_notes=True,
        )

    @action(detail=True, methods=["post"])
    def withdraw(self, request, pk=None):
        instance = self.get_object()

        BusinessTripService.withdraw(
            trip=instance,
            user=self._user(request),
            notes=self._notes(request),
        )

        return self._respond(
            instance=instance,
            message="Pengajuan ditarik kembali.",
        )

    # ------------------------------------------------------------------
    # Sesudah disetujui
    # ------------------------------------------------------------------

    @action(detail=True, methods=["post"])
    def depart(self, request, pk=None):
        instance = self.get_object()

        BusinessTripService.depart(
            trip=instance,
            user=self._user(request),
            actual_departure=self._datetime(
                request,
                "actual_departure_datetime",
            ),
        )

        return self._respond(
            instance=instance,
            message="Perjalanan ditandai berangkat.",
        )

    @action(detail=True, methods=["post"])
    def complete(self, request, pk=None):
        instance = self.get_object()

        BusinessTripService.complete(
            trip=instance,
            user=self._user(request),
            actual_return=self._datetime(request, "actual_return_datetime"),
        )

        return self._respond(
            instance=instance,
            message="Perjalanan selesai.",
        )

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        instance = self.get_object()

        BusinessTripService.cancel(
            trip=instance,
            user=self._user(request),
            reason=str(request.data.get("cancellation_reason", "") or ""),
        )

        return self._respond(
            instance=instance,
            message="Business Trip dibatalkan.",
        )


class BusinessTripLegViewSet(
    ServiceWriteMixin,
    BaseMasterViewSet,
):
    """
    Ruas perjalanan. Barisnya disaring lewat dokumen induknya, dan jalur
    create — yang tidak pernah melewati `filter_queryset()` — memeriksa
    bahwa induknya berada di cakupan **ubah** penulisnya.
    """

    data_scope = _prefixed(BUSINESS_TRIP_SCOPE, "trip")

    require_view_permission = True

    serializer_class = BusinessTripLegSerializer
    service_class = BusinessTripLegService

    framework_module = "hr/business-trip-legs"
    schema = BUSINESS_TRIP_LEG_SCHEMA

    search_fields = ["origin", "destination", "ticket_number"]

    filterset_fields = ["trip", "direction"]

    ordering_fields = ["sequence", "travel_start_date", "id"]

    ordering = ["trip", "sequence", "id"]

    def get_queryset(self):
        return (
            BusinessTripLeg.objects
            .select_related("trip", "transport_mode", "accommodation_type")
            .filter(is_deleted=False, trip__is_deleted=False)
        )

    def _assert_trip_writable(self, trip) -> None:
        user = getattr(self.request, "user", None)

        if trip is None or getattr(user, "is_superuser", False):
            return

        allowed = DataScopeService.filter(
            BusinessTrip.objects.filter(is_deleted=False),
            BUSINESS_TRIP_SCOPE,
            user,
            required_permission=CHANGE_PERMISSION,
        ).filter(pk=trip.pk).exists()

        if not allowed:
            raise ValidationError(
                {
                    "trip": (
                        "Business Trip ini berada di luar cakupan data "
                        "Anda."
                    ),
                },
            )

    def perform_create(self, serializer):
        self._assert_trip_writable(serializer.validated_data.get("trip"))

        super().perform_create(serializer)
