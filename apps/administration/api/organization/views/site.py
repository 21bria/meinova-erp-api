from apps.framework.views.master import BaseMasterViewSet

from apps.administration.api.organization.serializers import (
    SiteSerializer,
)
from apps.administration.api.organization.services import (
    SiteService,
)


class SiteViewSet(BaseMasterViewSet):
    serializer_class = SiteSerializer
    service_class = SiteService

    framework_module = "administration/organization/site"
    schema_type = "crud"

    ordering = ["name"]

    search_fields = [
        "code",
        "name",
        "company__name",
        "branch__name",
    ]

    filterset_fields = [
        "company",
        "branch",
        "site_type",
        "is_active",
    ]

    schema = {
        "endpoint": "/api/administration/organization/site/",
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

            "branch": {
                "lookup_endpoint": (
                    "/api/administration/organization/"
                    "lookup/branches/"
                ),
                "depends_on": "company",
                "lookup_params": {
                    "company_id": "$company",
                },
                "required": True,
                "placement": "quick",
                "order": 20,
            },

            "site_type": {
                "lookup_endpoint": (
                    "/api/administration/references/"
                    "organization/lookup/site-types/"
                ),
                "label": "Site Type",
                "required": True,
                "placement": "quick",
                "order": 30,
            },

            "code": {
                "label": "Site Code",
                "placeholder": "e.g. SITE-01",
                "required": True,
                "order": 40,
            },

            "name": {
                "label": "Site Name",
                "placeholder": "e.g. Site Morowali",
                "required": True,
                "order": 50,
            },

            "is_active": {
                "label": "Active",
                "placement": "quick",
                "order": 999,
            },
        },
    }