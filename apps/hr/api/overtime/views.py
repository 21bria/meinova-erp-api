from apps.framework.views.master import BaseMasterViewSet
from apps.framework.views.mixins import ServiceWriteMixin

from apps.hr.models import EmployeeOvertime

from .schema import OVERTIME_SCHEMA
from .serializers import EmployeeOvertimeSerializer
from .services import EmployeeOvertimeService


class EmployeeOvertimeViewSet(
    ServiceWriteMixin,
    BaseMasterViewSet,
):
    # Penyaringan data per baris (kewenangan `RoleAssignment`). Kolom
    # organisasinya sudah tersimpan langsung di record ini; `section`
    # lewat penempatan pegawainya karena baris ini tidak menyimpannya.
    data_scope = {
        "company": "company",
        "branch": "branch",
        "location": "location",
        "division": "employee__organization__division",
        "department": "employee__organization__department",
        "section": "employee__organization__section",
        "own": "employee__user_id",
    }

    serializer_class = EmployeeOvertimeSerializer
    service_class = EmployeeOvertimeService

    framework_module = "hr/overtime"
    schema = OVERTIME_SCHEMA

    search_fields = [
        "employee__employee_number",
        "employee__first_name",
        "employee__last_name",
        "overtime_type__name",
        "reason",
        "notes",
    ]

    filterset_fields = [
        "employee",
        "company",
        "branch",
        "location",
        "overtime_type",
        "work_date",
        "status",
        "is_paid",
    ]

    ordering_fields = [
        "work_date",
        "start_time",
        "end_time",
        "duration_minutes",
        "status",
        "employee__employee_number",
        "employee__first_name",
        "overtime_type__name",
        "created_at",
        "updated_at",
    ]

    ordering = [
        "-work_date",
        "employee__employee_number",
    ]

    def get_queryset(self):
        return (
            EmployeeOvertime.objects
            .select_related(
                "employee",
                "company",
                "branch",
                "location",
                "overtime_type",
            )
            .filter(is_deleted=False)
        )
