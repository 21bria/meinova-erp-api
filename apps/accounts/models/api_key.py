import secrets
import hashlib

from django.db import models

from apps.core.models.base import BaseModel


class APIKey(BaseModel):
    user = models.ForeignKey(
        "accounts.User",
        on_delete=models.CASCADE,
        related_name="api_keys",
    )

    name = models.CharField(max_length=150)

    prefix = models.CharField(max_length=16, db_index=True)
    hashed_key = models.CharField(max_length=128, unique=True)

    last_used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    allowed_ips = models.JSONField(default=list, blank=True)
    scopes = models.JSONField(default=list, blank=True)

    @staticmethod
    def generate_key():
        raw_key = secrets.token_urlsafe(40)
        prefix = raw_key[:12]
        hashed_key = hashlib.sha256(raw_key.encode()).hexdigest()
        return raw_key, prefix, hashed_key

    class Meta:
        db_table = "accounts_api_key"
        ordering = ["name"]

    def __str__(self):
        return self.name