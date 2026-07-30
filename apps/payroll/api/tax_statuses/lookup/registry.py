from apps.framework.lookup import (
    BaseLookup,
    register_lookup,
)

from apps.payroll.models import TaxStatus


@register_lookup
class TaxStatusLookup(BaseLookup):
    name = "tax-statuses"
    model = TaxStatus

    value_field = "id"
    label_field = "name"

    search_fields = [
        "code",
        "name",
    ]

    ordering = [
        "code",
    ]

    