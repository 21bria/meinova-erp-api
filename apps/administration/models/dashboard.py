from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models.base import BaseModel


class DashboardWidget(BaseModel):
    class WidgetType(models.TextChoices):
        CARD = "CARD", "Card"
        CHART = "CHART", "Chart"
        TABLE = "TABLE", "Table"
        LIST = "LIST", "List"
        CUSTOM = "CUSTOM", "Custom"

    code = models.CharField(max_length=100)
    title = models.CharField(max_length=150)
    description = models.TextField(blank=True)

    module = models.CharField(max_length=50, blank=True)

    widget_type = models.CharField(
        max_length=30,
        choices=WidgetType.choices,
        default=WidgetType.CARD,
    )

    component = models.CharField(max_length=100)
    endpoint = models.CharField(max_length=255, blank=True)
    permission = models.CharField(max_length=150, blank=True)

    default_width = models.PositiveSmallIntegerField(default=1)
    default_height = models.PositiveSmallIntegerField(default=1)

    class Meta:
        db_table = "master_dashboard_widget"
        ordering = ["module", "title"]

        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                condition=Q(is_deleted=False),
                name="uniq_active_administration_dashboardwidget_code",
            ),
        ]

    def __str__(self):
        return self.title


class DashboardTemplate(BaseModel):
    code = models.CharField(max_length=100)
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)

    role = models.CharField(max_length=100, blank=True)

    is_default = models.BooleanField(default=False)

    class Meta:
        db_table = "master_dashboard_template"
        ordering = ["name"]

        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                condition=Q(is_deleted=False),
                name="uniq_active_administration_dashboardtemplate_code",
            ),
        ]

    def __str__(self):
        return self.name


class DashboardTemplateItem(BaseModel):
    template = models.ForeignKey(
        DashboardTemplate,
        on_delete=models.CASCADE,
        related_name="items",
    )

    widget = models.ForeignKey(
        DashboardWidget,
        on_delete=models.CASCADE,
        related_name="template_items",
    )

    x = models.PositiveSmallIntegerField(default=0)
    y = models.PositiveSmallIntegerField(default=0)

    width = models.PositiveSmallIntegerField(default=1)
    height = models.PositiveSmallIntegerField(default=1)

    config = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "master_dashboard_template_item"
        constraints = [
            models.UniqueConstraint(
                fields=["template", "widget"],
                name="uniq_dashboard_template_widget",
            ),
        ]
        ordering = ["y", "x"]

    def __str__(self):
        return f"{self.template} - {self.widget}"


class UserDashboardLayout(BaseModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="dashboard_layouts",
    )

    widget = models.ForeignKey(
        DashboardWidget,
        on_delete=models.CASCADE,
        related_name="user_layouts",
    )

    x = models.PositiveSmallIntegerField(default=0)
    y = models.PositiveSmallIntegerField(default=0)

    width = models.PositiveSmallIntegerField(default=1)
    height = models.PositiveSmallIntegerField(default=1)

    config = models.JSONField(default=dict, blank=True)

    is_visible = models.BooleanField(default=True)

    class Meta:
        db_table = "master_user_dashboard_layout"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "widget"],
                name="uniq_dashboard_layout_user_widget",
            ),
        ]
        ordering = ["y", "x"]

    def __str__(self):
        return f"{self.user} - {self.widget}"


class FavoriteApp(BaseModel):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "Active"
        COMING_SOON = "COMING_SOON", "Coming Soon"
        BETA = "BETA", "Beta"
        MAINTENANCE = "MAINTENANCE", "Maintenance"
        DISABLED = "DISABLED", "Disabled"

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="favorite_apps",
    )

    app_code = models.CharField(max_length=50)
    title = models.CharField(max_length=100)
    description = models.CharField(max_length=200, blank=True)

    link = models.CharField(max_length=255)

    icon = models.CharField(max_length=100, blank=True)
    color = models.CharField(max_length=30, blank=True)
    badge = models.CharField(max_length=30, blank=True)

    status = models.CharField(
        max_length=20,
        choices=Status.choices,
        default=Status.ACTIVE,
    )

    is_visible = models.BooleanField(default=True)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "master_favorite_app"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "app_code"],
                name="uniq_favorite_app_user_code",
            ),
        ]
        ordering = ["position"]

    def __str__(self):
        return self.title


class FavoriteMenu(BaseModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="favorite_menus",
    )

    menu_code = models.CharField(max_length=100)
    title = models.CharField(max_length=100)
    description = models.CharField(max_length=200, blank=True)

    link = models.CharField(max_length=255)

    icon = models.CharField(
        max_length=100,
        blank=True,
        help_text="Lucide icon name",
    )

    color = models.CharField(max_length=30, blank=True)
    badge = models.CharField(max_length=30, blank=True)

    position = models.PositiveIntegerField(default=0)
    is_visible = models.BooleanField(default=True)

    class Meta:
        db_table = "master_favorite_menu"
        constraints = [
            models.UniqueConstraint(
                fields=["user", "menu_code"],
                name="uniq_favorite_menu_user_code",
            ),
        ]
        ordering = ["position"]

    def __str__(self):
        return self.title