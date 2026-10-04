from rest_framework.decorators import action
from rest_framework.permissions import IsAuthenticated

from apps.core.responses.api import success_response
from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin
from apps.hr.models import LeaveGoLive

from .schema import LEAVE_GO_LIVE_SCHEMA
from .serializers import LeaveGoLiveSerializer
from .services import LeaveGoLiveService


class LeaveGoLiveViewSet(
    ServiceWriteMixin,
    BaseMasterViewSet,
):
    """
    Langkah pertama implementasi cuti untuk perusahaan yang sudah
    berjalan: menyatakan sejak kapan sistem ini yang berwenang.
    """

    # Barisnya menyebut company sendiri, jadi tidak lewat penempatan
    # pegawai seperti saldo awal. Level di bawah company sengaja tidak
    # ada di peta: go-live bukan keputusan per lokasi, dan kunci yang
    # tidak ada di peta memang dilewati.
    data_scope = {
        "company": "company",
    }

    permission_classes = [IsAuthenticated]

    serializer_class = LeaveGoLiveSerializer
    service_class = LeaveGoLiveService

    framework_module = "hr/leave-go-live"
    schema = LEAVE_GO_LIVE_SCHEMA

    search_fields = [
        "company__code",
        "company__name",
        "notes",
    ]

    filterset_fields = [
        "company",
        "is_active",
    ]

    ordering_fields = [
        "go_live_date",
        "company__name",
        "created_at",
        "updated_at",
    ]

    ordering = ["-go_live_date", "company__name"]

    def get_queryset(self):
        return (
            LeaveGoLive.objects
            .select_related("company")
            .filter(is_deleted=False)
        )

    @action(detail=False, methods=["get"], url_path="current")
    def current(self, request):
        """
        Tanggal go-live yang berlaku, dipakai importer dan layar saldo
        awal untuk mengisi Opening Date tanpa mengetik ulang.

        `?company=<id>` menyempitkan ke satu perusahaan. Tanpa itu,
        seluruh baris yang terlihat dikembalikan — tenant yang
        memindahkan perusahaannya bertahap memang punya lebih dari satu
        tanggal, dan memilih salah satunya di sini berarti menebak.
        """
        queryset = self.filter_queryset(
            self.get_queryset().filter(is_active=True),
        )

        company = request.query_params.get("company")

        if company:
            queryset = queryset.filter(company_id=company)

        rows = [
            {
                "company": row.company_id,
                "company_name": row.company.name,
                "go_live_date": row.go_live_date,
                "cutoff_date": row.cutoff_date,
            }
            for row in queryset
        ]

        return success_response(
            data={"results": rows},
            message="Leave go-live retrieved successfully.",
        )
