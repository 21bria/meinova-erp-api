"""
Endpoint modul roster.

Tiga resource, dan pembagiannya mengikuti tiga keputusan yang berbeda:

* ``roster-setups``       — menetapkan jadwal awal (bulk, sekali per site)
* ``roster-adjustments``  — mengubah jadwal yang sudah berjalan
* ``rotation-credits``    — ledger saldo yang lahir dari kelebihan kerja

Yang **tidak** ada di sini: endpoint untuk menyunting segmen satu per
satu. Itu disengaja — segmen tidak pernah disunting di tempat, dan
menyediakan jalurnya akan membuka persis yang dilarang desainnya.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db.models import Prefetch, Q

from rest_framework.decorators import action

from apps.accounts.permissions import view_permission_for
from apps.accounts.scoping import DataScopeService
from apps.core.responses.api import created_response, success_response
from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin

from apps.hr.api.roster.adjustment_service import RosterAdjustmentService
from apps.hr.api.roster.credit_service import RotationCreditService
from apps.hr.api.roster.services import RosterGenerationService
from apps.hr.api.roster.setup_service import (
    RosterSetupLineService,
    RosterSetupService,
)
from apps.hr.models import (
    Employee,
    RosterAdjustment,
    RosterSetupLine,
    RosterSetupRequest,
    RotationCreditTransaction,
)

from .schema import (
    ROSTER_ADJUSTMENT_SCHEMA,
    ROSTER_SETUP_LINE_SCHEMA,
    ROSTER_SETUP_SCHEMA,
    ROTATION_CREDIT_SCHEMA,
)
from .serializers import (
    RosterAdjustmentSerializer,
    RosterSetupLineSerializer,
    RosterSetupSerializer,
    RotationCreditBalanceSerializer,
    RotationCreditSerializer,
)


# Peta cakupan yang dipakai seluruh resource roster. Disamakan persis
# dengan `SiteRotationViewSet` — kalau salah satu diubah, yang lain
# harus ikut, kalau tidak jumlah baris di dua layar tidak cocok dan
# selisihnya justru memberi tahu ada yang disembunyikan.
ROSTER_SCOPE = {
    "company": "company",
    "branch": "branch",
    "location": "location",
    "division": "employee__organization__division",
    "department": "employee__organization__department",
    "section": "employee__organization__section",
    "own": "employee__user_id",
}


def _user(request):
    return request.user if request.user.is_authenticated else None


def _is_allowed(value, allowed_ids: set) -> bool:
    """Id kiriman klien bisa berupa string; disamakan dulu ke int."""
    try:
        return int(value) in allowed_ids
    except (TypeError, ValueError):
        return False


# ----------------------------------------------------------------------
# Setup massal
# ----------------------------------------------------------------------


class RosterSetupViewSet(ServiceWriteMixin, BaseMasterViewSet):
    data_scope = {
        "company": "company",
        "branch": "location__branch",
        "location": "location",
        "department": "department",
        "section": "section",
    }

    serializer_class = RosterSetupSerializer
    service_class = RosterSetupService

    framework_module = "hr/roster-setups"
    schema = ROSTER_SETUP_SCHEMA

    search_fields = [
        "document_number",
        "location__name",
        "section__name",
        "notes",
    ]

    filterset_fields = [
        "document_number",
        "company",
        "location",
        "department",
        "section",
        "status",
        "as_of_date",
    ]

    ordering_fields = [
        "document_number",
        "as_of_date",
        "status",
        "created_at",
        "updated_at",
    ]

    ordering = ["-as_of_date", "-id"]

    def get_queryset(self):
        return (
            RosterSetupRequest.objects
            .select_related("company", "location", "department", "section")
            .prefetch_related(
                Prefetch(
                    "lines",
                    queryset=RosterSetupLine.objects
                    .filter(is_deleted=False)
                    .select_related("employee", "roster_policy"),
                ),
            )
            .filter(is_deleted=False)
        )

    # ------------------------------------------------------------------
    # Kandidat pegawai
    # ------------------------------------------------------------------

    @action(detail=True, methods=["get"], url_path="candidates")
    def candidates(self, request, pk=None):
        """
        Pegawai yang boleh masuk dokumen ini, dari kursi pemanggilnya.

        Daftarnya **milik service** (`eligible_employees`), bukan
        dirakit di sini: `add-employees` memakai daftar yang sama persis
        untuk memutuskan id mana yang diterima. Kalau dipisah, dropdown
        dan penjagaan akan berbeda — dan yang melebar adalah yang
        menerima id kiriman klien.
        """
        setup = self.get_object()

        queryset = RosterSetupService.eligible_employees(
            request=setup,
            user=_user(request),
        )

        search = str(request.query_params.get("search", "")).strip()

        if search:
            # `Q`, bukan dua queryset yang di-OR: menggabungkan dua
            # queryset ber-`exclude` menghasilkan join yang bisa
            # memunculkan baris yang sama dua kali, dan duplikat di
            # dropdown pegawai tidak terlihat seperti bug — terlihat
            # seperti dua orang bernama sama.
            queryset = queryset.filter(
                Q(employee_number__icontains=search)
                | Q(first_name__icontains=search)
                | Q(last_name__icontains=search),
            )

        taken = set(
            setup.lines
            .filter(is_deleted=False)
            .values_list("employee_id", flat=True)
        )

        return success_response(
            data={
                "results": [
                    {
                        "value": employee.pk,
                        "label": (
                            f"{employee.employee_number} — "
                            f"{employee.full_name}"
                        ),
                        "employee_name": employee.full_name,
                        "employee_number": employee.employee_number,
                        "section": getattr(
                            getattr(employee, "organization", None),
                            "section_id",
                            None,
                        ),
                        "roster_policy": getattr(
                            getattr(employee, "employment", None),
                            "roster_policy_id",
                            None,
                        ),
                        "roster_cycle_start": getattr(
                            getattr(employee, "employment", None),
                            "roster_cycle_start",
                            None,
                        ),
                        # Atasan langsungnya ikut, dan itu bukan
                        # hiasan: satu dokumen hanya boleh memuat satu
                        # atasan (lihat `batch_approver_findings`), jadi
                        # tanpa kolom ini penyusun batch baru tahu
                        # batch-nya bercabang **sesudah** tiga puluh
                        # nama dipilih.
                        "reports_to": getattr(
                            getattr(
                                getattr(employee, "organization", None),
                                "reports_to",
                                None,
                            ),
                            "employee_number",
                            None,
                        ),
                        "already_added": employee.pk in taken,
                    }
                    for employee in queryset[:500]
                ],
            },
            message="Kandidat pegawai.",
        )

    @action(detail=True, methods=["post"], url_path="add-employees")
    def add_employees(self, request, pk=None):
        """
        Menambahkan banyak pegawai sekaligus.

        Body: ``{"employee_ids": [1, 2, 3]}``

        Policy dan Current Cycle Start diambil dari penempatan masing
        masing — bisa dikoreksi per baris sesudahnya, karena justru di
        situ perbedaannya: satu batch, tiga puluh jangkar yang berbeda.
        """
        setup = self.get_object()

        RosterSetupService.assert_editable(setup)

        raw = request.data.get("employee_ids") or []

        if not isinstance(raw, (list, tuple)) or not raw:
            raise ValidationError(
                {
                    "employee_ids": (
                        "Sebutkan minimal satu pegawai."
                    ),
                },
            )

        # Disaring jadi bilangan **sebelum** menyentuh queryset: satu
        # nilai yang bukan angka membuat `pk__in` melempar `ValueError`
        # dan endpoint-nya membalas 500 — kegagalan server untuk
        # masukan yang jelas-jelas salah dari klien.
        wanted = []

        for value in raw:
            try:
                wanted.append(int(value))
            except (TypeError, ValueError):
                continue

        existing = set(
            setup.lines
            .filter(is_deleted=False)
            .values_list("employee_id", flat=True)
        )

        # **Daftar yang sama persis dengan dropdown-nya**, dan bukan
        # sekadar pengulangan: yang di sana menyusun pilihan, yang di
        # sini menerima id kiriman klien. Layar boleh saja menawarkan
        # yang benar; id yang dikirim tetap bisa apa saja, dan tanpa
        # baris ini pegawai kantor pusat, pegawai site sebelah, atau
        # pegawai di luar cakupan pembuatnya bisa masuk lewat satu
        # request yang tidak melewati dropdown mana pun.
        employees = list(
            RosterSetupService.eligible_employees(
                request=setup,
                user=_user(request),
            ).filter(pk__in=wanted),
        )

        allowed_ids = {employee.pk for employee in employees}

        created = 0
        skipped = 0

        for employee in employees:
            if employee.pk in existing:
                skipped += 1

                continue

            RosterSetupLineService.create(
                data={"request": setup, "employee": employee},
                user=_user(request),
            )

            created += 1

        # Id yang dikirim tapi tidak layak dilaporkan apa adanya —
        # diam-diam melewatkannya membuat "5 pegawai ditambahkan" untuk
        # sepuluh id terbaca seperti berhasil seluruhnya.
        rejected = [
            value
            for value in raw
            if not _is_allowed(value, allowed_ids)
        ]

        # Dibaca ulang dari queryset, bukan memakai `setup` yang sudah di
        # tangan: `get_object()` mem-prefetch `lines` **sebelum** baris
        # barunya dibuat, dan `get_line_count` membaca cache prefetch
        # itu. Tanpa ini responsnya membalas "2 pegawai ditambahkan"
        # bersama `line_count: 0` — dan yang dilihat pengguna cuma angka
        # nol, jadi fiturnya terbaca gagal padahal barisnya tersimpan.
        fresh = self.get_queryset().get(pk=setup.pk)

        return created_response(
            data=self.get_serializer(fresh).data,
            message=(
                f"{created} pegawai ditambahkan"
                + (f", {skipped} sudah ada" if skipped else "")
                + (
                    f", {len(rejected)} ditolak (di luar site, "
                    "department/section, cakupan Anda, atau sudah punya "
                    "rencana berjalan)."
                    if rejected
                    else "."
                )
            ),
        )

    # ------------------------------------------------------------------
    # Preview → submit → commit
    # ------------------------------------------------------------------

    @action(detail=True, methods=["get"], url_path="preview")
    def preview(self, request, pk=None):
        setup = self.get_object()

        result = RosterSetupService.preview(request=setup)

        # Temuan **dokumen** ikut ke dalam pesannya, bukan cuma temuan
        # baris. Layar Roster Setup menampilkan hasil Preview sebagai
        # satu toast, jadi "0 bermasalah" pada dokumen yang mejanya
        # bercabang terbaca seperti siap diajukan — lalu Submit-nya
        # ditolak dengan alasan yang tidak pernah muncul di preview.
        blockers = [
            item["message"]
            for item in (
                result["document_validations"]
                + result["workflow_validations"]
            )
            if item["level"] == "blocking"
        ]

        summary = (
            f"{result['total_lines']} baris ditinjau; "
            f"{result['blocking_lines']} bermasalah."
        )

        return success_response(
            data=result,
            message=(
                summary
                if not blockers
                else f"{summary} Belum bisa diajukan — "
                + " ".join(blockers)
            ),
        )

    @action(detail=True, methods=["post"], url_path="submit")
    def submit(self, request, pk=None):
        setup = self.get_object()

        instance = RosterSetupService.submit(
            request=setup,
            user=_user(request),
        )

        # `refresh_from_db()` memuat ulang kolomnya, **bukan** cache
        # prefetch `lines` — dan `line_count`/`committed_count` dibaca
        # dari sana. Dibaca ulang lewat queryset supaya angkanya
        # menggambarkan keadaan sesudah aksi, bukan sebelumnya.
        setup = self.get_queryset().get(pk=setup.pk)

        return success_response(
            data={
                "setup": self.get_serializer(setup).data,
                "workflow_instance": instance.pk,
            },
            message="Dokumen diajukan ke alur persetujuan.",
        )

    @action(detail=True, methods=["post"], url_path="withdraw")
    def withdraw(self, request, pk=None):
        setup = self.get_object()

        RosterSetupService.withdraw(request=setup, user=_user(request))

        setup = self.get_queryset().get(pk=setup.pk)

        return success_response(
            data=self.get_serializer(setup).data,
            message="Pengajuan ditarik; dokumen kembali ke Draft.",
        )

    @action(detail=True, methods=["post"], url_path="commit")
    def commit(self, request, pk=None):
        """
        Menerbitkan (atau mengulang) rencana untuk tiap baris.

        Aman ditekan berkali-kali: baris yang sudah berhasil dilewati.
        """
        setup = self.get_object()

        RosterSetupService.commit(request=setup, user=_user(request))

        setup = self.get_queryset().get(pk=setup.pk)

        return success_response(
            data=self.get_serializer(setup).data,
            message=(
                setup.commit_error
                or "Seluruh baris berhasil diterbitkan."
            ),
        )


class RosterSetupLineViewSet(ServiceWriteMixin, BaseMasterViewSet):
    data_scope = {
        "company": "request__company",
        "location": "request__location",
        "department": "request__department",
        "section": "request__section",
        "own": "employee__user_id",
    }

    serializer_class = RosterSetupLineSerializer
    service_class = RosterSetupLineService

    framework_module = "hr/roster-setup-lines"
    schema = ROSTER_SETUP_LINE_SCHEMA

    search_fields = [
        "employee__employee_number",
        "employee__first_name",
        "employee__last_name",
        "note",
    ]

    filterset_fields = [
        "request",
        "employee",
        "roster_policy",
        "status",
    ]

    ordering_fields = [
        "current_cycle_start",
        "status",
        "employee__employee_number",
    ]

    ordering = ["request", "employee__employee_number"]

    def get_queryset(self):
        return (
            RosterSetupLine.objects
            .select_related(
                "request",
                "employee",
                "employee__organization",
                "employee__employment",
                "roster_policy",
            )
            .filter(is_deleted=False)
        )

    @action(detail=True, methods=["get"], url_path="preview")
    def preview(self, request, pk=None):
        """Jadwal satu baris — dipakai saat menyunting di grid."""
        line = self.get_object()

        return success_response(
            data=RosterGenerationService.preview(
                employee=line.employee,
                policy=line.roster_policy,
                cycle_start=line.current_cycle_start,
                horizon_months=line.request.horizon_months,
                as_of_date=line.request.as_of_date,
            ),
            message="Preview jadwal.",
        )


# ----------------------------------------------------------------------
# Penyesuaian
# ----------------------------------------------------------------------


class RosterAdjustmentViewSet(ServiceWriteMixin, BaseMasterViewSet):
    data_scope = ROSTER_SCOPE

    serializer_class = RosterAdjustmentSerializer
    service_class = RosterAdjustmentService

    framework_module = "hr/roster-adjustments"
    schema = ROSTER_ADJUSTMENT_SCHEMA

    search_fields = [
        "document_number",
        "employee__employee_number",
        "employee__first_name",
        "employee__last_name",
        "reason",
        "reference",
    ]

    filterset_fields = [
        "document_number",
        "plan",
        "employee",
        "company",
        "branch",
        "location",
        "adjustment_kind",
        "credit_impact",
        "status",
        "effective_date",
    ]

    ordering_fields = [
        "document_number",
        "effective_date",
        "adjustment_kind",
        "status",
        "applied_at",
        "created_at",
    ]

    ordering = ["-effective_date", "-id"]

    def get_queryset(self):
        return (
            RosterAdjustment.objects
            .select_related(
                "plan",
                "employee",
                "employee__organization",
                "company",
                "branch",
                "location",
                "segment",
                "resulting_version",
            )
            .filter(is_deleted=False)
        )

    @action(detail=True, methods=["get"], url_path="preview")
    def preview(self, request, pk=None):
        """
        Jadwal sesudah penyesuaian, tanpa menulis apa pun.

        Perhitungannya sama persis dengan yang dipakai saat diterapkan —
        satu `compute()`, bukan dua jalur yang harus dijaga tetap sama.
        """
        adjustment = self.get_object()

        return success_response(
            data=RosterAdjustmentService.preview(adjustment=adjustment),
            message="Dampak penyesuaian.",
        )

    @action(detail=True, methods=["post"], url_path="submit")
    def submit(self, request, pk=None):
        adjustment = self.get_object()

        instance = RosterAdjustmentService.submit(
            adjustment=adjustment,
            user=_user(request),
        )

        adjustment.refresh_from_db()

        return success_response(
            data={
                "adjustment": self.get_serializer(adjustment).data,
                "workflow_instance": instance.pk,
            },
            message="Penyesuaian diajukan ke alur persetujuan.",
        )

    @action(detail=True, methods=["post"], url_path="withdraw")
    def withdraw(self, request, pk=None):
        adjustment = self.get_object()

        RosterAdjustmentService.withdraw(
            adjustment=adjustment,
            user=_user(request),
        )

        adjustment.refresh_from_db()

        return success_response(
            data=self.get_serializer(adjustment).data,
            message="Pengajuan ditarik; dokumen kembali ke Draft.",
        )

    @action(detail=True, methods=["post"], url_path="apply")
    def apply(self, request, pk=None):
        """
        Mengulang penerapan yang gagal.

        Idempoten: dokumen yang sudah diterapkan dikembalikan apa
        adanya, bukan diterapkan lagi.
        """
        adjustment = self.get_object()

        RosterAdjustmentService.apply(
            adjustment=adjustment,
            user=_user(request),
        )

        adjustment.refresh_from_db()

        return success_response(
            data=self.get_serializer(adjustment).data,
            message="Penyesuaian diterapkan.",
        )


# ----------------------------------------------------------------------
# Rotation credit
# ----------------------------------------------------------------------


class RotationCreditViewSet(BaseMasterViewSet):
    """
    Ledger rotation credit.

    Sengaja **tanpa** `ServiceWriteMixin`: penulisannya lewat action
    yang bernama (`record` untuk penyesuaian manual, `reverse` untuk
    pembatalan), bukan lewat POST/PUT/DELETE bawaan. `update` dan
    `destroy` dimatikan di `http_method_names` — service-nya sudah
    melempar, ini yang membuat jalurnya tidak ada sejak awal.
    """

    http_method_names = ["get", "post", "head", "options"]

    data_scope = {
        "company": "employee__organization__company",
        "branch": "employee__organization__branch",
        "location": "employee__organization__location",
        "division": "employee__organization__division",
        "department": "employee__organization__department",
        "section": "employee__organization__section",
        "own": "employee__user_id",
    }

    serializer_class = RotationCreditSerializer

    framework_module = "hr/rotation-credits"
    schema = ROTATION_CREDIT_SCHEMA

    search_fields = [
        "employee__employee_number",
        "employee__first_name",
        "employee__last_name",
        "reason",
        "source_type",
    ]

    filterset_fields = [
        "employee",
        "entry_type",
        "plan",
        "effective_date",
        "source_type",
    ]

    ordering_fields = [
        "effective_date",
        "transaction_date",
        "entry_type",
        "days",
        "employee__employee_number",
    ]

    ordering = ["-effective_date", "-id"]

    def get_queryset(self):
        return (
            RotationCreditTransaction.objects
            .select_related(
                "employee",
                "employee__organization",
                "plan",
                "reverses",
            )
            .prefetch_related("reversed_by")
            .filter(is_deleted=False)
        )

    def bulk_delete(self, request):
        """
        Ditutup, dan harus ditutup **di server**.

        `http_method_names` mengizinkan POST (dibutuhkan `create` dan
        `reverse/`), jadi action `bulk-delete/` bawaan `BaseMasterViewSet`
        tetap terdaftar dan tetap bisa ditembak langsung — mematikan
        tombolnya di schema tidak menghalangi siapa pun. Ledger
        append-only berarti append-only lewat jalur mana pun.
        """
        raise ValidationError(
            {
                "ledger": (
                    "Transaksi rotation credit tidak bisa dihapus. Pakai "
                    "Reversal — jejak 'pernah dicatat lalu dibatalkan' "
                    "justru yang paling dicari saat angkanya "
                    "dipersoalkan."
                ),
            },
        )

    def create(self, request, *args, **kwargs):
        """
        Mencatat transaksi manual (penyesuaian, kedaluwarsa, saldo
        awal).

        Lewat service, bukan `serializer.save()`: plafon, saldo negatif,
        dan penghitungan ulang saldo semuanya ada di sana, dan
        melewatinya berarti angka yang menembus aturan tanpa suara.
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        data = serializer.validated_data

        entry = RotationCreditService.record(
            employee=data["employee"],
            entry_type=data["entry_type"],
            days=data["days"],
            effective_date=data.get("effective_date"),
            reason=data.get("reason", ""),
            plan=data.get("plan"),
            segment=data.get("segment"),
            source_type=data.get("source_type", "manual"),
            source_id=data.get("source_id", ""),
            user=_user(request),
        )

        return created_response(
            data=self.get_serializer(entry).data,
            message="Transaksi dicatat.",
        )

    @action(detail=True, methods=["post"], url_path="reverse")
    def reverse_entry(self, request, pk=None):
        entry = self.get_object()

        reversal = RotationCreditService.reverse(
            entry=entry,
            reason=str(request.data.get("reason", "")).strip(),
            user=_user(request),
        )

        return created_response(
            data=self.get_serializer(reversal).data,
            message="Transaksi dibatalkan lewat baris pembalikan.",
        )

    @action(detail=False, methods=["get"], url_path="balances")
    def balances(self, request):
        """
        Saldo per pegawai.

        Dibaca dari cache `RotationCreditBalance`, yang dihitung ulang
        dari ledger setiap kali ada transaksi — bukan dijumlahkan di
        sini, supaya bisa disortir dan difilter langsung di tabel.
        """
        from apps.hr.models import RotationCreditBalance

        queryset = DataScopeService.filter(
            RotationCreditBalance.objects
            .select_related("employee", "employee__organization")
            .filter(is_deleted=False),
            {
                "company": "employee__organization__company",
                "branch": "employee__organization__branch",
                "location": "employee__organization__location",
                "division": "employee__organization__division",
                "department": "employee__organization__department",
                "section": "employee__organization__section",
                "own": "employee__user_id",
            },
            request.user,
            required_permission=view_permission_for(
                RotationCreditBalance,
            ),
        )

        employee = request.query_params.get("employee")

        if employee:
            queryset = queryset.filter(employee_id=employee)

        page = self.paginate_queryset(queryset)

        serializer = RotationCreditBalanceSerializer(
            page if page is not None else queryset,
            many=True,
        )

        if page is not None:
            return self.get_paginated_response(serializer.data)

        return success_response(
            data=serializer.data,
            message="Saldo rotation credit.",
        )

    @action(detail=False, methods=["post"], url_path="convert-preview")
    def convert_preview(self, request):
        """
        Berapa kredit yang lahir dari sekian hari kerja lebih.

        Dipakai form penyesuaian supaya angkanya terlihat **sebelum**
        dokumennya diajukan — "kenapa cuma dapat 2" harus punya jawaban
        di layar yang sama.
        """
        employee_id = request.data.get("employee")
        days = request.data.get("days")

        employee = (
            Employee.objects
            .filter(pk=employee_id, is_deleted=False)
            .select_related("employment", "organization")
            .first()
        )

        if employee is None:
            raise ValidationError(
                {"employee": "Pegawai tidak ditemukan."},
            )

        conversion = RotationCreditService.convert_for_employee(
            employee=employee,
            excess_days=days,
        )

        return success_response(
            data=conversion.as_dict(),
            message=conversion.reason,
        )
