from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel

from .choices import PayrollPeriodStatus
from .payroll_group import PayrollGroup


class PayrollPeriod(BaseModel):
    """
    Satu rentang penggajian untuk satu company × payroll group.

    **Periode adalah kalendernya, run adalah prosesnya.** Satu periode
    bisa melahirkan beberapa run (reguler, off-cycle THR, koreksi), dan
    `status` di sini merangkum keadaan run-run itu — ditulis
    `PayrollRunService`, tidak diketik orang. Dua mesin status yang
    sama-sama digerakkan tangan adalah cara membuat periode berkata
    APPROVED sementara run-nya masih dihitung ulang.
    """

    company = models.ForeignKey(
        "administration.Company",
        on_delete=models.PROTECT,
        related_name="payroll_periods",
    )

    payroll_group = models.ForeignKey(
        PayrollGroup,
        on_delete=models.PROTECT,
        related_name="periods",
    )

    code = models.CharField(max_length=30)
    name = models.CharField(max_length=150)

    start_date = models.DateField()
    end_date = models.DateField()

    # Batas terakhir data transaksi (absensi, lembur, input) diambil.
    # Kosong = sama dengan tanggal akhir periode.
    cutoff_date = models.DateField(null=True, blank=True)

    payment_date = models.DateField(null=True, blank=True)

    status = models.CharField(
        max_length=20,
        choices=PayrollPeriodStatus.choices,
        default=PayrollPeriodStatus.DRAFT,
    )

    # Pembagi proration. Kosong = dihitung dari jumlah hari kalender
    # periode; diisi = angka itu yang dipakai (banyak perusahaan memakai
    # 21 atau 22 hari kerja tetap, dan hasilnya harus sama tiap bulan
    # tanpa bergantung berapa hari Minggu jatuh di bulan itu).
    working_days = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text=(
            "Hari kerja pembagi proration. Kosong = jumlah hari "
            "kalender periode."
        ),
    )

    locked_at = models.DateTimeField(null=True, blank=True)
    locked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )

    notes = models.TextField(blank=True)

    class Meta:
        db_table = "payroll_period"
        ordering = ["-start_date", "company__name", "code"]
        verbose_name = "Payroll Period"
        verbose_name_plural = "Payroll Periods"

        constraints = [
            models.UniqueConstraint(
                fields=["company", "payroll_group", "code"],
                condition=Q(is_deleted=False),
                name="uniq_active_payroll_period_code",
            ),
            # Satu company × group tidak boleh punya dua periode dengan
            # rentang yang sama persis. Tumpang tindih sebagian sengaja
            # tidak dilarang di database — periode koreksi dan off-cycle
            # memang bisa memotong periode reguler.
            models.UniqueConstraint(
                fields=[
                    "company",
                    "payroll_group",
                    "start_date",
                    "end_date",
                ],
                condition=Q(is_deleted=False),
                name="uniq_active_payroll_period_range",
            ),
        ]

        indexes = [
            models.Index(
                fields=["company", "start_date", "end_date"],
                name="idx_payroll_period_range",
            ),
        ]

    @property
    def is_locked(self) -> bool:
        return self.status == PayrollPeriodStatus.FINALIZED

    @property
    def effective_cutoff(self):
        return self.cutoff_date or self.end_date

    @property
    def divisor_days(self) -> int:
        if self.working_days:
            return self.working_days

        return (self.end_date - self.start_date).days + 1

    def clean(self):
        super().clean()

        errors = {}

        if self.end_date and self.start_date and self.end_date < self.start_date:
            errors["end_date"] = (
                "End Date tidak boleh lebih awal dari Start Date."
            )

        if self.cutoff_date and self.start_date and self.cutoff_date < self.start_date:
            errors["cutoff_date"] = (
                "Cutoff Date tidak boleh lebih awal dari Start Date."
            )

        if self.payment_date and self.end_date and self.payment_date < self.end_date:
            errors["payment_date"] = (
                "Payment Date tidak boleh lebih awal dari End Date."
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"
