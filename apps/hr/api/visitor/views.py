"""
ViewSet Visitor Management.

`ServiceWriteMixin` dipasang di ketiganya — tanpa itu `service_class`
hanya dipakai untuk `get_queryset()` dan `soft_delete()`, jalur tulisnya
tetap `serializer.save()` bawaan DRF, dan seluruh isi `services.py`
(penomoran, pengisian cakupan, penolakan tamu blacklist) tidak pernah
jalan lewat API. Gagalnya diam: dokumennya tersimpan, cuma tanpa nomor
dan tanpa satu pun pemeriksaan.
"""

from django.core.exceptions import ValidationError
from django.db.models import Count, Prefetch, Q

from rest_framework.decorators import action

from apps.core.responses.api import success_response
from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin

from apps.hr.models import (
    ExternalVisitor,
    VisitorPass,
    VisitorRequest,
)

from .schema import (
    EXTERNAL_VISITOR_SCHEMA,
    VISITOR_PASS_SCHEMA,
    VISITOR_REQUEST_SCHEMA,
)
from .serializers import (
    ExternalVisitorSerializer,
    VisitorPassSerializer,
    VisitorRequestSerializer,
)
from .services import (
    ExternalVisitorService,
    VisitorPassService,
    VisitorRequestService,
)


class ExternalVisitorViewSet(
    ServiceWriteMixin,
    BaseMasterViewSet,
):
    """
    Master tamu luar.

    Sengaja **tanpa** `data_scope`: tamu bukan data yang menempel pada
    satu company atau site. Vendor yang sama datang ke Jakarta bulan ini
    dan ke Gebe bulan depan, dan menyembunyikan masternya per lokasi
    berarti orang yang sama didaftarkan ulang di tiap site — persis
    duplikasi yang dicegah master ini. Yang dicakup adalah
    **kunjungannya** (`VisitorRequest`), bukan identitas tamunya.
    """

    serializer_class = ExternalVisitorSerializer
    service_class = ExternalVisitorService

    framework_module = "hr/external-visitors"
    schema = EXTERNAL_VISITOR_SCHEMA

    # Base memberi default ["code", "name"] dan model ini tidak punya
    # keduanya — tanpa ditimpa, kotak pencarian membalas 500.
    search_fields = [
        "visitor_number",
        "full_name",
        "identity_number",
        "organization_name",
        "email",
        "mobile",
        "phone",
        "position",
        "address",
        "notes",
    ]

    filterset_fields = [
        "identity_type",
        "gender",
        "nationality",
        "city",
        "country",
        "is_active",
        "is_blacklisted",
    ]

    ordering_fields = [
        "visitor_number",
        "full_name",
        "organization_name",
        "created_at",
        "updated_at",
    ]

    ordering = ["full_name"]

    def get_queryset(self):
        return (
            ExternalVisitor.objects
            .select_related(
                "gender",
                "nationality",
                "city",
                "country",
            )
            # Anotasi diberi nama berbeda dari properti/serializer
            # method-nya (`visit_count`). Nama yang sama akan
            # ditempelkan Django lewat `setattr` ke instance dan
            # menjatuhkan endpoint-nya dengan "has no setter" —
            # jebakan yang sudah kena dua kali di codebase ini.
            .annotate(
                visit_total=Count(
                    "visitor_requests",
                    filter=Q(visitor_requests__is_deleted=False),
                    distinct=True,
                ),
            )
            .filter(is_deleted=False)
        )


