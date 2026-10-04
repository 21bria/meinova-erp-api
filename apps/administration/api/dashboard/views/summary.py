from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.administration.api.dashboard.services import DashboardSummaryService
from apps.core.responses.api import success_response


class DashboardSummaryAPIView(APIView):
    """
    Seluruh isi beranda dalam satu request: KPI, chart, quick action,
    notifikasi, dan dokumen berjalan.

    Satu endpoint, bukan lima — halaman pertama yang dibuka setiap orang
    setiap pagi tidak boleh menembak lima request hanya untuk render
    awal. Alasannya sama dengan `BaseDashboardAPIView`.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return success_response(
            data=DashboardSummaryService.build(request.user),
            message="Beranda berhasil dimuat.",
        )
