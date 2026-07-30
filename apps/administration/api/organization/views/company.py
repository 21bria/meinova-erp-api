from apps.framework.views.master import BaseMasterViewSet

from apps.administration.api.organization.serializers import (
    CompanySerializer,
)
from apps.administration.api.organization.services import (
    CompanyService,
)


class CompanyViewSet(BaseMasterViewSet):
    serializer_class = CompanySerializer
    service_class = CompanyService

    framework_module = "administration/organization/company"
    schema_type = "crud"

    search_fields = [
        "code",
        "name",
        "legal_name",
        "tax_number",
        "email",
        "phone",
    ]

    ordering = ["name"]

    filterset_fields = [
        "is_active",
        "company_type",
        "parent",
        "country",
        "province",
        "city",
    ]

    schema = {
        "endpoint": "/api/administration/organization/company/",
        "ui": {
            "editor": "dialog",
            "size": "lg",
        },
        "fields": {
            "parent": {
                "label": "Parent Company",
                "lookup_endpoint": (
                    "/api/administration/organization/"
                    "lookup/companies/"
                ),
                "placement": "advanced",
                "order": 10,
            },

            "company_type": {
                "label": "Company Type",
                "lookup_endpoint": (
                    "/api/administration/references/"
                    "organization/lookup/company-types/"
                ),
                "required": True,
                "placement": "quick",
                "order": 20,
            },

            "code": {
                "label": "Company Code",
                "placeholder": "e.g. MNV",
                "required": True,
                "order": 30,
            },

            "name": {
                "label": "Company Name",
                "placeholder": "e.g. Meinova Indonesia",
                "required": True,
                "order": 40,
            },

            "legal_name": {
                "label": "Legal Name",
                "placeholder": "e.g. PT Meinova Indonesia",
                "order": 50,
            },

            "tax_number": {
                "label": "Tax Number",
                "placeholder": "NPWP",
                "order": 60,
            },

            "phone": {
                "label": "Phone",
                "order": 70,
            },

            "email": {
                "label": "Email",
                "order": 80,
            },

            "website": {
                "label": "Website",
                "placeholder": "https://example.com",
                "order": 90,
            },

            "country": {
                "label": "Country",
                "lookup_endpoint": (
                    "/api/administration/references/"
                    "geography/lookup/countries/"
                ),
                "placement": "advanced",
                "order": 100,
            },

            "province": {
                "label": "Province",
                "lookup_endpoint": (
                    "/api/administration/references/"
                    "geography/lookup/provinces/"
                ),
                "depends_on": "country",
                "lookup_params": {
                    "country_id": "$country",
                },
                "placement": "advanced",
                "order": 110,
            },

            "city": {
                "label": "City",
                "lookup_endpoint": (
                    "/api/administration/references/"
                    "geography/lookup/cities/"
                ),
                "depends_on": "province",
                "lookup_params": {
                    "province_id": "$province",
                },
                "placement": "advanced",
                "order": 120,
            },

            "address": {
                "label": "Address",
                "widget": "textarea",
                "rows": 4,
                "layout": "full",
                "order": 130,
            },

            "is_active": {
                "label": "Active",
                "placement": "quick",
                "order": 999,
            },
        },
    }