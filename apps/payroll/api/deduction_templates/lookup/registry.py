from apps.framework.lookup import (
    BaseLookup,
    register_lookup,
)

from apps.payroll.models import DeductionTemplate


@register_lookup
class DeductionTemplateLookup(BaseLookup):
    name = "deduction-templates"
    model = DeductionTemplate

    value_field = "id"
    label_field = "name"

    search_fields = [
        "code",
        "name",
    ]

    ordering = [
        "code",
    ]

    