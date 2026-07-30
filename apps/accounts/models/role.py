from django.contrib.auth.models import Permission
from django.db import models

from apps.core.models.base import BaseModel


class Role(BaseModel):
    code = models.CharField(max_length=50, unique=True)

    name = models.CharField(max_length=150)

    description = models.TextField(blank=True)

    permissions = models.ManyToManyField(
        Permission,
        blank=True,
        related_name="roles",
    )

    class Meta:
        db_table = "accounts_role"
        ordering = ["name"]

    def __str__(self):
        return self.name