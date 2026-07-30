from django.db import models

from apps.core.models.base import BaseModel


class Menu(BaseModel):
    parent = models.ForeignKey(
        "self",
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="children",
    )

    code = models.CharField(max_length=100, unique=True)
    title = models.CharField(max_length=150)

    route = models.CharField(max_length=255, blank=True)
    icon = models.CharField(max_length=100, blank=True)
    module = models.CharField(max_length=100, blank=True)

    sort_order = models.PositiveIntegerField(default=0)
    is_group = models.BooleanField(default=False)

    class Meta:
        db_table = "accounts_menu"
        ordering = ["sort_order", "title"]

    def __str__(self):
        return self.title


class RoleMenuPermission(BaseModel):
    role = models.ForeignKey(
        "accounts.Role",
        on_delete=models.CASCADE,
        related_name="menu_permissions",
    )

    menu = models.ForeignKey(
        Menu,
        on_delete=models.CASCADE,
        related_name="role_permissions",
    )

    can_view = models.BooleanField(default=True)

    class Meta:
        db_table = "accounts_role_menu_permission"
        constraints = [
            models.UniqueConstraint(
                fields=["role", "menu"],
                name="uniq_accounts_role_menu_permission",
            ),
        ]

    def __str__(self):
        return f"{self.role} - {self.menu}"