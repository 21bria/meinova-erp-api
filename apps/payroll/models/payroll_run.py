from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel

from .choices import PayrollRunStatus, PayrollRunType
from .payroll_period import PayrollPeriod


# PF-0G. Status yang membuat sebuah run koreksi **menempati slot**
# penerus run yang dikoreksinya. Positif dan lengkap: seluruh status
# kecuali `CANCELLED`.
#
# `REJECTED` ikut menempati slot — run yang ditolak approver masih bisa
# diajukan ulang (`submit()` menerima REJECTED), jadi ia belum berakhir.
# Yang melepaskan slot hanya pembatalan, dan `cancel()` menolak run yang
# sudah FINALIZED — jadi koreksi yang sudah final tidak pernah melepas
# slotnya.
ACTIVE_SUCCESSOR_STATUSES = frozenset(
    {
        PayrollRunStatus.DRAFT,
        PayrollRunStatus.PROCESSING,
        PayrollRunStatus.REVIEW,
        PayrollRunStatus.SUBMITTED,
        PayrollRunStatus.APPROVED,
        PayrollRunStatus.FINALIZED,
        PayrollRunStatus.REJECTED,
    },
)

ACTIVE_SUCCESSOR_STATUS_VALUES = sorted(
    str(status) for status in ACTIVE_SUCCESSOR_STATUSES
)


