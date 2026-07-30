from apps.framework.views.master import BaseMasterViewSet

from apps.administration.api.organization.serializers import BranchSerializer
from apps.administration.api.organization.services import BranchService


class BranchViewSet(BaseMasterViewSet):
    serializer_class = BranchSerializer
    service_class = BranchService

    framework_module = "administration/organization/branch"
    schema_type = "crud"

    ordering = ["name"]

    search_fields = [
        "code",
        "name",
        "company__name",
    ]

    filterset_fields = [
        "company",
        "country",
        "province",
        "city",
        "is_active",
    ]

    schema = {
        "endpoint": "/api/administration/organization/branch/",
        "ui": {
            "editor": "dialog",
            "size": "lg",
        },
        "fields": {
            "company": {
                "lookup_endpoint": "/api/administration/organization/lookup/companies/",
                "required": True,
                "placement": "quick",
                "order": 10,
            },

            "code": {
                "label": "Branch Code",
                "placeholder": "e.g. JKT",
                "required": True,
                "order": 20,
            },

            "name": {
                "label": "Branch Name",
                "placeholder": "e.g. Jakarta Branch",
                "required": True,
                "order": 30,
            },

            "website": {
                "placeholder": "https://example.com",
                "order": 40,
            },

            "country": {
                "lookup_endpoint": (
                    "/api/administration/references/geography/"
                    "lookup/countries/"
                ),
                "required": True,
                "placement": "advanced",
                "order": 50,
            },

            "province": {
                "lookup_endpoint": (
                    "/api/administration/references/geography/"
                    "lookup/provinces/"
                ),
                "depends_on": "country",
                "lookup_params": {
                    "country_id": "$country",
                },
                "placement": "advanced",
                "order": 60,
            },

            "city": {
                "lookup_endpoint": (
                    "/api/administration/references/geography/"
                    "lookup/cities/"
                ),
                "depends_on": "province",
                "lookup_params": {
                    "province_id": "$province",
                },
                "placement": "advanced",
                "order": 70,
            },

            "is_active": {
                "label": "Active",
                "placement": "quick",
                "order": 999,
            },
        },
    }