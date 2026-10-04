from __future__ import annotations

from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.framework.tables import TablePage
from apps.framework.views.dashboard import BaseDashboardAPIView

from .schema import HR_EMPLOYEE_REPORTING_AUDIT_SCHEMA
from .services import EmployeeReportingAuditPresenter
from .statuses import REPORTING_STATUS_OPTIONS


class HREmployeeReportingAuditAPIView(BaseDashboardAPIView):
    """
    Employee Reporting Audit — satu tabel, tanpa periode.

    Menumpang runtime dashboard dengan sengaja: filter berjenjang,
    panel Advanced Filter, kotak cari, dan paginasi sisi server sudah
    diselesaikan di `BaseDashboardAPIView` + `TablePage`. Yang
    ditambahkan laporan ini nol runtime baru.

    **Read-only.** Tidak ada satu pun method tulis di sini, dan
    servicenya tidak punya jalan menulis ke Employee, Organization
    Assignment, maupun User. Garis pelaporan diperbaiki di layar
    Employee, bukan dari laporan yang melaporkannya.
    """

    framework_module = "reports/hr/employee-reporting-audit"
    schema = HR_EMPLOYEE_REPORTING_AUDIT_SCHEMA

    presenter = EmployeeReportingAuditPresenter

    def get_period(self, request) -> dict:
        """
        Laporan master tidak punya periode.

        Dikosongkan **di sini**, bukan dibiarkan jatuh ke bulan
        berjalan: bawaan `BaseDashboardAPIView` merakit satu rentang
        tanggal utuh dan mengirimkannya di respons, dan rentang yang
        ikut terkirim untuk laporan yang tidak memakainya adalah
        konfigurasi mati yang terbaca seperti konfigurasi hidup —
        pemanggil berikutnya akan menyangka hasilnya tersaring
        olehnya.
        """
        return {}

    def resolve_employee_reporting_audit(self, *, context, widget):
        """
        Dipaginasi di server, dan ukurannya dibatasi ke
        `page_size_options` di schema — bukan dibaca apa adanya dari
        query string. Satu tenant tiga ribu pegawai plus
        `?page_size=99999` berarti seluruh baris dirakit jadi satu
        respons.
        """
        return self.presenter.employee_table(
            context,
            page=TablePage.from_request(context["request"], widget),
        )


class ReportingStatusLookupAPIView(APIView):
    """
    Dua pilihan tetap untuk dropdown "Reporting Status".

    Tidak lewat `LookupRegistry` karena seluruh lookup di sana
    berdasarkan queryset, dan status ini **tidak punya model** — ia
    lahir dari ada-tidaknya `reports_to` pada baris pegawai. Membuatkan
    tabel referensi untuk dua nilai yang ditentukan kode berarti master
    yang bisa disunting sampai tidak lagi cocok dengan yang dibaca
    querysetnya.

    Bentuk responsnya `{count, next, previous, results}` — dialek yang
    sama dengan `BaseLookupView`, jadi `MLookupSelect` di frontend
    memakannya tanpa perlu tahu bedanya.

    Tidak ada data tenant yang lewat sini, jadi tidak ada cakupan data
    yang perlu ditegakkan; penjagaannya ada di queryset laporannya.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, pk: int | None = None):
        if pk is not None:
            for option in REPORTING_STATUS_OPTIONS:
                if option["id"] == pk:
                    return Response(option)

            return Response(status=404)

        search = str(request.query_params.get("search") or "").strip()

        results = [
            option
            for option in REPORTING_STATUS_OPTIONS
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