class VisitorRequestViewSet(
    ServiceWriteMixin,
    BaseMasterViewSet,
):
    # Cakupan barisnya mengikuti penempatan **pemohon**, yang sudah
    # didenormalisasi ke kolom company/branch/location saat dokumen
    # dibuat. `own` menunjuk akun pemohonnya: pegawai biasa harus bisa
    # melihat kunjungan yang ia ajukan sendiri.
    data_scope = {
        "company": "company",
        "branch": "branch",
        "location": "location",
        "division": "requester__organization__division",
        "department": "requester__organization__department",
        "section": "requester__organization__section",
        "own": "requester__user_id",
    }

    serializer_class = VisitorRequestSerializer
    service_class = VisitorRequestService

    framework_module = "hr/visitor-requests"
    schema = VISITOR_REQUEST_SCHEMA

    search_fields = [
        "document_number",
        "external_visitor__full_name",
        "external_visitor__organization_name",
        "external_visitor__identity_number",
        "employee__employee_number",
        "employee__first_name",
        "employee__last_name",
        "host_employee__first_name",
        "host_employee__last_name",
        "requester__first_name",
        "requester__last_name",
        "location__name",
        "remarks",
    ]

    filterset_fields = [
        "document_number",
        "visitor_type",
        "status",
        "arrival_status",
        "company",
        "branch",
        "location",
        "requester",
        "host_employee",
        "employee",
        "external_visitor",
        "visit_purpose",
        "visit_type",
        "visit_start_date",
        "visit_end_date",
        "travel_required",
        "accommodation_required",
    ]

    ordering_fields = [
        "document_number",
        "request_date",
        "visit_start_date",
        "visit_end_date",
        "status",
        "arrival_status",
        "checked_in_at",
        "checked_out_at",
        "created_at",
    ]

    ordering = ["-visit_start_date", "-id"]

    def get_queryset(self):
        return (
            VisitorRequest.objects
            .select_related(
                "requester",
                "requester__organization",
                "requester__organization__department",
                "employee",
                "employee__organization",
                "employee__organization__department",
                "employee__organization__position",
                "employee__organization__location",
                "employee__organization__company",
                "external_visitor",
                "host_employee",
                "host_employee__organization",
                "host_employee__organization__department",
                "host_employee__organization__position",
                "company",
                "branch",
                "location",
                "visit_purpose",
                "visit_type",
                "transport_mode",
                "accommodation_type",
                "checked_in_by",
                "checked_out_by",
            )
            .prefetch_related(
                Prefetch(
                    "passes",
                    queryset=VisitorPass.objects.filter(is_deleted=False),
                ),
            )
            .filter(is_deleted=False)
        )

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    def _user(self, request):
        return request.user if request.user.is_authenticated else None

    def _respond(self, *, instance, message):
        # Dibaca ulang lewat queryset, bukan `refresh_from_db()`:
        # yang kedua tidak membersihkan cache prefetch, jadi kartu
        # yang baru terbit tidak muncul di respons dan fiturnya
        # terbaca gagal padahal barisnya tersimpan.
        fresh = self.get_queryset().get(pk=instance.pk)

        return success_response(
            data={
                "visitor_request": VisitorRequestSerializer(
                    fresh,
                    context=self.get_serializer_context(),
                ).data,
            },
            message=message,
        )

    # ------------------------------------------------------------------
    # Alur persetujuan
    # ------------------------------------------------------------------

    @action(detail=True, methods=["post"], url_path="submit")
    def submit(self, request, pk=None):
        instance = self.get_object()

        VisitorRequestService.submit(
            request=instance,
            user=self._user(request),
            notes=request.data.get("notes", ""),
        )

        return self._respond(
            instance=instance,
            message="Visitor Request diajukan.",
        )

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, pk=None):
        return self._decide(request, approved=True)

    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request, pk=None):
        return self._decide(request, approved=False)

    def _decide(self, request, *, approved: bool):
        instance = self.get_object()

        notes = request.data.get("notes", "")

        # Penolakan tanpa alasan tidak bisa ditindaklanjuti pengaju —
        # dia hanya tahu ditolak, tidak tahu apa yang harus dibetulkan.
        if not approved and not str(notes).strip():
            raise ValidationError(
                {"notes": "Alasan penolakan wajib diisi."},
            )

        VisitorRequestService.decide(
            request=instance,
            approved=approved,
            user=self._user(request),
            notes=notes,
        )

        return self._respond(
            instance=instance,
            message=(
                "Visitor Request disetujui."
                if approved
                else "Visitor Request ditolak."
            ),
        )

    @action(detail=True, methods=["post"], url_path="withdraw")
    def withdraw(self, request, pk=None):
        instance = self.get_object()

        VisitorRequestService.withdraw(
            request=instance,
            user=self._user(request),
            notes=request.data.get("notes", ""),
        )

        return self._respond(
            instance=instance,
            message="Pengajuan ditarik kembali.",
        )

    # ------------------------------------------------------------------
    # Pos jaga
    # ------------------------------------------------------------------

    @action(detail=True, methods=["post"], url_path="check-in")
    def check_in(self, request, pk=None):
        instance = self.get_object()

        VisitorRequestService.check_in(
            request=instance,
            user=self._user(request),
            gate=request.data.get("gate", ""),
            remarks=request.data.get("remarks", ""),
        )

        return self._respond(
            instance=instance,
            message="Tamu check-in. Visitor Pass diterbitkan.",
        )

    @action(detail=True, methods=["post"], url_path="check-out")
    def check_out(self, request, pk=None):
        instance = self.get_object()

        VisitorRequestService.check_out(
            request=instance,
            user=self._user(request),
            remarks=request.data.get("remarks", ""),
        )

        return self._respond(
            instance=instance,
            message="Tamu check-out. Kunjungan selesai.",
        )

    @action(detail=True, methods=["post"], url_path="no-show")
    def no_show(self, request, pk=None):
        instance = self.get_object()

        VisitorRequestService.mark_no_show(
            request=instance,
            user=self._user(request),
            remarks=request.data.get("remarks", ""),
        )

        return self._respond(
            instance=instance,
            message="Kunjungan ditandai No Show.",
        )

    @action(detail=True, methods=["post"], url_path="issue-pass")
    def issue_pass(self, request, pk=None):
        instance = self.get_object()

        issued = VisitorPassService.issue(
            request=instance,
            user=self._user(request),
        )

        return self._respond(
            instance=instance,
            message=(
                f"Visitor Pass {issued.pass_number or ''} "
                "diterbitkan."
            ).strip(),
        )

    # ------------------------------------------------------------------
    # Pencarian di pos jaga
    # ------------------------------------------------------------------

    @action(detail=False, methods=["get"], url_path="gate")
    def gate(self, request):
        """
        Daftar tamu yang diharapkan hari ini, untuk layar pos jaga.

        Layar tersendiri karena yang dicari satpam bukan "dokumen
        kunjungan" melainkan "siapa yang boleh masuk sekarang" —
        dan itu selalu irisan yang sama: sudah disetujui, tanggalnya
        mencakup hari ini, belum check-out.

        Lewat `filter_queryset` supaya cakupan data tetap
        berlaku: satpam site tidak perlu melihat tamu site lain.
        """
        from django.utils import timezone

        today = timezone.localdate()

        queryset = (
            self.filter_queryset(self.get_queryset())
            .filter(
                status__in=["approved", "completed"],
                visit_start_date__lte=today,
                visit_end_date__gte=today,
            )
            .exclude(arrival_status="no_show")
            .order_by("checked_in_at", "visit_start_time", "id")
        )

        page = self.paginate_queryset(queryset)

        serializer = self.get_serializer(
            page if page is not None else queryset,
            many=True,
        )

        if page is not None:
            return self.get_paginated_response(serializer.data)

        return success_response(
            data=serializer.data,
            message="Daftar tamu hari ini.",
        )


