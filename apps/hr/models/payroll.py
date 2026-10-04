from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models.base import BaseModel
from apps.hr.models.employee import Employee
from apps.payroll.models import (
    AllowanceTemplate,
    DeductionTemplate,
    OvertimeGroup,
    PayrollGroup,
    PayrollPolicy,
    SalaryGrade,
    SalaryLevel,
    TaxStatus,
)
from apps.administration.models import Currency


class PayrollAssignment(BaseModel):
    class PaymentMethod(models.TextChoices):
        BANK_TRANSFER = "bank_transfer", "Bank Transfer"
        CASH = "cash", "Cash"
        CHEQUE = "cheque", "Cheque"

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="payroll_assignments",
    )

    payroll_group = models.ForeignKey(
        PayrollGroup,
        on_delete=models.PROTECT,
        related_name="employee_payroll_assignments",
    )

    salary_grade = models.ForeignKey(
        SalaryGrade,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_payroll_assignments",
    )

    salary_level = models.ForeignKey(
        SalaryLevel,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_payroll_assignments",
    )

    currency = models.ForeignKey(
        Currency,
        on_delete=models.PROTECT,
        related_name="employee_payroll_assignments",
    )

    payment_method = models.CharField(
        max_length=30,
        choices=PaymentMethod.choices,
        default=PaymentMethod.BANK_TRANSFER,
    )

    tax_status = models.ForeignKey(
        TaxStatus,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_payroll_assignments",
    )

    tax_number_payroll = models.CharField(max_length=50,blank=True)

    bpjs_kesehatan_number = models.CharField(max_length=50,blank=True)

    bpjs_ketenagakerjaan_number = models.CharField(max_length=50,blank=True,)

    overtime_eligible = models.BooleanField(default=False)

    overtime_group = models.ForeignKey(
        OvertimeGroup,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_payroll_assignments",
    )

    basic_salary = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
    )

    # Upah sehari pegawai harian. Ditaruh **di sini**, bukan di kartu
    # pegawai: kompensasi payroll yang authoritative sudah tinggal di
    # baris ini, dan hanya baris ini yang punya rentang berlaku.
    # Menaruhnya di Employee berarti kenaikan upah bulan depan ikut
    # mengubah payroll bulan lalu yang dihitung ulang.
    #
    # Dipakai hanya kalau kebijakannya memang harian dan tarifnya
    # memang diambil dari sini; kebijakan yang menurunkan tarif dari
    # gaji sebulan tidak membacanya.
    daily_rate = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
    )

    # Kebijakan perhitungan yang dipakai pegawai ini. Kosong = ikut
    # `PayrollSetting` perusahaannya, yaitu perilaku sebelum kebijakan
    # ini ada — tidak ada assignment lama yang berubah angkanya.
    #
    # Ditaruh di assignment, bukan di kartu pegawai, karena inilah yang
    # effective-dated: assignment yang berlaku 1 Juli membawa kebijakan
    # barunya untuk payroll Juli, sementara payroll Juni tetap membaca
    # assignment lama beserta kebijakan lamanya.
    payroll_policy = models.ForeignKey(
        PayrollPolicy,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_payroll_assignments",
    )

    allowance_template = models.ForeignKey(
        AllowanceTemplate,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_payroll_assignments",
    )

    deduction_template = models.ForeignKey(
        DeductionTemplate,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_payroll_assignments",
    )

    effective_from = models.DateField()
    effective_to = models.DateField(
        null=True,
        blank=True,
    )

    is_current = models.BooleanField(
        default=True,
    )

    payroll_notes = models.TextField(
        blank=True,
    )

    class Meta:
        db_table = "hr_employee_payroll_assignment"
        ordering = [
            "employee_id",
            "-effective_from",
        ]
        constraints = [
            models.UniqueConstraint(
                fields=[
                    "employee",
                    "effective_from",
                ],
                name=(
                    "uniq_employee_payroll_assignment_"
                    "effective_from"
                ),
            ),
            models.UniqueConstraint(
                fields=["employee"],
                condition=models.Q(is_current=True),
                name=(
                    "uniq_current_employee_"
                    "payroll_assignment"
                ),
            ),
        ]

    def clean(self):
        super().clean()

        errors = {}

        if (
            self.effective_to
            and self.effective_to < self.effective_from
        ):
            errors["effective_to"] = (
                "Effective to tidak boleh lebih awal "
                "dari effective from."
            )

        if (
            self.salary_level_id
            and self.salary_grade_id
            and hasattr(self.salary_level, "salary_grade_id")
            and self.salary_level.salary_grade_id
            != self.salary_grade_id
        ):
            errors["salary_level"] = (
                "Salary Level harus berasal dari "
                "Salary Grade yang dipilih."
            )

        if (
            self.overtime_group_id
            and not self.overtime_eligible
        ):
            errors["overtime_group"] = (
                "Overtime Group hanya boleh dipilih "
                "jika employee eligible overtime."
            )

        if self.daily_rate is not None and self.daily_rate < 0:
            errors["daily_rate"] = (
                "Daily Rate tidak boleh bernilai negatif."
            )

        if self.is_current and self.effective_to:
            errors["effective_to"] = (
                "Current payroll assignment tidak boleh "
                "memiliki effective to."
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return (
            f"{self.employee} - "
            f"{self.payroll_group}"
        )