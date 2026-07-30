from apps.framework.lookup import (
    BaseLookup,
    register_lookup,
)

from apps.payroll.models import AllowanceTemplate


@register_lookup
class AllowanceTemplateLookup(BaseLookup):
    name = "allowance-templates"
    model = AllowanceTemplate

    value_field = "id"
    label_field = "name"

    search_fields = [
        "code",
        "name",
    ]

    ordering = [
        "code",
    ]

    