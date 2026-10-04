from django.core.exceptions import ValidationError
from django.db.models import Prefetch

from rest_framework.decorators import action

from apps.accounts.permissions import view_permission_for
from apps.accounts.scoping import DataScopeService
from apps.core.responses.api import success_response
from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin

from apps.hr.models import (
    LeaveBalance,
    RotationPeriod,
    TravelArrangement,
    TravelRequest,
    TravelRequestPurpose,
)

from .schema import (
    TRAVEL_ARRANGEMENT_SCHEMA,
    TRAVEL_REQUEST_PURPOSE_SCHEMA,
    TRAVEL_REQUEST_SCHEMA,
)
from .serializers import (
    TravelArrangementSerializer,
    TravelRequestPurposeSerializer,
    TravelRequestSerializer,
)
from .services import (
    TravelArrangementService,
    TravelRequestPurposeService,
    TravelRequestService,
)


class TravelRequestViewSet(
    ServiceWriteMixin,
    BaseMasterViewSet,
):
    # Penyaringan data per baris (kewenangan `RoleAssignment`). Kolom
    # organisasinya sudah tersimpan langsung di record ini; `section`
    # lewat penempatan pegawainya karena baris ini tidak menyimpannya.
    data_scope = {
        "company": "company",
        "branch": "branch",
        "location": "location",
        "division": "employee__organization__division",
        "department": "employee__organization__department",
        "section": "employee__organization__section",
        "own": "employee__user_id",
    }

    # Peta yang sama, dinyatakan ulang lewat jalur relasi milik
    # `RotationPeriod`: baris jadwal tidak menyimpan kolom
    # organisasinya sendiri, jadi company/branch/location dibaca dari
    # dokumen rotasi induknya.
    #
    # Wajib sepadan dengan `data_scope` di atas. Kalau blok jadwalnya
    # tersaring lebih longgar daripada dokumen yang lahir darinya,
    # `from-rotation-period` jadi jalan memutar untuk membuat — dan
    # kemudian membaca — Travel Request milik pegawai di luar cakupan.
    rotation_period_scope = {
        "company": "rotation__company",
        "branch": "rotation__branch",
        "location": "rotation__location",
        "division": "employee__organization__division",
        "department": "employee__organization__department",
        "section": "employee__organization__section",
        "own": "employee__user_id",
    }

    serializer_class = TravelRequestSerializer
    service_class = TravelRequestService

    framework_module = "hr/travel-requests"
    schema = TRAVEL_REQUEST_SCHEMA

    # Base memberi default ["code", "name"], dan TravelRequest tidak
    # punya dua kolom itu — tanpa ditimpa, kotak pencarian membalas 500.
    search_fields = [
        "document_number",
        "employee__employee_number",
        "employee__first_name",
        "employee__last_name",
        "location__name",
        "notes",
    ]

    filterset_fields = [
        "document_number",
        "employee",
        "company",
        "branch",
        "location",
        "rotation_period",
        "status",
        "start_date",
        "end_date",
    ]

    ordering_fields = [
        "document_number",
        "start_date",
        "end_date",
        "total_days",
        "status",
        "employee__employee_number",
        "created_at",
        "updated_at",
    ]

    ordering = [
        "-start_date",
        "employee__employee_number",
    ]

    def get_queryset(self):
        return (
            TravelRequest.objects
            .select_related(
                "employee",
                # Kepala formulir dibaca lewat dua relasi; tanpa ini
                # daftar dokumen menambah beberapa query per baris.
                "employee__employment",
                "employee__employment__point_of_hire",
                "employee__organization",
                "employee__organization__department",
                "employee__organization__section",
                "employee__organization__position",
                "company",
                "branch",
                "location",
                "rotation_period",
            )
            .prefetch_related(
                Prefetch(
                    "purposes",
                    queryset=(
                        TravelRequestPurpose.objects
                        .select_related("purpose")
                        .filter(is_deleted=False)
                    ),
                ),
                Prefetch(
                    "employee__leave_balances",
                    queryset=(
                        LeaveBalance.objects
                        .select_related("leave_type")
                        .filter(is_deleted=False)
                    ),
                ),
            )
            .filter(is_deleted=False)
        )

    # ------------------------------------------------------------------
    # Approval
    # ------------------------------------------------------------------

    def _user(self, request):
        return request.user if request.user.is_authenticated else None

    def _respond(self, *, instance, message):
        instance.refresh_from_db()

        return success_response(
            data={
                "travel_request": TravelRequestSerializer(
                    instance,
                    context=self.get_serializer_context(),
                ).data,
            },
            message=message,
        )

    @action(detail=True, methods=["post"], url_path="submit")
    def submit(self, request, pk=None):
        instance = self.get_object()

        TravelRequestService.submit(
            request=instance,
            user=self._user(request),
            notes=request.data.get("notes", ""),
        )

        return self._respond(
            instance=instance,
            message="Travel Request diajukan.",
        )

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, pk=None):
        return self._decide(request, approved=True)

    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request, pk=None):
        return self._decide(request, approved=False)

    @action(detail=True, methods=["post"], url_path="withdraw")
    def withdraw(self, request, pk=None):
        instance = self.get_object()

        TravelRequestService.withdraw(
            request=instance,
            user=self._user(request),
            notes=request.data.get("notes", ""),
        )

        return self._respond(
            instance=instance,
            message="Pengajuan ditarik kembali.",
        )

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        instance = self.get_object()

        TravelRequestService.cancel(
            request=instance,
            user=self._user(request),
            notes=request.data.get("notes", ""),
        )

        return self._respond(
            instance=instance,
            message="Travel Request dibatalkan.",
        )

    def _decide(self, request, *, approved: bool):
        instance = self.get_object()

        notes = request.data.get("notes", "")

        # Penolakan tanpa alasan tidak bisa ditindaklanjuti pengaju —
        # dia hanya tahu ditolak, tidak tahu apa yang harus dibetulkan.
        if not approved and not str(notes).strip():
            raise ValidationError(
                {"notes": "Alasan penolakan wajib diisi."},
            )

        TravelRequestService.decide(
            request=instance,
            approved=approved,
            user=self._user(request),
            notes=notes,
        )

        return self._respond(
            instance=instance,
            message=(
                "Travel Request disetujui."
                if approved
                else "Travel Request ditolak."
            ),
        )

    @action(
        detail=False,
        methods=["post"],
        url_path="from-rotation-period",
    )
    def from_rotation_period(self, request):
        """
        Membuat TR dari satu blok Off pada jadwal roster.

        Body: {"rotation_period": 12}

        Jalan pintas untuk kasus yang paling sering: admin membuka
        jadwal, melihat blok off berikutnya, dan mengajukannya apa
        adanya. Isinya masih bisa disunting sesudahnya.
        """
        period_id = request.data.get("rotation_period")

        # Disaring cakupan data, sama seperti daftar Travel Request-nya
        # sendiri. Tanpa ini nomor blok jadwal tinggal ditebak dan
        # endpoint ini menerbitkan TR untuk pegawai di luar cakupan
        # pemanggilnya — dokumen yang lalu terbaca lewat daftar TR,
        # karena dokumennya kini miliknya.
        #
        # `filter_queryset()` milik viewset tidak dipakai di sini: yang
        # disaring model lain, dan lewat sana `DjangoFilterBackend`
        # ikut jalan memakai `filterset_fields` milik Travel Request.
        periods = DataScopeService.filter(
            (
                RotationPeriod.objects
                .select_related("rotation", "employee", "purpose")
                .filter(pk=period_id, is_deleted=False)
            ),
            self.rotation_period_scope,
            getattr(request, "user", None),
            required_permission=view_permission_for(RotationPeriod),
        )

        period = periods.first()

        if period is None:
            # Di luar cakupan dan tidak ada sama sekali dijawab sama —
            # membedakannya membocorkan blok jadwal mana yang ada.
            raise ValidationError(
                {
                    "rotation_period": (
                        f"Blok jadwal {period_id!r} tidak ditemukan."
                    ),
                },
            )

        instance = TravelRequestService.build_from_period(
            period=period,
            user=self._user(request),
        )

        return self._respond(
            instance=instance,
            message=(
                f"Travel Request {instance.document_number} dibuat "
                "dari blok jadwal."
            ),
        )


