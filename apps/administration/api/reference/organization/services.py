from apps.administration.models import (
    BranchType,
    CompanyType,
    FacilityType,
    LocationType,
)


class CompanyTypeService:
    @staticmethod
    def list():
        return CompanyType.objects.filter(is_deleted=False).order_by("sort_order", "name")


class BranchTypeService:
    @staticmethod
    def list():
        return BranchType.objects.filter(is_deleted=False).order_by("sort_order", "name")


class LocationTypeService:
    @staticmethod
    def list():
        return LocationType.objects.filter(is_deleted=False).order_by("sort_order", "name")



class FacilityTypeService:
    @staticmethod
    def list():
        return FacilityType.objects.filter(is_deleted=False).order_by("sort_order", "name")
