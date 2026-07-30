from apps.framework.lookup import (
    BaseLookup,
    register_lookup,
)

from apps.payroll.models import OvertimeGroup


@register_lookup
class OvertimeGroupLookup(BaseLookup):
    name = "overtime-groups"
    model = OvertimeGroup

    value_field = "id"
    label_field = "name"

    search_fields = [
        "code",
        "name",
    ]

    ordering = [
        "code",
    ]

    