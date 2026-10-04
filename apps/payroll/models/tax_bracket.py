from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel


class PayrollTaxBracket(BaseModel):
    """
    Lapisan tarif PPh21 progresif, dalam **rupiah setahun**.

    Setahun, bukan sebulan: PTKP (`TaxStatus.non_taxable_income`) juga
    angka tahunan, dan mencampur dua satuan di satu perhitungan adalah
    cara paling cepat menghasilkan pajak yang salah dua belas kali
    lipat. Mesin hitungnya menyetahunkan penghasilan bulanan, memotong
    PTKP, menerapkan lapisan ini, lalu membaginya dua belas.

    Tabel ini **opsional**. Kosong = tidak ada PPh21 yang dihitung, dan
    komponen berbasis `pph21_progressive` menghasilkan nol beserta
    peringatan pada hasil run — bukan error yang menghentikan payroll,
    karena tenant yang pajaknya diurus di luar sistem tetap harus bisa
    menerbitkan slip.
    """

    sequence = models.PositiveIntegerField(default=1)

    income_from = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        default=0,
        help_text="Batas bawah penghasilan kena pajak setahun.",
    )

    income_to = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Kosong = lapisan teratas, tanpa batas.",
    )

    rate = models.DecimalField(
        max_digits=6,
        decimal_places=3,
        default=0,
        help_text="Tarif dalam persen, mis. 5 untuk 5%.",
    )

    description = models.TextField(blank=True)

    class Meta:
        db_table = "payroll_tax_bracket"
        ordering = ["sequence", "income_from"]
        verbose_name = "Tax Bracket"
        verbose_name_plural = "Tax Brackets"

        constraints = [
            models.UniqueConstraint(
                fields=["sequence"],
                condition=Q(is_deleted=False),
                name="uniq_active_payroll_tax_bracket_sequence",
            ),
        ]

    def clean(self):
        super().clean()

        if (
            self.income_to is not None
            and self.income_to <= self.income_from
        ):
            raise ValidationError(
                {
                    "income_to": (
                        "Batas atas harus lebih besar dari batas bawah."
                    ),
                },
            )

    def __str__(self) -> str:
        return f"{self.income_from} - {self.income_to or '~'} @ {self.rate}%"