class VisitorPassViewSet(
    ServiceWriteMixin,
    BaseMasterViewSet,
):
    # Cakupannya menembus dokumen kunjungannya — kartu tidak menyimpan
    # kolom organisasi sendiri, dan menyalinnya ke sini berarti dua
    # tempat yang bisa berbeda.
    data_scope = {
        "company": "request__company",
        "branch": "request__branch",
        "location": "request__location",
        "own": "request__requester__user_id",
    }

    serializer_class = VisitorPassSerializer
    service_class = VisitorPassService

    framework_module = "hr/visitor-passes"
    schema = VISITOR_PASS_SCHEMA

    search_fields = [
        "pass_number",
        "request__document_number",
        "request__external_visitor__full_name",
        "request__employee__first_name",
        "request__employee__last_name",
        "notes",
    ]

    filterset_fields = [
        "request",
        "status",
        "valid_from",
        "valid_until",
    ]

    ordering_fields = [
        "pass_number",
        "valid_from",
        "valid_until",
        "status",
        "issued_at",
        "returned_at",
    ]

    ordering = ["-issued_at", "-id"]

    def get_queryset(self):
        return (
            VisitorPass.objects
            .select_related(
                "request",
                "request__employee",
                "request__external_visitor",
                "request__host_employee",
                "request__location",
                "issued_by",
                "returned_by",
            )
            .filter(is_deleted=False)
        )

    def _user(self, request):
        return request.user if request.user.is_authenticated else None

    def _respond(self, *, instance, message):
        instance.refresh_from_db()

        return success_response(
            data={
                "visitor_pass": VisitorPassSerializer(
                    instance,
                    context=self.get_serializer_context(),
                ).data,
            },
            message=message,
        )

    @action(detail=True, methods=["post"], url_path="return")
    def return_pass(self, request, pk=None):
        instance = self.get_object()

        VisitorPassService.mark_returned(
            instance=instance,
            user=self._user(request),
            notes=request.data.get("notes", ""),
        )

        return self._respond(
            instance=instance,
            message="Kartu ditandai sudah kembali.",
        )

    @action(detail=True, methods=["post"], url_path="lost")
    def mark_lost(self, request, pk=None):
        instance = self.get_object()

        VisitorPassService.mark_lost(
            instance=instance,
            user=self._user(request),
            notes=request.data.get("notes", ""),
        )

        return self._respond(
            instance=instance,
            message="Kartu ditandai hilang.",
        )
