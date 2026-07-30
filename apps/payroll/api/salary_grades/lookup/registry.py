from apps.framework.lookup import (
    BaseLookup,
    register_lookup,
)

from apps.payroll.models import SalaryGrade


@register_lookup
class SalaryGradeLookup(BaseLookup):
    name = "salary-grades"
    model = SalaryGrade

    value_field = "id"
    label_field = "name"

    search_fields = [
        "code",
        "name",
    ]

    ordering = [
        "code",
    ]

    