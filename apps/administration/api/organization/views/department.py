from apps.framework.views.master import BaseMasterViewSet
from apps.administration.api.organization.serializers import DepartmentSerializer
from apps.administration.api.organization.services import DepartmentService


class DepartmentViewSet(BaseMasterViewSet):
    serializer_class = DepartmentSerializer
    service_class = DepartmentService
    
    framework_module = "administration/organization/department"
    schema_type = "crud"

    ordering = ["name"]
    search_fields = [
        "code",
        "name",
        "company__name",
        "site__name",
        "division__name",
    ]
    filterset_fields = [
        "company",
        "site",
        "division",
        "is_active",
    ]
    schema = {
        "endpoint": "/api/administration/organization/department/",
        "ui": {
            "editor": "dialog",
            "size": "lg",
        },
        "fields": {
            "company": {
                "lookup_endpoint": "/api/administration/organization/lookup/companies/",
                "form": {
                    "order": 10,
                },
                "filter": {
                    "group": "quick",
                    "order": 10,
                },
            },
            "site": {
                "lookup_endpoint": "/api/administration/organization/lookup/sites/",
                "depends_on": "company",
                "lookup_params": {
                    "company_id": "$company",
                },
                "form": {
                    "order": 20,
                },
                "filter": {
                    "group": "quick",
                    "order": 20,
                },
            },
            "division": {
                "lookup_endpoint": "/api/administration/organization/lookup/divisions/",
                "depends_on": "company",
                "lookup_params": {
                    "company_id": "$company",
                },
                "form": {
                    "order": 30,
                },
                "filter": {
                    "group": "advanced",
                    "order": 30,
                },
            },
            "code": {
                "label": "Department Code",
                "placeholder": "e.g. HRD",
                "form": {
                    "order": 40,
                },
            },
            "name": {
                "label": "Department Name",
                "placeholder": "e.g. Human Resources",
                "form": {
                    "order": 50,
                },
            },
            "is_active": {
                "label": "Active",
                "form": {
                    "order": 999,
                },
                "filter": {
                    "group": "quick",
                    "order": 999,
                },
            },
        },
    }