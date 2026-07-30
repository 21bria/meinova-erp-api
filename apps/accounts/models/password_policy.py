from django.db import models

from apps.core.models.base import BaseModel


class PasswordPolicy(BaseModel):
    name = models.CharField(max_length=100, default="Default")

    minimum_length = models.PositiveSmallIntegerField(default=8)

    require_uppercase = models.BooleanField(default=True)
    require_lowercase = models.BooleanField(default=True)
    require_number = models.BooleanField(default=True)
    require_special_character = models.BooleanField(default=True)

    password_expiry_days = models.PositiveSmallIntegerField(default=90)

    password_history = models.PositiveSmallIntegerField(default=5)

    maximum_failed_attempts = models.PositiveSmallIntegerField(default=5)

    lockout_duration_minutes = models.PositiveSmallIntegerField(default=30)

    force_change_on_first_login = models.BooleanField(default=True)

    allow_password_reuse = models.BooleanField(default=False)

    is_default = models.BooleanField(default=True)

    class Meta:
        db_table = "accounts_password_policy"
        ordering = ["name"]

    def __str__(self):
        return self.name