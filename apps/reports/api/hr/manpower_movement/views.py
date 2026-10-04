from __future__ import annotations

from apps.framework.tables import TablePage
from apps.framework.views.dashboard import BaseDashboardAPIView

from .schema import HR_MANPOWER_MOVEMENT_SCHEMA
from .services import ManpowerMovementPresenter


class HRManpowerMovementAPIView(BaseDashboardAPIView):
    """
    Manpower Movement — satu request, seluruh widget.

    Menumpang runtime dashboard dengan sengaja: filter berjenjang,
    panel Advanced Filter, kotak cari, dan paginasi sisi server sudah
    diselesaikan di `BaseDashboardAPIView` + `TablePage`. Yang
    ditambahkan laporan ini nol runtime baru.

    **`get_period()` sengaja tidak ditimpa**, dan itu yang
    membedakannya dari Manpower Summary dan Contract Expiry di sebelah.
    Dua laporan itu adalah potret hari ini, jadi keduanya mengembalikan
    `{}` supaya tidak ada rentang mati yang ikut terkirim. Laporan ini
    justru **hanya punya arti** sebagai selisih antara dua tanggal;
    bawaan `BaseDashboardAPIView` — `?mode=&start=&end=` dengan bulan
    berjalan sebagai default — memang yang dibutuhkan.

    **Read-only.** Tidak ada satu pun method tulis di sini, dan
    servicenya tidak punya jalan menulis ke Employee, Organization
    Assignment, Employment Assignment, maupun Employee Action.
    Pergerakan diperbaiki di layar Employee Action, bukan dari laporan
    yang melaporkannya.
    """

    framework_module = "reports/hr/manpower-movement"
    schema = HR_MANPOWER_MOVEMENT_SCHEMA

    presenter = ManpowerMovementPresenter

    # ------------------------------------------------------------------
    # KPI — baris pertama adalah identitasnya, kiri ke kanan
    # ------------------------------------------------------------------

    def resolve_opening_headcount(self, *, context, widget):
        return self.presenter.opening_headcount(context)

    def resolve_joins(self, *, context, widget):
        return self.presenter.joins(context)

    def resolve_transfers_in(self, *, context, widget):
        return self.presenter.transfers_in(context)

    def resolve_transfers_out(self, *, context, widget):
        return self.presenter.transfers_out(context)

    def resolve_exits(self, *, context, widget):
        return self.presenter.exits(context)

    def resolve_closing_headcount(self, *, context, widget):
        return self.presenter.closing_headcount(context)

    def resolve_net_change(self, *, context, widget):
        return self.presenter.net_change(context)

    def resolve_missing_join_date(self, *, context, widget):
        return self.presenter.missing_join_date(context)

    # ------------------------------------------------------------------
    # Chart
    # ------------------------------------------------------------------

    def resolve_headcount_bridge(self, *, context, widget):
        return self.presenter.headcount_bridge(context)

    def resolve_exit_by_reason(self, *, context, widget):
        return self.presenter.exit_by_reason(context)

    # ------------------------------------------------------------------
    # Tabel
    # ------------------------------------------------------------------

    def resolve_movement_table(self, *, context, widget):
        """
        Dipaginasi di server, dan ukurannya dibatasi ke
        `page_size_options` di schema — bukan dibaca apa adanya dari
        query string.

        Halaman berikutnya diminta dengan `?widget=movement_table`
        supaya delapan KPI dan dua chart di atasnya tidak ikut dihitung
        ulang untuk jawaban yang sama persis.
        """
        return self.presenter.movement_table(
            context,
            page=TablePage.from_request(context["request"], widget),
        )
