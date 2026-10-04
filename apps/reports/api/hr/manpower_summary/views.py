from __future__ import annotations

from apps.framework.tables import TablePage
from apps.framework.views.dashboard import BaseDashboardAPIView

from .schema import HR_MANPOWER_SUMMARY_SCHEMA
from .services import ManpowerSummaryPresenter


class HRManpowerSummaryAPIView(BaseDashboardAPIView):
    """
    Manpower Summary — satu request, seluruh widget.

    Menumpang runtime dashboard dengan sengaja: filter berjenjang,
    panel Advanced Filter, kotak cari, dan paginasi sisi server sudah
    diselesaikan di `BaseDashboardAPIView` + `TablePage`. Yang
    ditambahkan laporan ini nol runtime baru.

    **Read-only.** Tidak ada satu pun method tulis di sini, dan
    servicenya tidak punya jalan menulis ke Employee, Organization
    Assignment, maupun Employment Assignment. Komposisi manpower
    diperbaiki di layar Employee, bukan dari laporan yang melaporkannya.
    """

    framework_module = "reports/hr/manpower-summary"
    schema = HR_MANPOWER_SUMMARY_SCHEMA

    presenter = ManpowerSummaryPresenter

    def get_period(self, request) -> dict:
        """
        Laporan ini potret hari ini, jadi tidak punya periode.

        Dikosongkan **di sini**, bukan dibiarkan jatuh ke bulan
        berjalan: bawaan `BaseDashboardAPIView` merakit satu rentang
        tanggal utuh dan mengirimkannya di respons, dan rentang yang
        ikut terkirim untuk laporan yang tidak memakainya adalah
        konfigurasi mati yang terbaca seperti konfigurasi hidup —
        pemanggil berikutnya akan menyangka headcount-nya dihitung
        pada rentang itu.
        """
        return {}

    # ------------------------------------------------------------------
    # KPI
    # ------------------------------------------------------------------

    def resolve_headcount(self, *, context, widget):
        return self.presenter.headcount(context)

    def resolve_permanent(self, *, context, widget):
        return self.presenter.permanent(context)

    def resolve_contract(self, *, context, widget):
        return self.presenter.contract(context)

    def resolve_unspecified_employment_type(self, *, context, widget):
        return self.presenter.unspecified_employment_type(context)

    # ------------------------------------------------------------------
    # Breakdown
    # ------------------------------------------------------------------

    def resolve_company_breakdown(self, *, context, widget):
        return self.presenter.company_breakdown(context)

    def resolve_location_breakdown(self, *, context, widget):
        return self.presenter.location_breakdown(context)

    def resolve_department_breakdown(self, *, context, widget):
        return self.presenter.department_breakdown(context)

    def resolve_employee_group_breakdown(self, *, context, widget):
        return self.presenter.employee_group_breakdown(context)

    def resolve_employment_type_breakdown(self, *, context, widget):
        return self.presenter.employment_type_breakdown(context)

    # ------------------------------------------------------------------
    # Tabel
    # ------------------------------------------------------------------

    def resolve_manpower_table(self, *, context, widget):
        """
        Dipaginasi di server, dan ukurannya dibatasi ke
        `page_size_options` di schema — bukan dibaca apa adanya dari
        query string.

        Halaman berikutnya diminta dengan `?widget=manpower_table`
        supaya KPI dan lima chart di atasnya tidak ikut dihitung ulang
        untuk jawaban yang sama persis.
        """
        return self.presenter.manpower_table(
            context,
            page=TablePage.from_request(context["request"], widget),
        )
