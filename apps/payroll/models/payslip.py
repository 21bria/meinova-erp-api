from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel

from .choices import PayslipStatus
from .payroll_run_employee import PayrollRunEmployee


class Payslip(BaseModel):
    """
    Slip gaji: dokumen terbit dari hasil run, bukan perhitungan kedua.

    `snapshot` memuat seluruh isi slip — kepala, rincian earning,
    rincian potongan, total — dibekukan saat penerbitan. Menghitung
    ulang saat slip dibuka berarti slip yang sama bisa berubah isinya
    setelah master diperbaiki, dan itu persis yang dilarang Tahap 9.

    Angka ringkasnya tetap disalin ke kolom sendiri supaya laporan dan
    daftar bisa menjumlahkan tanpa membongkar JSON tiap baris.
    """

    run_employee = models.OneToOneField(
        PayrollRunEmployee,
        on_delete=models.CASCADE,
        related_name="payslip",
    )

    document_number = models.CharField(max_length=50, blank=True, default="")

    # Disalin supaya penyaringan cakupan data dan laporan tidak perlu
    # menembus tiga relasi untuk setiap baris.
    run = models.ForeignKey(
        "payroll.PayrollRun",
        on_delete=models.CASCADE,
        related_name="payslips",
    )
    period = models.ForeignKey(
        "payroll.PayrollPeriod",
        on_delete=models.PROTECT,
        related_name="payslips",
    )
    employee = models.ForeignKey(
        "hr.Employee",
        on_delete=models.PROTECT,
        related_name="payslips",
    )
    company = models.ForeignKey(
        "administration.Company", on_delete=models.PROTECT,
        null=True, blank=True, related_name="+",
    )
    branch = models.ForeignKey(
        "administration.Branch", on_delete=models.PROTECT,
        null=True, blank=True, related_name="+",
    )
    location = models.ForeignKey(
        "administration.Location", on_delete=models.PROTECT,
        null=True, blank=True, related_name="+",
    )
    division = models.ForeignKey(
        "administration.Division", on_delete=models.PROTECT,
        null=True, blank=True, related_name="+",
    )
    department = models.ForeignKey(
        "administration.Department", on_delete=models.PROTECT,
        null=True, blank=True, related_name="+",
    )
    section = models.ForeignKey(
        "administration.Section", on_delete=models.PROTECT,
        null=True, blank=True, related_name="+",
    )

    issue_date = models.DateField(null=True, blank=True)

    basic_salary = models.DecimalField(
        max_digits=18, decimal_places=2, default=0,
    )
    gross_earning = models.DecimalField(
        max_digits=18, decimal_places=2, default=0,
    )
    total_deduction = models.DecimalField(
        max_digits=18, decimal_places=2, default=0,
    )
    tax_amount = models.DecimalField(
        max_digits=18, decimal_places=2, default=0,
    )
    net_pay = models.DecimalField(
        max_digits=18, decimal_places=2, default=0,
    )

    # Ikut dikolomkan, bukan hanya hidup di `snapshot`: laporan biaya
    # tenaga kerja menjumlah ribuan slip, dan menjumlah lewat JSON
    # berarti memuat semuanya ke memori untuk satu angka.
    employer_contribution = models.DecimalField(
        max_digits=18, decimal_places=2, default=0,
    )

    snapshot = models.JSONField(default=dict, blank=True)

    status = models.CharField(
        max_length=20,
        choices=PayslipStatus.choices,
        default=PayslipStatus.PUBLISHED,
    )

    published_at = models.DateTimeField(null=True, blank=True)
    published_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True, related_name="+",
    )

    notes = models.TextField(blank=True)

    class Meta:
        db_table = "payroll_payslip"
        ordering = ["-period__start_date", "employee__employee_number"]
        verbose_name = "Payslip"
        verbose_name_plural = "Payslips"

        constraints = [
            models.UniqueConstraint(
                fields=["document_number"],
                condition=Q(is_deleted=False) & ~Q(document_number=""),
                name="uniq_active_payroll_payslip_number",
            ),
        ]

        indexes = [
            models.Index(
                fields=["period", "employee"],
                name="idx_payroll_payslip_period_emp",
            ),
        ]

    def __str__(self) -> str:
        return self.document_number or f"Payslip #{self.pk}"
