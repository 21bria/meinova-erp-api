from apps.framework.views.master import BaseMasterViewSet

from apps.administration.api.organization.serializers import (
    LocationSerializer,
)
from apps.administration.api.organization.services import (
    LocationService,
)


class LocationViewSet(BaseMasterViewSet):
    serializer_class = LocationSerializer
    service_class = LocationService

    framework_module = "administration/organization/location"
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
        "location_type",
        "is_active",
    ]

    schema = {
        "endpoint": "/api/administration/organization/location/",
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

            "location_type": {
                "lookup_endpoint": (
                    "/api/administration/references/"
                    "organization/lookup/location-types/"
                ),
                "label": "Location Type",
                "required": True,
                "placement": "quick",
                "order": 30,
            },

            "code": {
                "label": "Location Code",
                "placeholder": "e.g. LOCATION-01",
                "required": True,
                "order": 40,
            },

            "name": {
                "label": "Location Name",
                "placeholder": "e.g. Location Morowali",
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