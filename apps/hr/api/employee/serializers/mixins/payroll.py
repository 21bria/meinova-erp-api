from rest_framework import serializers

from apps.administration.models import Currency
from apps.payroll.models import (
    AllowanceTemplate,
    DeductionTemplate,
    OvertimeGroup,
    PayrollGroup,
    SalaryGrade,
    SalaryLevel,
    TaxStatus,
)


class EmployeePayrollFieldsMixin(
    serializers.Serializer,
):
    payroll_group = serializers.PrimaryKeyRelatedField(
        queryset=PayrollGroup.objects.all(),
        required=False,
        allow_null=True,
    )

    salary_grade = serializers.PrimaryKeyRelatedField(
        queryset=SalaryGrade.objects.all(),
        required=False,
        allow_null=True,
    )

    salary_level = serializers.PrimaryKeyRelatedField(
        queryset=SalaryLevel.objects.all(),
        required=False,
        allow_null=True,
    )

    currency = serializers.PrimaryKeyRelatedField(
        queryset=Currency.objects.all(),
        required=False,
        allow_null=True,
    )

    tax_status = serializers.PrimaryKeyRelatedField(
        queryset=TaxStatus.objects.all(),
        required=False,
        allow_null=True,
    )

    overtime_group = serializers.PrimaryKeyRelatedField(
        queryset=OvertimeGroup.objects.all(),
        required=False,
        allow_null=True,
    )

    allowance_template = serializers.PrimaryKeyRelatedField(
        queryset=AllowanceTemplate.objects.all(),
        required=False,
        allow_null=True,
    )

    deduction_template = serializers.PrimaryKeyRelatedField(
        queryset=DeductionTemplate.objects.all(),
        required=False,
        allow_null=True,
    )

    payment_method = serializers.ChoiceField(
        choices=[
            ("bank_transfer", "Bank Transfer"),
            ("cash", "Cash"),
            ("cheque", "Cheque"),
        ],
        required=False,
        allow_blank=True,
    )

    tax_number_payroll = serializers.CharField(
        required=False,
        allow_blank=True,
    )

    bpjs_kesehatan_number = serializers.CharField(
        required=False,
        allow_blank=True,
    )

    bpjs_ketenagakerjaan_number = serializers.CharField(
        required=False,
        allow_blank=True,
    )

    basic_salary = serializers.DecimalField(
        max_digits=18,
        decimal_places=2,
        required=False,
        allow_null=True,
    )

    overtime_eligible = serializers.BooleanField(
        required=False,
    )

    effective_from = serializers.DateField(
        required=False,
        allow_null=True,
    )

    effective_to = serializers.DateField(
        required=False,
        allow_null=True,
    )

    payroll_notes = serializers.CharField(
        required=False,
        allow_blank=True,
    )