# Cakupan baris anak = cakupan Travel Request induknya, lewat relasi
# `request`. Peta yang sama, bukan salinan yang bisa bergeser.
TRAVEL_REQUEST_CHILD_SCOPE = {
    key: f"request__{path}"
    for key, path in TravelRequestViewSet.data_scope.items()
}


class TravelRequestChildScopeMixin:
    """
    Baris anak Travel Request (Travel Purpose, Travel Arrangement).

    Baca disaring `data_scope` lewat induknya. Tulis — create, update,
    hapus — mensyaratkan TR induknya berada di cakupan **ubah** Travel
    Request penulisnya (`hr.change_travelrequest`). Create tidak pernah
    melewati `filter_queryset()`, dan update/hapus yang hanya disaring
    dengan izin model anak tidak menjawab "boleh mengubah dokumen ini".
    Pola `BusinessTripLegViewSet` (TR-CLEANUP-1/2).
    """

    PARENT_CHANGE_PERMISSION = "hr.change_travelrequest"

    def _assert_request_writable(self, request_obj) -> None:
        user = getattr(self.request, "user", None)

        if request_obj is None or getattr(user, "is_superuser", False):
            return

        allowed = DataScopeService.filter(
            TravelRequest.objects.filter(is_deleted=False),
            TravelRequestViewSet.data_scope,
            user,
            required_permission=self.PARENT_CHANGE_PERMISSION,
        ).filter(pk=request_obj.pk).exists()

        if not allowed:
            raise ValidationError(
                {
                    "request": (
                        "Travel Request ini berada di luar cakupan "
                        "data Anda."
                    ),
                },
            )

    def perform_create(self, serializer):
        self._assert_request_writable(
            serializer.validated_data.get("request"),
        )

        super().perform_create(serializer)

    def perform_update(self, serializer):
        self._assert_request_writable(serializer.instance.request)

        super().perform_update(serializer)

    def perform_soft_delete(self, instance, user):
        # Satu jalur untuk `destroy()` dan `bulk_delete()`.
        self._assert_request_writable(instance.request)

        super().perform_soft_delete(instance, user)


