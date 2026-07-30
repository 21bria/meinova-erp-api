from apps.framework.lookup import (
    BaseLookup,
    register_lookup,
)

from apps.administration.models import (
    City,
    Country,
    Province,
)


@register_lookup
class CountryLookup(BaseLookup):
    name = "countries"
    model = Country

    search_fields = ["code","name"]
    ordering = [ "name"]


@register_lookup
class ProvinceLookup(BaseLookup):
    name = "provinces"
    model = Province

    search_fields = ["code","name"]
    filter_fields = ["country_id"]

    ordering = ["name"]


@register_lookup
class CityLookup(BaseLookup):
    name = "cities"
    model = City
    
    search_fields = [ "code","name"]
    filter_fields = ["province_id"]

    ordering = [ "name" ]