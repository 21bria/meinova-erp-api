from apps.framework.views.master import BaseMasterViewSet

from apps.administration.api.organization.serializers import CostCenterSerializer
from apps.administration.api.organization.services import CostCenterService


class CostCenterViewSet(BaseMasterViewSet):
    serializer_class = CostCenterSerializer
    service_class = CostCenterService
    framework_module = "administration/organization/cost-center"
    schema_type = "crud"
    
    ordering = ["name"]
    search_fields = [
        "code",
        "name",
        "company__name",
        "location__name",
    ]
    filterset_fields = [
        "company",
        "location",
        "is_active",
    ]
    schema = {
        "endpoint": "/api/administration/organization/cost-center/",
        "ui": {
            "editor": "dialog",
            "size": "lg",
        },
        "fields": {
            "company": {
                "lookup_endpoint": "/api/administration/organization/lookup/companies/",
                "placement": "quick",
                "order": 10,
            },
            "location": {
                "lookup_endpoint": "/api/administration/organization/lookup/locations/",
                "depends_on": "company",
                "lookup_params": {
                    "company_id": "$company",
                },
                "placement": "quick",
                "order": 20,
            },
            "code": {
                "label": "Cost Center Code",
                "placeholder": "e.g. CC-001",
                "order": 30,
            },
            "name": {
                "label": "Cost Center Name",
                "placeholder": "e.g. Mining Operation",
                "order": 40,
            },
            "is_active": {
                "label": "Active",
                "order": 999,
            },
        },
    }