from rest_framework import serializers

from apps.hr.models import Employee

from .mixins.general import EmployeeGeneralFieldsMixin
from .mixins.organization import EmployeeOrganizationFieldsMixin
from .mixins.employment import EmployeeEmploymentFieldsMixin
from .mixins.payroll import EmployeePayrollFieldsMixin

from apps.hr.api.employee.services.employee_service import EmployeeService

class EmployeeSerializer(
    EmployeeGeneralFieldsMixin,
    EmployeeOrganizationFieldsMixin,
    EmployeeEmploymentFieldsMixin,
    EmployeePayrollFieldsMixin,
    serializers.ModelSerializer,
):
    full_name = serializers.CharField(
        read_only=True,
    )

    display_name = serializers.CharField(
        read_only=True,
    )

    class Meta:
        model = Employee

        fields = [
            # Base
            "id",

            # General
            "user",
            "employee_number",
            "nik",
            "passport_number",
            "tax_number",
            "first_name",
            "last_name",
            "gender",
            "religion",
            "nationality",
            "blood_type",
            "marital_status",
            "birth_place",
            "birth_date",
            "personal_email",
            "work_email",
            "phone",
            "mobile",
            "emergency_contact_name",
            "emergency_contact_phone",
            "avatar",
            "notes",
            "is_active",

            # Organization
            "company",
            "branch",
            "site",
            "division",
            "department",
            "section",
            "position",
            "job_level",
            "job_grade",
            "reports_to",
            "cost_center",
            "organization_effective_date",
            "organization_notes",

            # Employment
            "employment_status",
            "employment_type",
            "employee_group",
            "contract_type",
            "probation_type",
            "employment_effective_date",
            "join_date",
            "confirmation_date",
            "probation_start",
            "probation_end",
            "contract_start",
            "contract_end",

            "work_schedule",
            "working_calendar",
            "shift",
            "notice_period_days",
            "employment_notes",

            # Payroll
            "payroll_group",
            "salary_grade",
            "salary_level",
            "currency",
            "payment_method",
            "tax_status",
            "tax_number_payroll",
            "bpjs_kesehatan_number",
            "bpjs_ketenagakerjaan_number",
            "overtime_eligible",
            "overtime_group",
            "basic_salary",
            "allowance_template",
            "deduction_template",
            "effective_from",
            "effective_to",
            "payroll_notes",

            # Computed
            "full_name",
            "display_name",
        ]

        read_only_fields = [
            "id",
            "created_at",
            "updated_at",
            "created_by",
            "updated_by",
            "deleted_at",
            "deleted_by",
            "is_deleted",
            "full_name",
            "display_name",
        ]

    def create(self, validated_data):
        request = self.context.get("request")

        return EmployeeService.create(
            validated_data,
            user=request.user if request else None,
        )

    def update(self, instance, validated_data):

        request = self.context.get("request")

        return EmployeeService.update(
            instance,
            validated_data,
            user=request.user if request else None,
        )