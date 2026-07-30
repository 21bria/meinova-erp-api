from apps.framework.lookup import (
    BaseLookup,
    register_lookup,
)

from apps.administration.models import (
    Bank,
    BankBranch,
)


@register_lookup
class BankLookup(BaseLookup):
    name = "banks"
    model = Bank

    search_fields = [
        "code",
        "name",
    ]

    ordering = [
        "name",
    ]


@register_lookup
class BankBranchLookup(BaseLookup):
    name = "bank-branches"
    model = BankBranch

    search_fields = [
        "code",
        "name",
    ]

    ordering = [
        "name",
    ]

    filter_fields = [
        "bank",
    ]