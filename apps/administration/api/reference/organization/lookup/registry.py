from apps.framework.lookup import (
    BaseLookup,
    register_lookup,
)

from apps.administration.models import (
    BranchType,
    CompanyType,
    FacilityType,
    LocationType,
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
class LocationTypeLookup(BaseLookup):
    name = "location-types"

    model = LocationType

    search_fields = [
        "code",
        "name",
    ]

    ordering = [
        "code",
    ]


@register_lookup
class FacilityTypeLookup(BaseLookup):
    name = "facility-types"

    model = FacilityType

    search_fields = [
        "code",
        "name",
    ]

    ordering = [
        "sort_order",
        "code",
    ]

