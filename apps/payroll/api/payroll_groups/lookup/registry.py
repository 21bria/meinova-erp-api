from apps.framework.lookup import (
    BaseLookup,
    register_lookup,
)

from apps.payroll.models import PayrollGroup


@register_lookup
class PayrollGroupLookup(BaseLookup):
    name = "payroll-groups"
    model = PayrollGroup

    value_field = "id"
    label_field = "name"

    search_fields = [
        "code",
        "name",
    ]

    ordering = [
        "code",
    ]

    