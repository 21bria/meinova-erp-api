from decimal import Decimal

from django.db.models import Count, Sum

from rest_framework.decorators import action

from apps.core.responses.api import success_response
from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin
from apps.payroll.models import (
    PayrollComponentType,
    PayrollRun,
    PayrollRunComponent,
)
from apps.payroll.scoping import (
    PAYROLL_RUN_SCOPE,
    payable_run_employees,
    visible_findings,
)
from apps.payroll.services import PayrollRunService

from .schema import PAYROLL_RUN_SCHEMA
from .serializers import PayrollRunSerializer


# Nol yang sebentuk dengan kolom uang di database — `Sum` atas queryset
# kosong mengembalikan None, dan "None" tercetak sebagai string adalah
# bug tampilan yang tidak berbunyi.
ZERO = Decimal("0.00")


class PayrollRunViewSet(ServiceWriteMixin, BaseMasterViewSet):
    """
    Dokumen pelaksanaan payroll.

    Cakupan barisnya memakai kolom organisasi milik run itu sendiri
    (`company`/`branch`/`location`), plus `department`/`section` untuk
    run yang memang dipersempit ke sana. Run se-company punya
    `department` kosong, dan `DataScopeService` melewatkan kolom kosong
    sesuai setelan `DATA_SCOPE_INCLUDE_NULL` — perilaku yang sama dengan
    dokumen HR lain.
    """

    # Sensitif: baca ikut menuntut `view_<model>`. Lihat
    # `BaseMasterViewSet.require_view_permission`.
    require_view_permission = True

    # Peta yang sama dipakai `PayrollRunService.assert_may_finalize()`;
    # satu definisi, di `apps/payroll/scoping.py`.
    data_scope = PAYROLL_RUN_SCOPE

    # Mengunci payroll berdampak keuangan, jadi cakupan barisnya
    # dihitung dari izin yang mengotorisasi tindakan itu — bukan dari
    # izin baca yang dipegang role lain milik orang yang sama. Pola yang
    # sama dengan `hr.record_employeeleave` di layar Cuti.
    #
    # Penolakannya sendiri tetap di service
    # (`PayrollRunService.assert_may_finalize`): perintah manajemen dan
    # jalur lain yang menyusul tidak lewat viewset sama sekali.
    action_scope_permissions = {
        "finalize": PayrollRunService.FINALIZE_PERMISSION,
    }

    # Peserta alur boleh membaca dokumen yang ditagihkan kepadanya
    # walau cakupan datanya tidak mencakup baris itu. Tanpa ini,
    # approver Finance yang bercakupan sempit ditagih menyetujui
    # dokumen yang tidak bisa ia buka.
    workflow_document = ("payroll", "payroll_run")

    serializer_class = PayrollRunSerializer
    service_class = PayrollRunService

    framework_module = "payroll/payroll-runs"
    schema = PAYROLL_RUN_SCHEMA

    search_fields = [
        "document_number",
        "name",
        "period__code",
        "period__name",
        "company__name",
    ]

    filterset_fields = [
        "period",
        "company",
        "branch",
        "location",
        "department",
        "section",
        "run_type",
        "status",
    ]

    ordering = ["-created_at"]

    ordering_fields = [
        "document_number",
        "run_type",
        "status",
        "employee_count",
        "total_net",
        "created_at",
        "finalized_at",
    ]

    def get_queryset(self):
        return (
            PayrollRun.objects
            .filter(is_deleted=False)
            .select_related(
                "period",
                "period__payroll_group",
                "company",
                "branch",
                "location",
                "department",
                "section",
            )
        )

    # ------------------------------------------------------------------

    def _user(self, request):
        return request.user if request.user.is_authenticated else None

    def _respond(self, *, instance, message, extra=None):
        instance.refresh_from_db()

        data = {
            "payroll_run": PayrollRunSerializer(
                instance,
                context=self.get_serializer_context(),
            ).data,
        }

        if extra:
            data.update(extra)

        return success_response(data=data, message=message)

    @action(detail=True, methods=["post"], url_path="generate-employees")
    def generate_employees(self, request, pk=None):
        instance = self.get_object()

        result = PayrollRunService.generate_employees(
            run=instance,
            user=self._user(request),
        )

        return self._respond(
            instance=instance,
            message=(
                f"{result['total']} pegawai siap dihitung "
                f"({result['created']} baru, {result['excluded']} "
                "dikeluarkan)."
            ),
            extra={"result": result},
        )

    @action(detail=True, methods=["post"], url_path="calculate")
    def calculate(self, request, pk=None):
        instance = self.get_object()

        result = PayrollRunService.calculate(
            run=instance,
            user=self._user(request),
        )

        return self._respond(
            instance=instance,
            message=(
                f"{result['calculated']} pegawai dihitung, "
                f"{result['failed']} gagal."
            ),
            extra={"result": result},
        )

    @action(detail=True, methods=["post"], url_path="validate")
    def validate_run(self, request, pk=None):
        instance = self.get_object()

        summary = PayrollRunService.validate(
            run=instance,
            user=self._user(request),
        )

        return self._respond(
            instance=instance,
            message=(
                f"{summary['counts']['errors']} error, "
                f"{summary['counts']['warnings']} warning."
            ),
            extra={"validation": summary},
        )

    @action(detail=True, methods=["post"], url_path="acknowledge")
    def acknowledge(self, request, pk=None):
        instance = self.get_object()

        PayrollRunService.acknowledge(
            run=instance,
            user=self._user(request),
        )

        return self._respond(
            instance=instance,
            message="Peringatan diakui.",
        )

    @action(detail=True, methods=["post"], url_path="submit")
    def submit(self, request, pk=None):
        instance = self.get_object()

        PayrollRunService.submit(
            run=instance,
            user=self._user(request),
            notes=request.data.get("notes", ""),
        )

        return self._respond(
            instance=instance,
            message="Payroll run diajukan.",
        )

    @action(detail=True, methods=["post"], url_path="withdraw")
    def withdraw(self, request, pk=None):
        instance = self.get_object()

        PayrollRunService.withdraw(
            run=instance,
            user=self._user(request),
        )

        return self._respond(
            instance=instance,
            message="Pengajuan ditarik kembali.",
        )

    @action(detail=True, methods=["post"], url_path="finalize")
    def finalize(self, request, pk=None):
        instance = self.get_object()

        result = PayrollRunService.finalize(
            run=instance,
            user=self._user(request),
        )

        return self._respond(
            instance=instance,
            message=(
                f"Payroll dikunci. {result['payslips']} slip gaji "
                "diterbitkan."
            ),
            extra={"result": result},
        )

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        instance = self.get_object()

        PayrollRunService.cancel(
            run=instance,
            user=self._user(request),
            notes=request.data.get("notes", ""),
        )

        return self._respond(
            instance=instance,
            message="Payroll run dibatalkan.",
        )

    @action(detail=True, methods=["get"], url_path="summary")
    def summary(self, request, pk=None):
        """
        Rekap satu run: per komponen dan per unit organisasi.

        Dihitung di database, bukan di frontend. Run 500 pegawai punya
        ribuan baris komponen, dan menjumlahkannya di browser berarti
        mengirim seluruhnya lebih dulu.

        **Seluruh angkanya dijumlahkan dari baris yang boleh dibaca
        pemanggilnya**, bukan dari kolom total yang dibekukan di run.

        Sebelumnya tidak begitu, dan itu kebocoran: `run.total_*` dan
        `employee_count` dibekukan atas **seluruh** pegawai run tanpa
        mengenal siapa yang membacanya, sementara agregat komponen dan
        rekap departemen dirakit langsung dari manager — tidak satu pun
        melewati `filter_queryset()` yang menegakkan `data_scope` dan
        `EmployeeDataPolicy`. Akun yang membuka
        `/api/payroll/payroll-run-employees/?run=8` dan mendapat nol
        baris tetap membaca total Rp 132.378.341 di sini.

        Tidak ada percabangan "akses penuh vs sebagian", dan itu
        disengaja: pemegang akses penuh menjumlahkan **baris yang sama
        persis** yang dipakai `_refresh_totals` membekukan
        `run.total_*`, jadi angkanya identik dengan sebelumnya. Cabang
        khusus untuk kasus itu cuma menambah jalur kedua yang bisa
        menyimpang tanpa ada yang menyadarinya.

        Yang tidak boleh dilihat **hilang tanpa jejak** — tidak ada
        "3 pegawai disembunyikan". Penanda seperti itu sendiri sudah
        memberi tahu ada gaji yang tidak terbaca, dan itu setengah dari
        informasinya. Aturan yang sama dengan `EmployeeDataVisibility`
        di tab riwayat pegawai.
        """
        instance = self.get_object()

        lines = payable_run_employees(run=instance, user=request.user)

        totals = lines.aggregate(
            employees=Count("id"),
            earning=Sum("gross_earning"),
            deduction=Sum("total_deduction"),
            tax=Sum("tax_amount"),
            net=Sum("net_pay"),
            employer=Sum("employer_contribution"),
        )

        components = list(
            PayrollRunComponent.objects
            .filter(is_deleted=False, run_employee__in=lines)
            .values("component_type", "code", "name", "source")
            .annotate(total=Sum("amount"))
            .order_by("component_type", "-total")
        )

        by_department = list(
            lines
            .values("department__name")
            .annotate(
                employees=Count("id"),
                gross=Sum("gross_earning"),
                deduction=Sum("total_deduction"),
                net=Sum("net_pay"),
            )
            .order_by("department__name")
        )

        return success_response(
            data={
                "run": {
                    "id": instance.pk,
                    "document_number": instance.document_number,
                    "status": instance.status,
                    "employee_count": totals["employees"] or 0,
                    "total_earning": str(totals["earning"] or ZERO),
                    "total_deduction": str(totals["deduction"] or ZERO),
                    "total_tax": str(totals["tax"] or ZERO),
                    "total_net": str(totals["net"] or ZERO),
                    "total_employer_contribution": str(
                        totals["employer"] or ZERO,
                    ),
                    # Biaya perusahaan, bukan yang dibawa pulang
                    # pegawai. Gross + beban perusahaan — bukan net,
                    # dan bukan gross saja.
                    "total_payroll_cost": str(
                        (totals["earning"] or ZERO)
                        + (totals["employer"] or ZERO),
                    ),
                },
                "earnings": [
                    row for row in components
                    if row["component_type"] == PayrollComponentType.EARNING
                ],
                "deductions": [
                    row for row in components
                    if row["component_type"] == PayrollComponentType.DEDUCTION
                ],
                "employer_contributions": [
                    row for row in components
                    if row["component_type"]
                    == PayrollComponentType.EMPLOYER_CONTRIBUTION
                ],
                "by_department": by_department,
                "validation": visible_findings(
                    summary=instance.validation_summary,
                    visible_employee_ids=lines.values_list(
                        "employee_id",
                        flat=True,
                    ),
                ),
            },
            message="Rekap payroll run.",
        )
