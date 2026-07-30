from apps.framework.views.master import BaseMasterViewSet
from apps.administration.api.organization.serializers import DivisionSerializer
from apps.administration.api.organization.services import DivisionService


class DivisionViewSet(BaseMasterViewSet):
    serializer_class = DivisionSerializer
    service_class = DivisionService

    framework_module = "administration/organization/division"
    schema_type = "crud"
    
    ordering = ["name"]
    search_fields = [
        "code",
        "name",
        "company__name",
        "site__name",
    ]
    filterset_fields = [
        "company",
        "site",
        "is_active",
    ]
    schema = {
        "endpoint": "/api/administration/organization/division/",
        "ui": {
            "editor": "dialog",
            "size": "lg"
        },
        "fields": {
            "company": {
                "lookup_endpoint": "/api/administration/organization/lookup/companies/",
                "required": True,
                "placement": "quick",
                "order": 10,
            },
            "site": {
                "lookup_endpoint": "/api/administration/organization/lookup/sites/",
                  "depends_on": "company",
                "lookup_params": {
                    "company_id": "$company",
                },
                "required": True,
                "placement": "quick",
                "order": 20,
            },
            "code": {
                "placeholder": "e.g. OPS",
                "order": 30,
            },
            "name": {
                "placeholder": "e.g. Operations",
                "order": 40,
            },
            "is_active": {
                "label": "Active",
                "order": 999,
            },
        },
    }
