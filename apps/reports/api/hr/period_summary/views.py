from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from apps.core.responses.api import error_response, success_response
from apps.framework.tables import TablePage
from apps.framework.views.dashboard import BaseDashboardAPIView

from .drilldown import (
    EmployeeNotVisible,
    HRPeriodSummaryDrilldown,
    InvalidEmployee,
    UnknownMetric,
    parse_employee_id,
)
from .metrics import Metric
from .schema import HR_PERIOD_SUMMARY_SCHEMA
from .services import HRPeriodSummaryPresenter


class HRPeriodSummaryAPIView(BaseDashboardAPIView):
    """
    Laporan HR Period Summary — satu request, seluruh widget.

    Menumpang runtime dashboard dengan sengaja: pemilih periode, filter
    lookup berjenjang, dan pembagian hasil per `widget.key` sudah
    diselesaikan di sana, dan laporan yang merakit ulang ketiganya cuma
    menambah tempat baru untuk ketidakcocokan.

    **Read-only.** Tidak ada satu pun method tulis di sini, dan
    servicenya tidak punya jalan menulis ke Attendance, Leave, Overtime,
    Roster, maupun Employee.
    """

    framework_module = "reports/hr/period-summary"
    schema = HR_PERIOD_SUMMARY_SCHEMA

    presenter = HRPeriodSummaryPresenter

    # ------------------------------------------------------------------
    # KPI
    # ------------------------------------------------------------------

    def resolve_headcount(self, *, context, widget):
        return self.presenter.headcount(context)

    def resolve_attendance_rate(self, *, context, widget):
        return self.presenter.attendance_rate(context)

    def resolve_present_days(self, *, context, widget):
        return self.presenter.metric_stat(context, Metric.PRESENT)

    def resolve_absent_days(self, *, context, widget):
        return self.presenter.metric_stat(context, Metric.ABSENT)

    def resolve_leave_days(self, *, context, widget):
        return self.presenter.leave_total(context)

    def resolve_overtime_hours(self, *, context, widget):
        return self.presenter.metric_stat(context, Metric.OT_TOTAL)

    # ------------------------------------------------------------------
    # Chart
    # ------------------------------------------------------------------

    def resolve_attendance_trend(self, *, context, widget):
        return self.presenter.attendance_trend(context)

    def resolve_leave_breakdown(self, *, context, widget):
        return self.presenter.leave_breakdown(context)

    def resolve_overtime_trend(self, *, context, widget):
        return self.presenter.overtime_trend(context)

    def resolve_department_comparison(self, *, context, widget):
        return self.presenter.department_comparison(context)

    # ------------------------------------------------------------------
    # Tabel
    # ------------------------------------------------------------------

    def resolve_employee_period_summary(self, *, context, widget):
        """
        Dipaginasi di server, dan **hanya tabelnya**.

        Batas halaman dibaca dari widget-nya sendiri (`page_size`,
        `page_size_options` di schema), bukan dari angka yang dikirim
        pemanggil apa adanya: satu tenant dengan tiga ribu pegawai plus
        `?page_size=99999` berarti seluruh agregasi dirakit jadi satu
        respons, dan yang jatuh bukan cuma laporannya.

        Halaman berikutnya diminta dengan `?widget=employee_period_summary`
        supaya KPI dan chart tidak ikut dihitung ulang untuk jawaban yang
        sama persis.
        """
        return self.presenter.employee_table(
            context,
            page=TablePage.from_request(context["request"], widget),
        )


class HRPeriodSummaryDrilldownAPIView(APIView):
    """
    Rincian satu angka: `?metric=absent&employee=12`.

    Filter dan periodenya dibaca dengan **cara yang sama persis** dengan
    laporannya — kelasnya menumpang `get_context()` milik view di atas,
    bukan memparsing query string sendiri. Kalau tidak, satu filter yang
    besok dijadikan multi-select akan diam-diam diabaikan di sini saja,
    dan rincian yang terbuka berisi baris di luar filter yang sedang
    dipilih di layar.
    """

    permission_classes = [IsAuthenticated]

    MAX_ITEMS = 500

    def get(self, request):
        report = HRPeriodSummaryAPIView()
        report.request = request

        context = report.get_context(request)

        metric = str(request.query_params.get("metric", "")).strip()

        try:
            employee_id = parse_employee_id(
                request.query_params.get("employee_id"),
            )
        except InvalidEmployee:
            return error_response(
                message="employee_id harus berupa id pegawai.",
                status_code=400,
            )

        try:
            data = HRPeriodSummaryDrilldown.resolve(
                context,
                metric=metric,
                employee_id=employee_id,
                limit=self.MAX_ITEMS,
            )
        except UnknownMetric as error:
            return error_response(
                message=str(error),
                status_code=400,
            )
        except EmployeeNotVisible:
            # Satu jawaban untuk "tidak ada" dan "di luar cakupan" —
            # membedakannya membocorkan bahwa id itu ada.
            return error_response(
                message="Pegawai tidak ditemukan pada laporan ini.",
                status_code=404,
            )

        return success_response(
            data=data,
            message="Rincian berhasil dimuat.",
        )
