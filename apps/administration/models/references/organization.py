from apps.core.models.base_reference import BaseReference


class CompanyType(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_company_type"

class BranchType(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_branch_type"

class SiteType(BaseReference):
    class Meta(BaseReference.Meta):
        db_table = "master_site_type"

