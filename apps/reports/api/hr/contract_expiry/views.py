from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.framework.tables import TablePage
from apps.framework.views.dashboard import BaseDashboardAPIView

from .schema import HR_CONTRACT_EXPIRY_SCHEMA
from .services import ContractExpiryPresenter
from .statuses import EXPIRY_STATUS_OPTIONS, RENEWAL_STATUS_OPTIONS


class HRContractExpiryAPIView(BaseDashboardAPIView):
    """
    Contract Expiry — satu request, seluruh widget.

    Menumpang runtime dashboard dengan sengaja: filter berjenjang,
    panel Advanced Filter, kotak cari, dan paginasi sisi server sudah
    diselesaikan di `BaseDashboardAPIView` + `TablePage`. Yang
    ditambahkan laporan ini nol runtime baru.

    **Read-only.** Tidak ada satu pun method tulis di sini, dan
    servicenya tidak punya jalan menulis ke Employee, Employment
    Assignment, maupun Employee Action. Kontrak diperpanjang lewat
    dokumen Employee Action, bukan dari laporan yang melaporkannya.
    """

    framework_module = "reports/hr/contract-expiry"
    schema = HR_CONTRACT_EXPIRY_SCHEMA

    presenter = ContractExpiryPresenter

    def get_period(self, request) -> dict:
        """
        Laporan ini potret satu tanggal, jadi tidak punya periode.

        Dikosongkan **di sini**, bukan dibiarkan jatuh ke bulan
        berjalan: bawaan `BaseDashboardAPIView` merakit satu rentang
        tanggal utuh dan mengirimkannya di respons, dan rentang yang
        ikut terkirim untuk laporan yang tidak memakainya adalah
        konfigurasi mati yang terbaca seperti konfigurasi hidup —
        pemanggil berikutnya akan menyangka sisa harinya dihitung dari
        ujung rentang itu.
        """
        return {}

    # ------------------------------------------------------------------
    # KPI
    # ------------------------------------------------------------------

    def resolve_expired(self, *, context, widget):
        return self.presenter.expired(context)

    def resolve_expiring_30(self, *, context, widget):
        return self.presenter.expiring_30(context)

    def resolve_expiring_60(self, *, context, widget):
        return self.presenter.expiring_60(context)

    def resolve_expiring_90(self, *, context, widget):
        return self.presenter.expiring_90(context)

    def resolve_active_contracts(self, *, context, widget):
        return self.presenter.active_contracts(context)

    # ------------------------------------------------------------------
    # Chart
    # ------------------------------------------------------------------

    def resolve_expiry_timeline(self, *, context, widget):
        return self.presenter.expiry_timeline(context)

    def resolve_expiring_by_department(self, *, context, widget):
        return self.presenter.expiring_by_department(context)

    # ------------------------------------------------------------------
    # Tabel
    # ------------------------------------------------------------------

    def resolve_contract_table(self, *, context, widget):
        """
        Dipaginasi di server, dan ukurannya dibatasi ke
        `page_size_options` di schema — bukan dibaca apa adanya dari
        query string.

        Halaman berikutnya diminta dengan `?widget=contract_table`
        supaya KPI dan dua chart di atasnya tidak ikut dihitung ulang
        untuk jawaban yang sama persis.
        """
        return self.presenter.contract_table(
            context,
            page=TablePage.from_request(context["request"], widget),
        )


class StaticOptionLookupAPIView(APIView):
    """
    Pilihan tetap untuk dropdown yang **tidak punya tabel master**.

    Expiry Status dihitung dari selisih tanggal; Renewal Status
    dibacakan dari status dokumen `EmployeeAction`. Keduanya ditentukan
    kode, dan membuatkan tabel referensi untuk nilai seperti itu berarti
    master yang bisa disunting sampai tidak lagi cocok dengan yang
    dibaca laporannya — bentuk kegagalan yang sudah dihindari
    `reporting_status` di Employee Reporting Audit, dan pola yang sama
    dipakai di sini.

    Bentuk responsnya `{count, next, previous, results}` — dialek yang
    sama dengan `BaseLookupView`, jadi `MLookupSelect` di frontend
    memakannya tanpa perlu tahu bedanya.

    Tidak ada data tenant yang lewat sini, jadi tidak ada cakupan data
    yang perlu ditegakkan; penjagaannya ada di queryset laporannya.
    """

    permission_classes = [IsAuthenticated]

    options: tuple[dict, ...] = ()

    def get(self, request, pk: int | None = None):
        if pk is not None:
            for option in self.options:
                if option["id"] == pk:
                    return Response(option)

            return Response(status=404)

        search = str(request.query_params.get("search") or "").strip()

        results = [
            option
            for option in self.options
            if not search
            or search.casefold() in option["name"].casefold()
        ]

        return Response(
            {
                "count": len(results),
                "next": None,
                "previous": None,
                "results": results,
            }
        )


class ExpiryStatusLookupAPIView(StaticOptionLookupAPIView):
    options = EXPIRY_STATUS_OPTIONS


class RenewalStatusLookupAPIView(StaticOptionLookupAPIView):
    options = RENEWAL_STATUS_OPTIONS
