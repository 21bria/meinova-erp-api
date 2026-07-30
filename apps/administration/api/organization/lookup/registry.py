from apps.framework.lookup import (
    BaseLookup,
    register_lookup,
)

from apps.administration.models import (
    Branch,
    Company,
    CostCenter,
    Department,
    Division,
    Position,
    Section,
    Site,
)

@register_lookup
class CompanyLookup(BaseLookup):
    name = "companies"
    model = Company
    search_fields = ["code", "name"]
    ordering = ["code"]


@register_lookup
class BranchLookup(BaseLookup):
    name = "branches"
    model = Branch
    search_fields = ["code", "name"]
    filter_fields = ["company_id"]
    ordering = ["code"]


@register_lookup
class SiteLookup(BaseLookup):
    name = "sites"
    model = Site
    search_fields = ["code", "name"]
    filter_fields = ["branch_id"]
    ordering = ["code"]


@register_lookup
class DivisionLookup(BaseLookup):
    name = "divisions"
    model = Division
    search_fields = ["code", "name"]
    filter_fields = ["company_id"]
    ordering = ["code"]


@register_lookup
class DepartmentLookup(BaseLookup):
    name = "departments"
    model = Department
    search_fields = ["code", "name"]
    filter_fields = ["division_id"]
    ordering = ["code"]


@register_lookup
class SectionLookup(BaseLookup):
    name = "sections"
    model = Section
    search_fields = ["code", "name"]
    filter_fields = ["department_id"]
    ordering = ["code"]


@register_lookup
class PositionLookup(BaseLookup):
    name = "positions"
    model = Position
    search_fields = ["code", "name"]
    filter_fields = ["section_id"]
    ordering = ["code"]


@register_lookup
class CostCenterLookup(BaseLookup):
    name = "cost-centers"
    model = CostCenter
    search_fields = ["code", "name"]
    filter_fields = ["company_id"]
    ordering = ["code"]