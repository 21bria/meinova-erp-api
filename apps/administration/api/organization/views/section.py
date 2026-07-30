from apps.framework.views.master import BaseMasterViewSet

from apps.administration.api.organization.serializers import (
    SectionSerializer,
)
from apps.administration.api.organization.services import (
    SectionService,
)


class SectionViewSet(BaseMasterViewSet):
    serializer_class = SectionSerializer
    service_class = SectionService

    framework_module = "administration/organization/section"
    schema_type = "crud"

    ordering = ["name"]

    search_fields = [
        "code",
        "name",
        "company__name",
        "site__name",
        "division__name",
        "department__name",
    ]

    filterset_fields = [
        "company",
        "site",
        "division",
        "department",
        "is_active",
    ]

    schema = {
        "endpoint": "/api/administration/organization/section/",
        "ui": {
            "editor": "dialog",
            "size": "lg",
        },
        "fields": {
            "company": {
                "lookup_endpoint": (
                    "/api/administration/organization/"
                    "lookup/companies/"
                ),
                "required": True,
                "placement": "quick",
                "order": 10,
            },

            "site": {
                "lookup_endpoint": (
                    "/api/administration/organization/"
                    "lookup/sites/"
                ),
                "depends_on": "company",
                "lookup_params": {
                    "company_id": "$company",
                },
                "required": True,
                "placement": "quick",
                "order": 20,
            },

            "division": {
                "lookup_endpoint": (
                    "/api/administration/organization/"
                    "lookup/divisions/"
                ),
                "depends_on": "site",
                "lookup_params": {
                    "site_id": "$site",
                },
                "required": True,
                "placement": "advanced",
                "order": 30,
            },

            "department": {
                "lookup_endpoint": (
                    "/api/administration/organization/"
                    "lookup/departments/"
                ),
                "depends_on": "division",
                "lookup_params": {
                    "division_id": "$division",
                },
                "required": True,
                "placement": "advanced",
                "order": 40,
            },

            "code": {
                "label": "Section Code",
                "placeholder": "e.g. MINE",
                "order": 50,
            },

            "name": {
                "label": "Section Name",
                "placeholder": "e.g. Mine Operation",
                "order": 60,
            },

            "is_active": {
                "label": "Active",
                "placement": "quick",
                "order": 999,
            },
        },
    }