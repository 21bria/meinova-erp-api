from apps.framework.views.master import BaseMasterViewSet

from apps.hr.api.employee.schema import EMPLOYEE_SCHEMA
from apps.hr.api.employee.serializers.employee import EmployeeSerializer
from apps.hr.api.employee.services.employee_service import EmployeeService


class EmployeeViewSet(BaseMasterViewSet):
    serializer_class = EmployeeSerializer
    service_class = EmployeeService

    framework_module = "hr/employees"
    schema_type = "crud"

    ordering = [
        "first_name",
        "last_name",
    ]

    search_fields = [
        "employee_number",
        "nik",
        "first_name",
        "middle_name",
        "last_name",
        "preferred_name",
        "personal_email",
        "work_email",
        "phone",
        "mobile",
    ]

    filterset_fields = [
        "gender",
        "religion",
        "nationality",
        "blood_type",
        "marital_status",
        "is_active",
    ]

    schema = EMPLOYEE_SCHEMA

    def get_queryset(self):
        return EmployeeService.list()