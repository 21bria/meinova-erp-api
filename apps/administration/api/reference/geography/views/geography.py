from apps.framework.views.master import BaseMasterViewSet

from apps.administration.api.reference.geography.serializers.geography import (
    CountrySerializer,
    ProvinceSerializer,
    CitySerializer,
)
from apps.administration.api.reference.geography.services.geography_service import (
    CountryService,
    ProvinceService,
    CityService,
)


def country_schema(slug):
    return {
        "endpoint": f"/api/administration/references/geography/{slug}/",
        "ui": {
            "editor": "dialog",
            "size": "md",
            "columns": 2,
        },
        "fields": {
            "code": {
                "form": True,
                "table": True,
                "filter": False,
                "placeholder": "e.g. ID",
                "order": 10,
            },
            "name": {
                "form": True,
                "table": True,
                "filter": False,
                "placeholder": "Country name",
                "order": 20,
            },
            "phone_code": {
                "label": "Phone Code",
                "form": True,
                "table": True,
                "filter": False,
                "placeholder": "e.g. +62",
                "order": 30,
            },
            "currency_code": {
                "label": "Currency Code",
                "form": True,
                "table": True,
                "filter": False,
                "placeholder": "e.g. IDR",
                "order": 40,
            },
            "is_active": {
                "label": "Active",
                "form": True,
                "table": True,
                "filter": True,
                "placement": "quick",
                "order": 999,
            },
        },
    }


def province_schema(slug):
    return {
        "endpoint": f"/api/administration/references/geography/{slug}/",
        "ui": {
            "editor": "dialog",
            "size": "md",
            "columns": 2,
        },
        "fields": {
            "country": {
                "lookup_endpoint": "/api/administration/references/geography/lookup/countries/",
                "placement": "quick",
                "order": 10,
            },
            "code": {
                "form": True,
                "table": True,
                "filter": False,
                "placeholder": "e.g. DKI",
                "order": 20,
            },
            "name": {
                "form": True,
                "table": True,
                "filter": False,
                "placeholder": "Province name",
                "order": 30,
            },
            "is_active": {
                "label": "Active",
                "form": True,
                "table": True,
                "filter": True,
                "placement": "quick",
                "order": 999,
            },
        },
    }


def city_schema(slug):
    return {
        "endpoint": f"/api/administration/references/geography/{slug}/",
        "ui": {
            "editor": "dialog",
            "size": "md",
            "columns": 2,
        },
        "fields": {
            "province": {
                "lookup_endpoint": "/api/administration/references/geography/lookup/provinces/",
                "placement": "quick",
                "order": 10,
            },
            "code": {
                "form": True,
                "table": True,
                "filter": False,
                "placeholder": "e.g. JKT",
                "order": 20,
            },
            "name": {
                "form": True,
                "table": True,
                "filter": False,
                "placeholder": "City name",
                "order": 30,
            },
            "is_active": {
                "label": "Active",
                "form": True,
                "table": True,
                "filter": True,
                "placement": "quick",
                "order": 999,
            },
        },
    }


class CountryViewSet(BaseMasterViewSet):
    serializer_class = CountrySerializer
    service_class = CountryService

    ordering = ["name"]
    search_fields = ["code", "name", "phone_code", "currency_code"]
    filterset_fields = ["is_active"]
    framework_module = "references/geography/countries"
    schema = country_schema("countries")


class ProvinceViewSet(BaseMasterViewSet):
    serializer_class = ProvinceSerializer
    service_class = ProvinceService

    ordering = ["country__name", "name"]
    search_fields = ["code", "name", "country__name"]
    filterset_fields = ["country", "is_active"]
    framework_module = "references/geography/provinces"
    schema = province_schema("provinces")


class CityViewSet(BaseMasterViewSet):
    serializer_class = CitySerializer
    service_class = CityService

    ordering = ["province__country__name", "province__name", "name"]
    search_fields = ["code", "name", "province__name", "province__country__name"]
    filterset_fields = ["province", "is_active"]
    framework_module = "references/geography/cities"
    schema = city_schema("cities")