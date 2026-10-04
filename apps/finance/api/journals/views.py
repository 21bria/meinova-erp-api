from django.db.models import Prefetch

from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated

from apps.core.responses.api import success_response
from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import PeriodScopedListMixin, ServiceWriteMixin

from apps.finance.api.permissions import FinanceActionPermission
from apps.finance.models import Journal, JournalLine
from apps.finance.services import (
    CHANGE_JOURNAL_PERMISSION,
    JOURNAL_SCOPE,
    POST_JOURNAL_PERMISSION,
    REVERSE_JOURNAL_PERMISSION,
    JournalLineService,
    FinancePostingService,
    FinanceReversalService,
    JournalService,
)

from .schema import JOURNAL_LINE_SCHEMA, JOURNAL_SCHEMA
from .serializers import (
    JournalCancelSerializer,
    JournalLineSerializer,
    JournalPostAllSerializer,
    JournalReverseSerializer,
    JournalSerializer,
    JournalSubmitSerializer,
)


class JournalViewSet(
    PeriodScopedListMixin,
    ServiceWriteMixin,
    BaseMasterViewSet,
):
    """
    Jurnal umum.

    `PeriodScopedListMixin` dipasang paling depan: buku jurnal adalah
    tabel yang tumbuh terus, dan daftar yang bawaannya "seluruh waktu"
    tetap membayar `COUNT(*)` atas jutaan baris walau yang dikirim cuma
    dua puluh. Tanpa `date_from`/`date_to`, daftarnya jatuh ke bulan
    berjalan.
    """

    serializer_class = JournalSerializer
    service_class = JournalService

    framework_module = "finance/journals"
    schema = JOURNAL_SCHEMA

    period_field = "posting_date"

    data_scope = JOURNAL_SCOPE

    # FIN-B1/B2. Setiap aksi dokumen menagih izinnya sendiri, dan
    # cakupan barisnya dihitung **dari izin itu** (`get_object()` →
    # `required_scope_permission`). Yang memutuskan tetap service-nya;
    # `FinanceActionPermission` mencerminkannya sebagai 403 lebih awal
    # dan menolak aksi tulis kustom yang lupa dinyatakan di sini.
    #
    # Setuju/tolak tidak ada di sini: keduanya lewat kotak masuk alur
    # (`WorkflowApprovalService.check_right`).
    action_scope_permissions = {
        "submit": CHANGE_JOURNAL_PERMISSION,
        "withdraw": CHANGE_JOURNAL_PERMISSION,
        "cancel": CHANGE_JOURNAL_PERMISSION,
        "post_journal": POST_JOURNAL_PERMISSION,
        "post_all": POST_JOURNAL_PERMISSION,
        "reverse": REVERSE_JOURNAL_PERMISSION,
    }

    permission_classes = [IsAuthenticated, FinanceActionPermission]

    # Peserta alur boleh **membaca** jurnal yang ditagihkan kepadanya,
    # sekalipun cakupan datanya tidak memuat barisnya. Tanpa ini,
    # approver keuangan yang bercakupan satu perusahaan ditagih
    # menyetujui jurnal yang tidak bisa ia buka — dan yang muncul bukan
    # "tidak berhak" melainkan 404 yang terbaca seperti dokumen hilang.
    workflow_document = ("finance", "journal")

    search_fields = [
        "journal_number",
        "description",
        "source_reference",
        "lines__account__code",
        "lines__account__name",
    ]

    filterset_fields = [
        "company",
        "fiscal_year",
        "accounting_period",
        "journal_type",
        "status",
        "currency",
        "source_module",
        "source_type",
    ]

    ordering_fields = [
        "journal_number",
        "posting_date",
        "document_date",
        "status",
        "total_debit",
        "created_at",
    ]

    ordering = ["-posting_date", "-id"]

    def get_queryset(self):
        return (
            Journal.objects
            .filter(is_deleted=False)
            .select_related(
                "company",
                "fiscal_year",
                "accounting_period",
                "currency",
                "base_currency",
                "reversal_of",
                "reversed_by",
                "posted_by",
            )
            .prefetch_related(
                Prefetch(
                    "lines",
                    queryset=(
                        JournalLine.objects
                        .filter(is_deleted=False)
                        .select_related(
                            "account",
                            "cost_center",
                            "location",
                            "department",
                        )
                        .prefetch_related("dimension_values")
                        .order_by("line_number")
                    ),
                ),
            )
            .distinct()
        )

    # ------------------------------------------------------------------
    # Tulis
    # ------------------------------------------------------------------

    def perform_create(self, serializer):
        lines = serializer.validated_data.pop("line_items", None)

        super().perform_create(serializer)

        journal = serializer.instance

        JournalService.assert_within_scope(
            journal=journal,
            user=self._service_user(),
        )

        if lines is not None:
            JournalService.replace_lines(
                journal=journal,
                lines=lines,
                user=self._service_user(),
            )

            journal.refresh_from_db()

    def perform_update(self, serializer):
        lines = serializer.validated_data.pop("line_items", None)

        # FIN-AJ1: status **dan** asal. Jurnal proyeksi kejadian ditolak
        # sebelum satu kolom pun ditulis. Service-nya menagih hal yang
        # sama (`prepare_update_data`); ini hanya supaya `line_items` tidak
        # sempat disentuh.
        JournalService.assert_content_mutable(
            serializer.instance, action="disunting",
        )

        super().perform_update(serializer)

        journal = serializer.instance

        if lines is not None:
            JournalService.replace_lines(
                journal=journal,
                lines=lines,
                user=self._service_user(),
            )

        JournalService.sync_totals(journal)
        JournalService.assert_within_scope(
            journal=journal,
            user=self._service_user(),
        )

        journal.refresh_from_db()

    # ------------------------------------------------------------------
    # Aksi dokumen
    # ------------------------------------------------------------------

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        payload = JournalSubmitSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        journal = self.get_object()

        instance = JournalService.submit(
            journal=journal,
            user=request.user,
            notes=payload.validated_data["notes"],
        )

        journal.refresh_from_db()

        return success_response(
            data=self.get_serializer(journal).data,
            message=(
                "Journal submitted for approval."
                if instance is not None
                else (
                    "No approval workflow configured for journals in this "
                    "company — the journal is approved and ready to post."
                )
            ),
        )

    @action(detail=True, methods=["post"])
    def withdraw(self, request, pk=None):
        journal = JournalService.withdraw(
            journal=self.get_object(),
            user=request.user,
        )

        journal.refresh_from_db()

        return success_response(
            data=self.get_serializer(journal).data,
            message="Submission withdrawn. The journal is a draft again.",
        )

    @action(detail=True, methods=["post"], url_path="post")
    def post_journal(self, request, pk=None):
        """
        Membukukan jurnal ke buku besar.

        `url_path="post"` sementara nama methodnya `post_journal`:
        `post` bentrok dengan `APIView.post`, dan menimpanya mematikan
        seluruh method POST viewset ini — termasuk `create`.
        """
        result = FinancePostingService.post(
            journal=self.get_object(),
            user=request.user,
        )

        return success_response(
            data=self.get_serializer(result.journal).data,
            message=(
                # Permintaan kedua **bukan** error. Lihat
                # `PostingResult.already_posted`.
                f"Journal {result.journal.journal_number} was already "
                "posted — nothing changed."
                if result.already_posted
                else f"Journal {result.journal.journal_number} posted."
            ),
        )

    @action(detail=True, methods=["post"])
    def reverse(self, request, pk=None):
        payload = JournalReverseSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        reversal = FinanceReversalService.reverse(
            journal=self.get_object(),
            user=request.user,
            posting_date=payload.validated_data.get("posting_date"),
            reason=payload.validated_data["reason"],
        )

        return success_response(
            data=self.get_serializer(reversal).data,
            message=(
                f"Reversal journal {reversal.journal_number} created and "
                "posted."
            ),
        )

    @action(detail=True, methods=["post"])
    def cancel(self, request, pk=None):
        payload = JournalCancelSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        journal = JournalService.cancel(
            journal=self.get_object(),
            user=request.user,
            reason=payload.validated_data["reason"],
        )

        journal.refresh_from_db()

        return success_response(
            data=self.get_serializer(journal).data,
            message="Journal cancelled.",
        )

    # ------------------------------------------------------------------
    # Aksi koleksi
    # ------------------------------------------------------------------

    @action(detail=False, methods=["post"], url_path="post-all")
    def post_all(self, request):
        """
        Memposting banyak jurnal sekaligus.

        Tanpa `ids`, cakupannya **seluruh baris yang lolos
        `filter_queryset()`** — jadi penyaring toolbar ikut berlaku dan
        cakupan data tidak bisa dilewati. Itu bentuk yang sama dengan
        Post All di Leave Opening Balance.
        """
        payload = JournalPostAllSerializer(data=request.data)
        payload.is_valid(raise_exception=True)

        queryset = self.filter_queryset(self.get_queryset())

        ids = payload.validated_data.get("ids")

        if ids:
            queryset = queryset.filter(pk__in=ids)

        result = FinancePostingService.post_many(
            journals=list(queryset),
            user=request.user,
        )

        return success_response(
            data=result,
            message=(
                f"{result['posted']} journal(s) posted, "
                f"{result['already_posted']} already posted, "
                f"{len(result['failed'])} failed."
            ),
        )


