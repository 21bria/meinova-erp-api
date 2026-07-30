from apps.framework.views.master import BaseMasterViewSet

from apps.hr.models import EmployeeBankAccount
from .serializers import EmployeeBankAccountSerializer


class EmployeeBankAccountViewSet(
    BaseMasterViewSet,
):
    serializer_class = EmployeeBankAccountSerializer

    filterset_fields = [
        "employee",
        "bank",
        "is_primary",
        "is_active",
    ]

    ordering = [
        "-is_primary",
        "bank__name",
        "account_number",
    ]

    def get_queryset(self):
        return (
            EmployeeBankAccount.objects
            .select_related(
                "employee",
                "bank",
            )
            .filter(is_deleted=False)
        )