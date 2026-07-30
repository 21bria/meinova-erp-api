from apps.framework.lookup import (
    BaseLookup,
    register_lookup,
)

from apps.administration.models import (
    BranchType,
    CompanyType,
    SiteType,
)


@register_lookup
class BranchTypeLookup(BaseLookup):
    name = "branch-types"

    model = BranchType

    search_fields = [
        "code",
        "name",
    ]

    ordering = [
        "code",
    ]


@register_lookup
class CompanyTypeLookup(BaseLookup):
    name = "company-types"

    model = CompanyType

    search_fields = [
        "code",
        "name",
    ]

    ordering = [
        "code",
    ]


@register_lookup
class SiteTypeLookup(BaseLookup):
    name = "site-types"

    model = SiteType

    search_fields = [
        "code",
        "name",
    ]

    ordering = [
        "code",
    ]