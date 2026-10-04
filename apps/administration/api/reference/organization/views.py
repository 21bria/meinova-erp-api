from apps.framework.views.master import BaseMasterViewSet
from apps.administration.api.reference.organization.serializers import *
from apps.administration.api.reference.organization.services import *
from apps.administration.api.reference.organization.schemas import *


class CompanyTypeViewSet(BaseMasterViewSet):
    serializer_class = CompanyTypeSerializer
    service_class = CompanyTypeService
    framework_module = "references/organization/company-types"
    # schema = company_type_schema("company-types")

    ordering = ["sort_order", "name"]
    search_fields = ["code", "name"]
    schema_type = "crud"
    schema = {
        "endpoint": "/api/administration/references/organization/company-types"
        }


class BranchTypeViewSet(BaseMasterViewSet):
    serializer_class = BranchTypeSerializer
    service_class = BranchTypeService
    framework_module = "references/organization/branch-types"
    # schema = branch_type_schema("branch-types")
  
    ordering = ["sort_order", "name"]
    search_fields = ["code", "name"]
    schema_type = "crud"
    schema = {
        "endpoint": "/api/administration/references/organization/branch-types"
        }


class LocationTypeViewSet(BaseMasterViewSet):
    serializer_class = LocationTypeSerializer
    service_class = LocationTypeService
    framework_module = "references/organization/location-types"
    # schema = location_type_schema("location-types")
    ordering = ["sort_order", "name"]
    search_fields = ["code", "name"]

    schema_type = "crud"
    schema = {
        "endpoint": "/api/administration/references/organization/location-types"
        }


class FacilityTypeViewSet(BaseMasterViewSet):
    """
    Jenis fasilitas: Workshop, Warehouse, Jetty, Camp, dan seterusnya.

    Dipisah dari Location Type karena keduanya menjawab pertanyaan yang
    berbeda — lihat docstring `FacilityType` di model.
    """

    serializer_class = FacilityTypeSerializer
    service_class = FacilityTypeService
    framework_module = "references/organization/facility-types"

    ordering = ["sort_order", "name"]
    search_fields = ["code", "name"]

    schema_type = "crud"
    schema = {
        "title": "Facility Type",
        "endpoint": "/api/administration/references/organization/facility-types/",
        "ui": {
            "editor": "dialog",
            "size": "md",
        },
        "fields": {
            "code": {
                "label": "Code",
                "placeholder": "e.g. WORKSHOP",
                "required": True,
                "order": 10,
            },
            "name": {
                "label": "Name",
                "placeholder": "e.g. Workshop",
                "required": True,
                "order": 20,
            },
            "description": {
                "label": "Description",
                "order": 30,
            },
            "sort_order": {
                "label": "Sort Order",
                "order": 40,
            },
            "is_active": {
                "label": "Active",
                "placement": "quick",
                "order": 999,
            },
        },
    }

