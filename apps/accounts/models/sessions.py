from django.conf import settings
from django.db import models

from apps.core.models.base import BaseModel


class UserSession(BaseModel):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="sessions",
    )

    session_key = models.CharField(max_length=255, blank=True, db_index=True)
    refresh_jti = models.CharField(max_length=255, blank=True, db_index=True)

    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)

    browser = models.CharField(max_length=100, blank=True)
    os = models.CharField(max_length=100, blank=True)
    device = models.CharField(max_length=100, blank=True)

    login_at = models.DateTimeField(auto_now_add=True)
    last_activity_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    is_active_session = models.BooleanField(default=True)

    class Meta:
        db_table = "accounts_user_session"
        ordering = ["-login_at"]
        indexes = [
            models.Index(fields=["user", "is_active_session"]),
            models.Index(fields=["ip_address"]),
            models.Index(fields=["login_at"]),
            models.Index(fields=["last_activity_at"]),
        ]

    def __str__(self):
        return f"{self.user} - {self.ip_address or '-'}"