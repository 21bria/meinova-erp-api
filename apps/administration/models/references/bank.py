from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel


class Bank(BaseModel):
    code = models.CharField(
        max_length=20,
    )

    name = models.CharField(
        max_length=150,
    )

    short_name = models.CharField(
        max_length=50,
    )

    swift_code = models.CharField(
        max_length=20,
    )

    country = models.ForeignKey(
        "administration.Country",
        null=True,
        blank=True,
        on_delete=models.DO_NOTHING,
        related_name="banks",
    )

    class Meta:
        db_table = "master_bank"
        ordering = ["name"]

        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                condition=Q(is_deleted=False),
                name="uniq_active_administration_bank_code",
            ),
        ]

    def __str__(self):
        return f"{self.code} - {self.name}"