from rest_framework import serializers

from apps.payroll.models import Payslip


class PayslipSerializer(serializers.ModelSerializer):
    employee_name = serializers.CharField(
        source="employee.full_name", read_only=True, default=None,
    )
    employee_number = serializers.CharField(
        source="employee.employee_number", read_only=True, default=None,
    )
    company_name = serializers.CharField(
        source="company.name", read_only=True, default=None,
    )
    department_name = serializers.CharField(
        source="department.name", read_only=True, default=None,
    )
    section_name = serializers.CharField(
        source="section.name", read_only=True, default=None,
    )
    period_name = serializers.CharField(
        source="period.name", read_only=True, default=None,
    )
    period_code = serializers.CharField(
        source="period.code", read_only=True, default=None,
    )
    run_document_number = serializers.CharField(
        source="run.document_number", read_only=True, default=None,
    )

    class Meta:
        model = Payslip
        fields = "__all__"

        # Slip adalah dokumen hasil, bukan formulir. Seluruh isinya
        # read-only; koreksi lewat payroll run bertipe Correction.
        read_only_fields = [
            field.name for field in Payslip._meta.fields
        ]
