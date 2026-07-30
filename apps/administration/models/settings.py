from django.db import models

from apps.core.models.base import BaseModel
from .currency import Currency
from .organization import Company


class TenantSetting(BaseModel):
    company = models.OneToOneField(
        Company,
        on_delete=models.CASCADE,
        related_name="tenant_setting",
    )

    currency = models.ForeignKey(
        Currency,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="tenant_settings",
    )

    timezone = models.CharField(max_length=100, default="Asia/Jakarta")
    language = models.CharField(max_length=20, default="id")

    date_format = models.CharField(max_length=50, default="DD/MM/YYYY")
    decimal_separator = models.CharField(max_length=1, default=",")
    thousand_separator = models.CharField(max_length=1, default=".")

    class Meta:
        db_table = "master_tenant_setting"

    def __str__(self):
        return f"Tenant Setting - {self.company.name}"


class SystemSetting(BaseModel):
    key = models.CharField(max_length=100, unique=True)
    value = models.JSONField(default=dict)

    description = models.CharField(max_length=255, blank=True)
    is_public = models.BooleanField(default=False)

    class Meta:
        db_table = "master_system_setting"
        ordering = ["key"]

    def __str__(self):
        return self.key


class PrintSetting(BaseModel):
    company = models.OneToOneField(
        Company,
        on_delete=models.CASCADE,
        related_name="print_setting",
    )

    logo = models.ImageField(
        upload_to="tenant/logo/",
        null=True,
        blank=True,
    )

    header_text = models.TextField(blank=True)
    footer_text = models.TextField(blank=True)

    default_paper_size = models.CharField(max_length=20, default="A4")
    default_orientation = models.CharField(max_length=20, default="PORTRAIT")

    show_logo = models.BooleanField(default=True)
    show_footer = models.BooleanField(default=True)

    class Meta:
        db_table = "master_print_setting"

    def __str__(self):
        return f"Print Setting - {self.company.name}"