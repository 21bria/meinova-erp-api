import uuid

from django.db import models
from django_tenants.models import TenantMixin, DomainMixin


class Client(TenantMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    schema_name = models.CharField(max_length=63, unique=True)
    code = models.SlugField(max_length=50, unique=True)
    name = models.CharField(max_length=200)

    is_active = models.BooleanField(default=True)

    auto_create_schema = True
    auto_drop_schema = False

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "tenants_client"
        ordering = ["name"]

    def __str__(self):
        return self.name


class Domain(DomainMixin):
    class Meta:
        db_table = "tenants_domain"

    def __str__(self):
        return self.domain


class Plan(models.Model):
    code = models.SlugField(max_length=50, unique=True)
    name = models.CharField(max_length=100)

    max_users = models.PositiveIntegerField(default=10)
    max_companies = models.PositiveIntegerField(default=1)
    max_locations = models.PositiveIntegerField(default=1)

    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "tenants_plan"

    def __str__(self):
        return self.name


class Subscription(models.Model):
    tenant = models.OneToOneField(
        Client,
        on_delete=models.CASCADE,
        related_name="subscription",
    )
    plan = models.ForeignKey(
        Plan,
        on_delete=models.PROTECT,
    )

    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)

    status = models.CharField(max_length=20, default="ACTIVE")

    class Meta:
        db_table = "tenants_subscription"