from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.decorators import action

from apps.core.responses.api import error_response, success_response
from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin
from apps.hr.models import LeaveOpeningBalance, LeaveOpeningStatus

from .schema import LEAVE_OPENING_SCHEMA
from .serializers import LeaveOpeningBalanceSerializer
from .services import LeaveOpeningBalanceService


class LeaveOpeningBalanceViewSet(
    ServiceWriteMixin,
    BaseMasterViewSet,
):
    """
    Saldo cuti awal saat migrasi dari sistem lama.

    `ServiceWriteMixin` wajib: tanpa itu jalur tulisnya
    `serializer.save()` bawaan DRF, dan seluruh isi
    `LeaveOpeningBalanceService` — penurunan tahun, pembekuan tanggal
    hangus, dan sinkronisasi ke kartu saldo — tidak pernah jalan.
    Barisnya tersimpan, kartu saldonya tetap nol, dan tidak ada satu
    pun pesan yang menyebutkannya.
    """

    # Sama persis dengan LeaveBalanceViewSet: seluruh organisasinya
    # lewat penempatan pegawai, baris ini tidak menyimpan satu pun
    # kolom organisasi sendiri.
    data_scope = {
        "company": "employee__organization__company",
        "branch": "employee__organization__branch",
        "location": "employee__organization__location",
        "division": "employee__organization__division",
        "department": "employee__organization__department",
        "section": "employee__organization__section",
        "own": "employee__user_id",
    }

    serializer_class = LeaveOpeningBalanceSerializer
    service_class = LeaveOpeningBalanceService

    framework_module = "hr/leave-opening-balances"
    schema = LEAVE_OPENING_SCHEMA

    search_fields = [
        "employee__employee_number",
        "employee__first_name",
        "employee__last_name",
        "leave_type__name",
        "remark",
    ]

    filterset_fields = [
        "employee",
        "leave_type",
        "year",
        "source",
        "status",
        # Batch go-live disusun per perusahaan, jadi inilah penyaring
        # yang benar-benar dipakai saat Review — dan tanpa didaftarkan
        # di sini parameternya diterima lalu diabaikan diam-diam.
        "employee__organization__company",
    ]

    ordering_fields = [
        "status",
        "opening_date",
        "year",
        "days",
        "expires_at",
        "employee__employee_number",
        "leave_type__name",
        "created_at",
        "updated_at",
    ]

    ordering = [
        "-opening_date",
        "employee__employee_number",
    ]

    def get_queryset(self):
        return (
            LeaveOpeningBalance.objects
            .select_related(
                "employee",
                "leave_type",
                # Keduanya dibaca serializer untuk menurunkan Join Date
                # dan Eligible Date: `employment` memegang tanggal
                # masuknya, `organization` memegang company yang dipakai
                # memilih Leave Policy. Tanpa ini satu halaman 20 baris
                # menembak 40 query tambahan — dan lambatnya baru terasa
                # di tenant yang barisnya ratusan, persis tenant yang
                # sedang bermigrasi.
                "employee__employment",
                "employee__organization",
            )
            .filter(is_deleted=False)
        )

    # ------------------------------------------------------------------
    # Review -> Post
    # ------------------------------------------------------------------

    @action(detail=True, methods=["post"], url_path="post")
    def post_balance(self, request, pk=None):
        """
        Menjadikan angka baris ini saldo pegawainya.

        `url_path` sengaja disebut: nama methodnya tidak boleh `post`
        (itu nama method HTTP milik APIView, dan menimpanya mematikan
        seluruh request POST ke viewset ini).
        """
        instance = self.get_object()

        try:
            instance = self.service_class.post(
                instance=instance,
                user=request.user,
            )
        except DjangoValidationError as exc:
            return error_response(
                message=self._first_message(exc),
                status_code=400,
            )

        return success_response(
            data=self.get_serializer(instance).data,
            message="Opening balance posted successfully.",
        )

    @action(detail=True, methods=["post"], url_path="unpost")
    def unpost_balance(self, request, pk=None):
        instance = self.get_object()

        try:
            instance = self.service_class.unpost(
                instance=instance,
                user=request.user,
            )
        except DjangoValidationError as exc:
            return error_response(
                message=self._first_message(exc),
                status_code=400,
            )

        return success_response(
            data=self.get_serializer(instance).data,
            message="Opening balance withdrawn to draft.",
        )

    @action(detail=False, methods=["post"], url_path="post-all")
    def post_all(self, request):
        """
        Posting massal — jalur yang sebenarnya dipakai saat go-live.

        Dua bentuk body, dan keduanya perlu: `{"ids": [...]}` untuk
        baris yang dipilih di tabel, dan tanpa `ids` untuk **seluruh
        draft yang sedang terlihat** — lewat `filter_queryset`, jadi
        penyaring perusahaan di toolbar ikut berlaku dan
        cakupan data tidak bisa dilewati. Batch migrasi berisi
        ratusan baris; memilih semuanya di tabel berhalaman bukan
        pekerjaan yang bisa diselesaikan siapa pun.
        """
        queryset = self.filter_queryset(self.get_queryset()).filter(
            status=LeaveOpeningStatus.DRAFT,
        )

        ids = request.data.get("ids")

        if ids:
            queryset = queryset.filter(pk__in=ids)

        result = self.service_class.post_many(
            queryset=queryset.select_related("employee", "leave_type"),
            user=request.user,
        )

        message = (
            f"{result['posted']} saldo awal di-post."
            if not result["failed"]
            else (
                f"{result['posted']} saldo awal di-post, "
                f"{result['failed']} gagal."
            )
        )

        return success_response(data=result, message=message)

    @staticmethod
    def _first_message(exc: DjangoValidationError) -> str:
        messages = getattr(exc, "messages", None)

        return messages[0] if messages else str(exc)