class PayrollRun(BaseModel):
    """
    Satu pelaksanaan payroll di dalam sebuah periode.

    Inilah dokumennya: yang diajukan ke alur persetujuan, yang dikunci,
    dan yang melahirkan slip. Angka totalnya dibekukan di sini supaya
    daftar run tidak perlu menjumlahkan ribuan baris komponen tiap kali
    layarnya dibuka.
    """

    document_number = models.CharField(max_length=50, blank=True, default="")

    period = models.ForeignKey(
        PayrollPeriod,
        on_delete=models.PROTECT,
        related_name="runs",
    )

    # Disalin dari periode saat dibuat. Bukan denormalisasi malas:
    # cakupan data per baris (kewenangan `RoleAssignment`) menyaring lewat
    # kolom, dan menyaring lewat `period__company` berarti setiap
    # perubahan periode ikut menggeser siapa yang boleh membaca run
    # yang sudah terkunci.
    company = models.ForeignKey(
        "administration.Company",
        on_delete=models.PROTECT,
        related_name="payroll_runs",
    )

    name = models.CharField(max_length=150, blank=True, default="")

    run_type = models.CharField(
        max_length=20,
        choices=PayrollRunType.choices,
        default=PayrollRunType.REGULAR,
    )

    # Penyaring opsional saat men-generate pegawai. Kosong = seluruh
    # company. Disimpan supaya "kenapa orang ini tidak ada di run"
    # bisa dijawab dari dokumennya sendiri, bukan dari ingatan.
    branch = models.ForeignKey(
        "administration.Branch",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="payroll_runs",
    )
    location = models.ForeignKey(
        "administration.Location",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="payroll_runs",
    )
    department = models.ForeignKey(
        "administration.Department",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="payroll_runs",
    )
    section = models.ForeignKey(
        "administration.Section",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="payroll_runs",
    )

    status = models.CharField(
        max_length=20,
        choices=PayrollRunStatus.choices,
        default=PayrollRunStatus.DRAFT,
    )

    employee_count = models.PositiveIntegerField(default=0)

    total_earning = models.DecimalField(
        max_digits=20, decimal_places=2, default=0,
    )
    total_deduction = models.DecimalField(
        max_digits=20, decimal_places=2, default=0,
    )
    total_tax = models.DecimalField(
        max_digits=20, decimal_places=2, default=0,
    )
    total_net = models.DecimalField(
        max_digits=20, decimal_places=2, default=0,
    )

    # Bukan bagian dari `total_earning` maupun `total_deduction`.
    # Laporan biaya tenaga kerja membacanya bersama `total_earning`;
    # laporan transfer bank tidak boleh menyentuhnya sama sekali.
    total_employer_contribution = models.DecimalField(
        max_digits=20, decimal_places=2, default=0,
    )

    # Hasil `PayrollValidationService`, dibekukan apa adanya. Disimpan
    # supaya layar Review menampilkan temuan yang **sama** dengan yang
    # dipakai Finalize — bukan hasil pemeriksaan ulang yang bisa
    # berbeda karena datanya berubah di antaranya.
    validation_summary = models.JSONField(default=dict, blank=True)

    # Peringatan (bukan error) yang sudah diakui. Finalize dengan
    # peringatan tanpa acknowledgement ditolak; itu yang membedakan
    # "sudah dibaca dan diterima" dari "tidak pernah dilihat".
    warnings_acknowledged = models.BooleanField(default=False)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    acknowledged_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )

    calculated_at = models.DateTimeField(null=True, blank=True)
    calculated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )

    submitted_at = models.DateTimeField(null=True, blank=True)
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )

    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )

    finalized_at = models.DateTimeField(null=True, blank=True)
    finalized_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )

    notes = models.TextField(blank=True)

    # PF-0G. Run yang dikoreksi run ini — **satu-satunya** penanda
    # koreksi. `corrects_document_number` sengaja tidak disimpan: nomor
    # dokumen sudah ada di baris yang ditunjuk, dan menyalinnya berarti
    # dua sumber untuk satu fakta yang bisa berselisih. Payload PF-0C
    # menurunkan keduanya dari relasi ini.
    #
    # `PROTECT`: run yang sudah dikoreksi tidak boleh hilang dari jejak
    # koreksinya.
    corrects_run = models.ForeignKey(
        "self",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="corrections",
    )

    class Meta:
        db_table = "payroll_run"
        ordering = ["-created_at"]
        verbose_name = "Payroll Run"
        verbose_name_plural = "Payroll Runs"

        # PF-0G. Menerbitkan run koreksi adalah wewenang **payroll**,
        # terpisah dari `change_payrollrun` (yang dipegang setiap
        # operator yang memfinalisasi) dan dari izin Finance mana pun.
        permissions = [
            ("correct_payrollrun", "Can issue a correction payroll run"),
        ]

        constraints = [
            models.UniqueConstraint(
                fields=["document_number"],
                condition=Q(is_deleted=False) & ~Q(document_number=""),
                name="uniq_active_payroll_run_number",
            ),
            # PF-0G — **satu penerus aktif** per run yang dikoreksi.
            #
            # Syaratnya ditulis **positif** (`status__in`), bukan sebagai
            # negasi: daftar status payroll bisa bertambah, dan
            # `~Q(status="cancelled")` diam-diam menganggap setiap status
            # baru sebagai penerus aktif. Yang positif memaksa keputusan
            # itu dibuat sadar — status baru tidak masuk sampai
            # ditambahkan ke `ACTIVE_SUCCESSOR_STATUSES`.
            #
            # Persis sama dengan aturan service
            # (`PayrollRunService.active_successor`); keduanya membaca
            # konstanta yang sama.
            models.UniqueConstraint(
                fields=["corrects_run"],
                condition=(
                    Q(is_deleted=False)
                    & Q(corrects_run__isnull=False)
                    & Q(status__in=ACTIVE_SUCCESSOR_STATUS_VALUES)
                ),
                name="uniq_active_payroll_run_successor",
            ),
        ]

        indexes = [
            models.Index(
                fields=["period", "status"],
                name="idx_payroll_run_period_status",
            ),
            # Tidak ada indeks tambahan untuk `corrects_run`: kolom FK
            # sudah berindeks sendiri, dan penelusuran rantai koreksi
            # selalu lewat kolom itu.
        ]

    LOCKED_STATUSES = frozenset({PayrollRunStatus.FINALIZED})

    EDITABLE_STATUSES = frozenset(
        {
            PayrollRunStatus.DRAFT,
            PayrollRunStatus.PROCESSING,
            PayrollRunStatus.REVIEW,
            PayrollRunStatus.REJECTED,
        },
    )

    @property
    def is_locked(self) -> bool:
        return self.status in self.LOCKED_STATUSES

    @property
    def is_editable(self) -> bool:
        return self.status in self.EDITABLE_STATUSES

    def clean(self):
        super().clean()

        if self.period_id and self.company_id:
            period_company = getattr(self.period, "company_id", None)

            if period_company and period_company != self.company_id:
                raise ValidationError(
                    {
                        "company": (
                            "Company harus sama dengan company periode."
                        ),
                    },
                )

        self._clean_correction()

    def _clean_correction(self) -> None:
        """
        Aturan relasi koreksi yang berlaku di **setiap** jalur tulis.

        Yang tidak bisa ditegakkan di sini — satu penerus aktif, dan
        pencegahan balapan — ditegakkan constraint database plus
        penguncian baris di `PayrollRunService`.
        """
        if self.corrects_run_id is None:
            if self.run_type == PayrollRunType.CORRECTION:
                raise ValidationError(
                    {
                        "corrects_run": (
                            "Run koreksi harus menyebut run yang "
                            "dikoreksinya."
                        ),
                    },
                )

            return

        if self.run_type != PayrollRunType.CORRECTION:
            raise ValidationError(
                {
                    "corrects_run": (
                        "Hanya run bertipe Correction yang boleh menunjuk "
                        "run yang dikoreksi."
                    ),
                },
            )

        if self.pk and self.corrects_run_id == self.pk:
            raise ValidationError(
                {"corrects_run": "Run tidak bisa mengoreksi dirinya sendiri."},
            )

        target = self.corrects_run

        if target.status != PayrollRunStatus.FINALIZED:
            raise ValidationError(
                {
                    "corrects_run": (
                        f"Run {target.document_number or target.pk} belum "
                        "difinalisasi — yang belum final diperbaiki dengan "
                        "menghitung ulang, bukan dengan run koreksi."
                    ),
                },
            )

        if target.company_id != self.company_id:
            raise ValidationError(
                {"corrects_run": "Run koreksi harus di company yang sama."},
            )

        if target.period_id != self.period_id:
            raise ValidationError(
                {
                    "corrects_run": (
                        "Run koreksi harus berada di periode payroll yang "
                        "sama dengan run yang dikoreksinya."
                    ),
                },
            )

        # Siklus. Dengan "target harus FINALIZED" + relasi yang tidak
        # bisa diubah sesudah dibuat, siklus seharusnya mustahil terjadi
        # menurut urutan waktu — tapi "seharusnya mustahil" bukan
        # penjagaan, dan rantainya pendek.
        seen = {self.pk} if self.pk else set()

        node = target

        while node is not None:
            if node.pk in seen:
                raise ValidationError(
                    {"corrects_run": "Rantai koreksi tidak boleh melingkar."},
                )

            seen.add(node.pk)

            node = node.corrects_run

    def corrected_run_ids(self) -> set[int]:
        """
        Run yang **digantikan** run ini — seluruh rantai pendahulunya.

        PF-0G. Modelnya REPLACEMENT: run koreksi memuat hasil periode itu
        seutuhnya, jadi pegawai yang sama memang muncul lagi di run yang
        sama periodenya. Yang digantikan bukan cuma pendahulu langsung —
        koreksi atas koreksi menggantikan keduanya.

        Dipakai validasi duplikat, dan hanya untuk mengecualikan rantai
        ini sendiri. Run lain di periode yang sama tetap bertabrakan.
        """
        chain: set[int] = set()

        node = self.corrects_run if self.corrects_run_id else None

        while node is not None and node.pk not in chain:
            chain.add(node.pk)

            node = node.corrects_run

        return chain

    def __str__(self) -> str:
        return self.document_number or f"Payroll Run #{self.pk}"
