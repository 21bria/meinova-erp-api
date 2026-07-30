from apps.framework.views.master import BaseMasterViewSet

from apps.hr.models import EmployeeCertificate

from .serializers import EmployeeCertificateSerializer
from .services import EmployeeCertificateService


class EmployeeCertificateViewSet(
    BaseMasterViewSet,
):
    serializer_class = EmployeeCertificateSerializer
    service_class = EmployeeCertificateService

    search_fields = [
        "certificate_name",
        "certificate_number",
        "issuing_organization",
        "credential_id",
    ]

    filterset_fields = [
        "employee",
        "certificate_type",
        "is_lifetime",
        "is_verified",
        "is_active",
    ]

    ordering = [
        "-issue_date",
        "certificate_name",
    ]

    def get_queryset(self):
        return (
            EmployeeCertificate.objects
            .select_related(
                "employee",
                "certificate_type",
            )
            .filter(is_deleted=False)
        )