from apps.administration.models import CompanyType, BranchType, SiteType


class CompanyTypeService:
    @staticmethod
    def list():
        return CompanyType.objects.filter(is_deleted=False).order_by("sort_order", "name")


class BranchTypeService:
    @staticmethod
    def list():
        return BranchType.objects.filter(is_deleted=False).order_by("sort_order", "name")


class SiteTypeService:
    @staticmethod
    def list():
        return SiteType.objects.filter(is_deleted=False).order_by("sort_order", "name")

