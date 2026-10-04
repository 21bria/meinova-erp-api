from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models import BaseModel

from .allowance_template_line import AllowanceTemplateLine
from .choices import (
    EMPLOYEE_SIDE_COMPONENT_TYPES,
    INPUT_TYPE_DEFAULT_SIDE,
    PayrollComponentType,
    PayrollInputStatus,
    PayrollInputType,
)
from .deduction_template_line import DeductionTemplateLine
from .payroll_period import PayrollPeriod


class PayrollInput(BaseModel):
    """
    Nilai transaksi payroll satu pegawai untuk satu periode.

    **Hanya nilainya.** Definisi komponen tetap di master
    (`AllowanceTemplateLine` / `DeductionTemplateLine`); baris ini
    menunjuk salah satunya dan mengisi angkanya untuk periode ini saja.
    Komponen yang memang tidak ada di master — insentif sekali jalan,
    koreksi bulan lalu — boleh berdiri sendiri dengan `code`/`name`
    diketik, dan itu satu-satunya alasan kedua kolom itu boleh diisi
    tangan.

    Lembur yang sudah punya dokumennya sendiri (`EmployeeOvertime`)
    **tidak** perlu diinput di sini: mesin hitung membacanya langsung
    dari modul HR. Input bertipe overtime disediakan untuk site yang
    lemburnya belum lewat modul itu.
    """

    period = models.ForeignKey(
        PayrollPeriod,
        on_delete=models.CASCADE,
        related_name="inputs",
    )

    employee = models.ForeignKey(
        "hr.Employee",
        on_delete=models.PROTECT,
        related_name="payroll_inputs",
    )

    input_type = models.CharField(
        max_length=30,
        choices=PayrollInputType.choices,
        default=PayrollInputType.ALLOWANCE,
    )

    component_type = models.CharField(
        max_length=20,
        choices=EMPLOYEE_SIDE_COMPONENT_TYPES,
        blank=True,
        default="",
        help_text=(
            "Kosong = mengikuti sisi bawaan jenis input."
        ),
    )

    allowance_line = models.ForeignKey(
        AllowanceTemplateLine,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="payroll_inputs",
    )

    deduction_line = models.ForeignKey(
        DeductionTemplateLine,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="payroll_inputs",
    )

    code = models.CharField(max_length=50, blank=True, default="")
    name = models.CharField(max_length=150, blank=True, default="")

    quantity = models.DecimalField(
        max_digits=12, decimal_places=4, default=1,
    )

    rate = models.DecimalField(
        max_digits=18, decimal_places=2, null=True, blank=True,
        help_text="Kosong = Amount dipakai apa adanya.",
    )

    amount = models.DecimalField(
        max_digits=18, decimal_places=2, default=0,
    )

    is_taxable = models.BooleanField(default=True)

    status = models.CharField(
        max_length=20,
        choices=PayrollInputStatus.choices,
        default=PayrollInputStatus.DRAFT,
    )

    reference = models.CharField(max_length=100, blank=True, default="")
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "payroll_input"
        ordering = ["-period__start_date", "employee__employee_number", "code"]
        verbose_name = "Payroll Input"
        verbose_name_plural = "Payroll Inputs"

        indexes = [
            models.Index(
                fields=["period", "employee"],
                name="idx_payroll_input_period_emp",
            ),
        ]

    @property
    def effective_side(self) -> str:
        if self.component_type:
            return self.component_type

        return INPUT_TYPE_DEFAULT_SIDE.get(
            self.input_type,
            PayrollComponentType.EARNING,
        )

    @property
    def effective_code(self) -> str:
        if self.allowance_line_id and self.allowance_line:
            return self.allowance_line.code

        if self.deduction_line_id and self.deduction_line:
            return self.deduction_line.code

        return self.code

    @property
    def effective_name(self) -> str:
        if self.allowance_line_id and self.allowance_line:
            return self.allowance_line.name

        if self.deduction_line_id and self.deduction_line:
            return self.deduction_line.name

        return self.name or self.get_input_type_display()

    @property
    def effective_amount(self):
        if self.rate is not None:
            product = Decimal(self.rate) * Decimal(self.quantity or 0)
            return product.quantize(Decimal("0.01"))

        return Decimal(self.amount or 0)

    def clean(self):
        super().clean()

        errors = {}

        if self.allowance_line_id and self.deduction_line_id:
            errors["deduction_line"] = (
                "Pilih salah satu saja: komponen tunjangan atau "
                "komponen potongan."
            )

        side = self.effective_side

        if self.allowance_line_id and side != PayrollComponentType.EARNING:
            errors["component_type"] = (
                "Komponen tunjangan tidak bisa dipakai sebagai potongan."
            )

        if self.deduction_line_id and side != PayrollComponentType.DEDUCTION:
            errors["component_type"] = (
                "Komponen potongan tidak bisa dipakai sebagai earning."
            )

        # Baris berdiri sendiri wajib menyebut namanya. Komponen tanpa
        # nama muncul di slip sebagai kolom kosong, dan pegawai yang
        # bertanya tidak bisa dijawab siapa pun.
        if (
            not self.allowance_line_id
            and not self.deduction_line_id
            and not self.code
        ):
            errors["code"] = (
                "Isi Code, atau pilih komponen dari master."
            )

        if self.quantity is not None and self.quantity < 0:
            errors["quantity"] = "Quantity tidak boleh negatif."

        if self.rate is None and not self.amount:
            errors["amount"] = (
                "Isi Amount, atau isi Rate untuk dikalikan Quantity."
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self) -> str:
        return f"{self.employee_id} - {self.effective_code}"
