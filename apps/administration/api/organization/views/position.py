from apps.framework.views.master import BaseMasterViewSet

from apps.administration.api.organization.serializers import PositionSerializer
from apps.administration.api.organization.services import PositionService

class PositionViewSet(BaseMasterViewSet):
    serializer_class = PositionSerializer
    service_class = PositionService

    framework_module = "administration/organization/position"
    schema_type = "crud"

    ordering = ["name"]

    search_fields = [
        "code",
        "name",
        "company__name",
        "branch__name",
        "site__name",
        "division__name",
        "department__name",
        "section__name",
        "job_category__name",
        "job_level__name",
    ]

    filterset_fields = [
        "company",
        "branch",
        "site",
        "division",
        "department",
        "section",
        "job_category",
        "job_level",
        "is_active",
    ]

    schema = {
        "endpoint": "/api/administration/organization/position/",
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
                "placement": "quick",
                "order": 20,
            },

            "site": {
                "lookup_endpoint": (
                    "/api/administration/organization/"
                    "lookup/sites/"
                ),
                "depends_on": "branch",
                "lookup_params": {
                    "branch_id": "$branch",
                },
                "placement": "advanced",
                "order": 30,
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
                "placement": "advanced",
                "order": 40,
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
                "placement": "advanced",
                "order": 50,
            },

            "section": {
                "lookup_endpoint": (
                    "/api/administration/organization/"
                    "lookup/sections/"
                ),
                "depends_on": "department",
                "lookup_params": {
                    "department_id": "$department",
                },
                "placement": "advanced",
                "order": 60,
            },

            "job_category": {
                "label": "Job Category",
                "lookup_endpoint": (
                    "/api/administration/references/hr/"
                    "lookup/job-categories/"
                ),
                "placement": "advanced",
                "order": 70,
            },

            "job_level": {
                "label": "Job Level",
                "lookup_endpoint": (
                    "/api/administration/references/hr/"
                    "lookup/job-levels/"
                ),
                "placement": "advanced",
                "order": 80,
            },

            "code": {
                "label": "Position Code",
                "placeholder": "e.g. SUP-MINE",
                "order": 90,
            },

            "name": {
                "label": "Position Name",
                "placeholder": "e.g. Mine Supervisor",
                "order": 100,
            },

            "is_active": {
                "label": "Active",
                "placement": "quick",
                "order": 999,
            },
        },
    }