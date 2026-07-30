# apps/core/models/base_reference.py
from django.db import models
from .base import BaseModel

class BaseReference(BaseModel):
    code = models.CharField(
        max_length=50,
        unique=True,
    )

    name = models.CharField(
        max_length=150,
    )

    description = models.TextField(
        blank=True,
        default="",
    )

    sort_order = models.PositiveSmallIntegerField(
        default=0,
    )

    class Meta:
        abstract = True
        ordering = [
            "sort_order",
            "name",
        ]

    def __str__(self):
        return self.name