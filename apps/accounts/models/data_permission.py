from django.db import models

from apps.core.models.base import BaseModel


class RoleDataPermission(BaseModel):
    class ResourceType(models.TextChoices):
        COMPANY = "company", "Company"
        BRANCH = "branch", "Branch"
        SITE = "site", "Site"
        DIVISION = "division", "Division"
        DEPARTMENT = "department", "Department"
        SECTION = "section", "Section"
        COST_CENTER = "cost_center", "Cost Center"
        WAREHOUSE = "warehouse", "Warehouse"
        PROJECT = "project", "Project"
        IUP = "iup", "IUP"
        OWN = "own", "Own Data"

    role = models.ForeignKey(
        "accounts.Role",
        on_delete=models.CASCADE,
        related_name="data_permissions",
    )

    resource_type = models.CharField(
        max_length=50,
        choices=ResourceType.choices,
    )

    resource_id = models.PositiveIntegerField(
        null=True,
        blank=True,
    )

    class Meta:
        db_table = "accounts_role_data_permission"
        constraints = [
            models.UniqueConstraint(
                fields=["role", "resource_type", "resource_id"],
                name="uniq_accounts_role_data_permission",
            ),
        ]
        ordering = ["role__name", "resource_type", "resource_id"]

    def __str__(self):
        return f"{self.role} - {self.resource_type} - {self.resource_id or 'ALL'}"