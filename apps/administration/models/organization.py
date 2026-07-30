from django.db import models
from apps.core.models.base import BaseModel

class Company(BaseModel):
    parent = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="children",
    )

    company_type = models.ForeignKey(
        "administration.CompanyType",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="companies",
    )

    code = models.CharField(max_length=50)
    name = models.CharField(max_length=200)

    legal_name = models.CharField(max_length=255, blank=True)
    tax_number = models.CharField(max_length=100, blank=True)

    country = models.ForeignKey(
        "administration.Country",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="companies",
    )
    province = models.ForeignKey(
        "administration.Province",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="companies",
    )
    city = models.ForeignKey(
        "administration.City",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="companies",
    )

    address = models.TextField(blank=True)
    postal_code = models.CharField(max_length=20, blank=True)

    phone = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    website = models.URLField(blank=True)

    class Meta:
        db_table = "master_company"
        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                name="uniq_core_company_code",
            ),
        ]
        ordering = ["name"]

    def __str__(self):
        return self.name
    
class Branch(BaseModel):
    company = models.ForeignKey(
        Company,
        on_delete=models.CASCADE,
        related_name="branches",
    )

    code = models.CharField(max_length=50)
    name = models.CharField(max_length=200)

    country = models.ForeignKey(
        "administration.Country",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="branches",
    )
    province = models.ForeignKey(
        "administration.Province",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="branches",
    )
    city = models.ForeignKey(
        "administration.City",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="branches",
    )

    address = models.TextField(blank=True)
    postal_code = models.CharField(max_length=20, blank=True)

    phone = models.CharField(max_length=50, blank=True)
    email = models.EmailField(blank=True)
    website = models.URLField(blank=True)


    class Meta:
        db_table = "master_branch"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "code"],
                name="uniq_core_branch_company_code",
            ),
        ]
        ordering = ["name"]

    def __str__(self):
        return self.name

class Site(BaseModel):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="sites")
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True, related_name="sites")

    code = models.CharField(max_length=50)
    name = models.CharField(max_length=200)

    site_type = models.ForeignKey(
        "administration.SiteType",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="sites",
    )

    country = models.ForeignKey("administration.Country", on_delete=models.SET_NULL, null=True, blank=True, related_name="sites")
    province = models.ForeignKey("administration.Province", on_delete=models.SET_NULL, null=True, blank=True, related_name="sites")
    city = models.ForeignKey("administration.City", on_delete=models.SET_NULL, null=True, blank=True, related_name="sites")

    address = models.TextField(blank=True)
    postal_code = models.CharField(max_length=20, blank=True)

    class Meta:
        db_table = "master_site"
        constraints = [
            models.UniqueConstraint(fields=["company", "code"], name="uniq_core_site_company_code"),
        ]
        ordering = ["name"]

    def __str__(self):
        return self.name

class Division(BaseModel):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="divisions")
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True, related_name="divisions")
    site = models.ForeignKey(Site, on_delete=models.SET_NULL, null=True, blank=True, related_name="divisions")

    code = models.CharField(max_length=50)
    name = models.CharField(max_length=150)

    class Meta:
        db_table = "master_division"
        constraints = [
            models.UniqueConstraint(fields=["company", "code"], name="uniq_core_division_company_code"),
        ]
        ordering = ["name"]

    def __str__(self):
        return self.name

class Department(BaseModel):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="departments")
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True, related_name="departments")
    site = models.ForeignKey(Site, on_delete=models.SET_NULL, null=True, blank=True, related_name="departments")
    division = models.ForeignKey(Division, on_delete=models.SET_NULL, null=True, blank=True, related_name="departments")

    code = models.CharField(max_length=50)
    name = models.CharField(max_length=150)

    class Meta:
        db_table = "master_department"
        constraints = [
            models.UniqueConstraint(fields=["company", "code"], name="uniq_core_department_company_code"),
        ]
        ordering = ["name"]

    def __str__(self):
        return self.name

class Section(BaseModel):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="sections")
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True, related_name="sections")
    site = models.ForeignKey(Site, on_delete=models.SET_NULL, null=True, blank=True, related_name="sections")
    division = models.ForeignKey(Division, on_delete=models.SET_NULL, null=True, blank=True, related_name="sections")
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name="sections")

    code = models.CharField(max_length=50)
    name = models.CharField(max_length=150)

    class Meta:
        db_table = "master_section"
        constraints = [
            models.UniqueConstraint(fields=["company", "code"], name="uniq_core_section_company_code"),
        ]
        ordering = ["name"]

    def __str__(self):
        return self.name

class Position(BaseModel):
    company = models.ForeignKey(Company,on_delete=models.CASCADE,related_name="positions")
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL,null=True,blank=True, related_name="positions")
    site = models.ForeignKey(Site, on_delete=models.SET_NULL, null=True, blank=True, related_name="positions")
    division = models.ForeignKey(Division,on_delete=models.SET_NULL,null=True,blank=True,related_name="positions")
    department = models.ForeignKey(Department,on_delete=models.SET_NULL,  null=True,blank=True,related_name="positions" )
    section = models.ForeignKey(Section,on_delete=models.SET_NULL,null=True,blank=True,related_name="positions")

    job_category = models.ForeignKey("administration.JobCategory",on_delete=models.SET_NULL,null=True,blank=True,related_name="positions")
    job_level = models.ForeignKey("administration.JobLevel",on_delete=models.SET_NULL,null=True,blank=True,related_name="positions")
    reports_to = models.ForeignKey("self", on_delete=models.SET_NULL,null=True,blank=True, related_name="sub_positions")
    code = models.CharField(max_length=50)
    name = models.CharField(max_length=150)

    headcount = models.PositiveSmallIntegerField(default=1)
    description = models.TextField(blank=True)

    is_manager = models.BooleanField(default=False)

    class Meta:
        db_table = "master_position"
        constraints = [
            models.UniqueConstraint(
                fields=["company", "code"],
                name="uniq_core_position_company_code",
            ),
        ]
        ordering = ["name"]

    def __str__(self):
        return self.name

   
class CostCenter(BaseModel):
    company = models.ForeignKey(Company, on_delete=models.CASCADE, related_name="cost_centers")
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True, related_name="cost_centers")
    site = models.ForeignKey(Site, on_delete=models.SET_NULL, null=True, blank=True, related_name="cost_centers")
    division = models.ForeignKey(Division, on_delete=models.SET_NULL, null=True, blank=True, related_name="cost_centers")
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name="cost_centers")

    code = models.CharField(max_length=50)
    name = models.CharField(max_length=150)

    class Meta:
        db_table = "master_cost_center"
        constraints = [
            models.UniqueConstraint(fields=["company", "code"], name="uniq_core_cost_center_company_code"),
        ]
        ordering = ["name"]

    def __str__(self):
        return self.name