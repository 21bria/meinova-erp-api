from django.db import models

from apps.core.models import BaseModel

from .choices import (
    PayrollBasis,
    PayrollComponentSource,
    PayrollComponentType,
)
from .payroll_run_employee import PayrollRunEmployee


class PayrollRunComponent(BaseModel):
    """
    Satu baris rincian perhitungan seorang pegawai.

    Inilah yang membuat hasil bisa diaudit tanpa menjalankan ulang
    mesinnya. Tiap baris menyimpan **cara** angkanya lahir — basis,
    tarif, kuantitas, dasar perhitungan — bukan hanya hasilnya. "Kenapa
    tunjangan transport bulan ini Rp 480.000, bukan Rp 600.000" dijawab
    barisnya sendiri: 20 hari × Rp 24.000.

    Dokumen asalnya ditunjuk pasangan string `reference_type` /
    `reference_id`, pola yang sama dengan `WorkflowInstance` dan
    `RosterPlanVersion` — tabel ini tidak perlu mengenal model mana pun
    yang bisa melahirkan sebuah komponen.
    """

    run_employee = models.ForeignKey(
        PayrollRunEmployee,
        on_delete=models.CASCADE,
        related_name="components",
    )

    sequence = models.PositiveIntegerField(default=1)

    component_type = models.CharField(
        max_length=30,
        choices=PayrollComponentType.choices,
    )

    source = models.CharField(
        max_length=30,
        choices=PayrollComponentSource.choices,
    )

    code = models.CharField(max_length=50)
    name = models.CharField(max_length=150)

    basis = models.CharField(
        max_length=30,
        choices=PayrollBasis.choices,
        default=PayrollBasis.FIXED,
    )

    # Dasar yang dikenai tarif (gaji pokok, gross, atau nilai satuan).
    base_amount = models.DecimalField(
        max_digits=18, decimal_places=2, default=0,
    )

    rate = models.DecimalField(
        max_digits=18, decimal_places=6, default=0,
    )

    quantity = models.DecimalField(
        max_digits=12, decimal_places=4, default=1,
    )

    amount = models.DecimalField(
        max_digits=18, decimal_places=2, default=0,
    )

    is_taxable = models.BooleanField(default=False)
    reduces_taxable = models.BooleanField(default=False)
    is_prorated = models.BooleanField(default=False)

    reference_type = models.CharField(max_length=50, blank=True, default="")
    reference_id = models.CharField(max_length=50, blank=True, default="")

    calculation_note = models.CharField(max_length=255, blank=True, default="")

    class Meta:
        db_table = "payroll_run_component"
        ordering = ["run_employee", "component_type", "sequence", "code"]
        verbose_name = "Payroll Component Result"
        verbose_name_plural = "Payroll Component Results"

        indexes = [
            models.Index(
                fields=["run_employee", "component_type"],
                name="idx_payroll_component_side",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} - {self.amount}"