class TravelRequestPurposeViewSet(
    TravelRequestChildScopeMixin,
    ServiceWriteMixin,
    BaseMasterViewSet,
):
    data_scope = TRAVEL_REQUEST_CHILD_SCOPE

    serializer_class = TravelRequestPurposeSerializer
    service_class = TravelRequestPurposeService

    framework_module = "hr/travel-request-purposes"
    schema = TRAVEL_REQUEST_PURPOSE_SCHEMA

    search_fields = [
        "purpose__code",
        "purpose__name",
        "notes",
    ]

    filterset_fields = [
        "request",
        "purpose",
        "start_date",
        "end_date",
    ]

    ordering_fields = [
        "sequence",
        "start_date",
        "end_date",
        "total_days",
        "created_at",
    ]

    # Kronologis dulu — baris sisipan mendapat nomor urut terakhir yang
    # bebas, jadi mengurutkan dari nomor akan melemparnya ke dasar
    # tabel, jauh dari baris yang dipecahnya.
    ordering = [
        "request",
        "start_date",
        "sequence",
    ]

    def get_queryset(self):
        return (
            TravelRequestPurpose.objects
            .select_related(
                "request",
                # Dibaca `policy_rules`: `LeavePolicyResolver` memilih
                # aturan lewat company + Employee Group + Employment
                # Type pegawainya. Tanpa ketiganya di sini, tiap baris
                # menambah tiga query untuk satu kolom turunan.
                "request__employee",
                "request__employee__organization",
                "request__employee__employment",
                "purpose",
                "purpose__leave_type",
                "employee_leave",
                "employee_leave__leave_type",
            )
            .filter(is_deleted=False)
        )


class TravelArrangementViewSet(
    TravelRequestChildScopeMixin,
    ServiceWriteMixin,
    BaseMasterViewSet,
):
    """
    Etape perjalanan + akomodasinya (tab Travel Arrangement dan
    Accommodation). Cakupan: `TravelRequestChildScopeMixin`
    (TR-CLEANUP-1).
    """

    data_scope = TRAVEL_REQUEST_CHILD_SCOPE

    serializer_class = TravelArrangementSerializer
    service_class = TravelArrangementService

    framework_module = "hr/travel-arrangements"
    schema = TRAVEL_ARRANGEMENT_SCHEMA

    search_fields = [
        "request__document_number",
        "request__employee__employee_number",
        "origin",
        "destination",
        "transport_detail",
        "ticket_number",
        "accommodation_name",
        "justification",
        "notes",
    ]

    filterset_fields = [
        "request",
        "direction",
        "transport_mode",
        "accommodation_type",
        "accommodation_needed",
        "is_special_arrangement",
        "travel_start_date",
    ]

    ordering_fields = [
        "direction",
        "sequence",
        "travel_start_date",
        "travel_end_date",
        "accommodation_checkin",
        "accommodation_nights",
        "created_at",
    ]

    # "out" < "in" secara alfabet tidak berlaku — urutan yang benar
    # adalah keberangkatan dulu baru kepulangan, dan itu urutan
    # tanggalnya. Jadi tanggal yang jadi kunci utama, dengan nomor
    # etape sebagai pemecah seri: Makassar → Sorong → Gebe berangkat
    # dan tiba di hari yang sama, dan tanpa `sequence` urutan dua
    # barisnya jadi kebetulan.
    ordering = [
        "request",
        "travel_start_date",
        "direction",
        "sequence",
    ]

    def get_queryset(self):
        return (
            TravelArrangement.objects
            .select_related(
                "request",
                "request__employee",
                "transport_mode",
                "accommodation_type",
            )
            .filter(is_deleted=False)
        )

