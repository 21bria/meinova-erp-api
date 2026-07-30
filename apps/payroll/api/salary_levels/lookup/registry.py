from apps.framework.lookup import (
    BaseLookup,
    register_lookup,
)

from apps.payroll.models import SalaryLevel


@register_lookup
class SalaryLevelLookup(BaseLookup):
    name = "salary-levels"
    model = SalaryLevel

    value_field = "id"
    label_field = "name"

    search_fields = [
        "code",
        "name",
    ]

    ordering = [
        "sequence",
        "code",
    ]

    