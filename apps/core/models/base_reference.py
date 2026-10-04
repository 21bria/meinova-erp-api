# apps/core/models/base_reference.py
from django.db import models
from django.db.models import Q

from .base import BaseModel


class BaseReference(BaseModel):
    # Keunikan `code` dikondisikan ke is_deleted (lihat Meta.constraints).
    # Dengan unique=True polos, kode referensi yang sudah di-soft-delete
    # akan terkunci selamanya dan tidak bisa dipakai ulang.
    code = models.CharField(
        max_length=50,
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

        # %(app_label)s dan %(class)s dipakai supaya tiap model turunan
        # mendapat nama constraint sendiri. Model turunan wajib memakai
        # `class Meta(BaseReference.Meta)` agar ikut terbawa.
        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                condition=Q(is_deleted=False),
                name="uniq_active_%(app_label)s_%(class)s_code",
            ),
        ]

    def __str__(self):
        return self.name