class JournalLineViewSet(ServiceWriteMixin, BaseMasterViewSet):
    """
    Baris jurnal, untuk grid di dalam workspace jurnal.

    `ui.create/edit/delete` dimatikan di schema-nya: barisnya hanya
    dibuka dari dalam dokumen induknya, dan daftar rata berisi seluruh
    baris jurnal se-tenant bukan layar yang berguna untuk siapa pun.
    """

    serializer_class = JournalLineSerializer
    service_class = JournalLineService

    framework_module = "finance/journal-lines"
    schema = JOURNAL_LINE_SCHEMA

    # Dimensi inti adalah kolom pada baris ini, jadi petanya langsung —
    # tanpa satu pun join. Inilah imbalan dari memilih arsitektur
    # dimensi hibrida.
    data_scope = {
        "company": "company",
        "branch": "branch",
        "location": "location",
        "division": "division",
        "department": "department",
        "section": "section",
        "cost_center": "cost_center",
    }

    search_fields = ["account__code", "account__name", "description"]

    filterset_fields = [
        "journal",
        "account",
        "company",
        "location",
        "department",
        "cost_center",
        "is_posted",
    ]

    ordering_fields = ["line_number", "posting_date", "debit", "credit"]
    ordering = ["journal_id", "line_number"]

    def get_queryset(self):
        return (
            JournalLine.objects
            .filter(is_deleted=False)
            .select_related(
                "journal",
                "account",
                "cost_center",
                "location",
                "department",
                "transaction_currency",
            )
            .prefetch_related("dimension_values")
        )
