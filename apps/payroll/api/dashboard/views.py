from apps.framework.tables import TablePage
from apps.framework.views.dashboard import BaseDashboardAPIView

from .schema import PAYROLL_DASHBOARD_SCHEMA
from .services import PayrollDashboardService


class PayrollDashboardAPIView(BaseDashboardAPIView):
    """
    Payroll Dashboard — satu request, seluruh widget.

    **Read-only, dan itu bukan kebetulan.** Tidak ada satu method tulis
    pun di sini, dan servicenya tidak punya jalan menulis ke run,
    kebijakan, maupun master mana pun. Payroll diperbaiki di layar yang
    memilikinya; dashboard cuma menunjukkan ke mana harus pergi.

    Nama resolver harus persis `resolve_<key widget>` — itu satu-satunya
    penghubung antara schema dan perhitungannya, dan widget yang
    resolvernya belum ditulis gagal berisik alih-alih tampil kosong.
    """

    framework_module = "payroll/dashboard"
    schema = PAYROLL_DASHBOARD_SCHEMA

    service_class = PayrollDashboardService

    def get_period(self, request) -> dict:
        """
        Dashboard ini tidak punya periode tanggal, dan itu disengaja.

        Yang menentukan angkanya `PayrollPeriod` dan `PayrollRun` —
        dokumen, bukan rentang tanggal. Membiarkan bawaan
        `BaseDashboardAPIView` merakit "1–30 September" lalu
        mengirimkannya di respons berarti mengirim konfigurasi mati yang
        terbaca seperti konfigurasi hidup: pemanggil berikutnya akan
        menyangka totalnya dihitung pada rentang itu, padahal run yang
        dibaca bisa saja periode Juli.

        Alasan yang sama dengan `HRManpowerSummaryAPIView`.
        """
        return {}

    # ------------------------------------------------------------------
    # Kartu KPI
    # ------------------------------------------------------------------

    def resolve_employees(self, *, context, widget):
        return self.service_class.employees(context)

    def resolve_gross_payroll(self, *, context, widget):
        return self.service_class.gross_payroll(context)

    def resolve_total_deduction(self, *, context, widget):
        return self.service_class.total_deduction(context)

    def resolve_net_payroll(self, *, context, widget):
        return self.service_class.net_payroll(context)

    def resolve_overtime(self, *, context, widget):
        return self.service_class.overtime(context)

    def resolve_absence_unpaid(self, *, context, widget):
        return self.service_class.absence_unpaid(context)

    def resolve_employer_contribution(self, *, context, widget):
        return self.service_class.employer_contribution(context)

    def resolve_total_payroll_cost(self, *, context, widget):
        return self.service_class.total_payroll_cost(context)

    # ------------------------------------------------------------------
    # Operasional
    # ------------------------------------------------------------------

    def resolve_run_progress(self, *, context, widget):
        return self.service_class.run_progress(context)

    def resolve_attention(self, *, context, widget):
        return self.service_class.attention(
            context,
            limit=widget.get("limit") or 12,
        )

    def resolve_run_employees(self, *, context, widget):
        """
        Dipaginasi sisi server. Frontend meminta halaman berikutnya
        dengan `?widget=run_employees&page=`, jadi KPI dan chart di
        atasnya tidak ikut dihitung ulang tiap kali halaman digeser.
        """
        return self.service_class.run_employees(
            context,
            page=TablePage.from_request(context["request"], widget),
        )

    # ------------------------------------------------------------------
    # Chart
    # ------------------------------------------------------------------

    def resolve_cost_trend(self, *, context, widget):
        return self.service_class.cost_trend(context)

    def resolve_composition(self, *, context, widget):
        return self.service_class.composition(context)

    # ------------------------------------------------------------------
    # Rincian
    # ------------------------------------------------------------------

    def resolve_by_policy(self, *, context, widget):
        return self.service_class.breakdown(
            context,
            field="payroll_policy__name",
            key="policy",
        )

    def resolve_by_department(self, *, context, widget):
        return self.service_class.breakdown(
            context,
            field="department__name",
            key="department",
        )

    def resolve_by_location(self, *, context, widget):
        return self.service_class.breakdown(
            context,
            field="location__name",
            key="location",
        )
