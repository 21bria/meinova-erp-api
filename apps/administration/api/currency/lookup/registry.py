from apps.framework.lookup import (
    BaseLookup,
    register_lookup,
)

from apps.administration.models import Currency


@register_lookup
class CurrencyLookup(BaseLookup):
    name = "currencies"

    model = Currency

    search_fields = [
        "code",
        "name",
        "symbol",
    ]

    ordering = [
        "code",
    ]