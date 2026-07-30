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


class SiteTypeViewSet(BaseMasterViewSet):
    serializer_class = SiteTypeSerializer
    service_class = SiteTypeService
    framework_module = "references/organization/site-types"
    # schema = site_type_schema("site-types")
    ordering = ["sort_order", "name"]
    search_fields = ["code", "name"]

    schema_type = "crud"
    schema = {
        "endpoint": "/api/administration/references/organization/site-types"
        }

