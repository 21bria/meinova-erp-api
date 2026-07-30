from django.conf import settings
from django.db import models


class SecuritySetting(models.Model):

    max_login_attempts = models.PositiveSmallIntegerField(default=3)
    lockout_minutes = models.PositiveSmallIntegerField(default=15)
    password_expiry_days = models.PositiveSmallIntegerField(default=90)
    require_2fa = models.BooleanField(default=False)

    class Meta:
        db_table = "master_security_setting"


class SessionSetting(models.Model):
    timeout_minutes = models.PositiveSmallIntegerField(default=30)
    remember_me_days = models.PositiveSmallIntegerField(default=7)
    single_session_only = models.BooleanField(default=False)

    class Meta:
        db_table = "master_session_setting"


class LoginHistory(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    
    username = models.CharField(max_length=150)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)

    is_success = models.BooleanField(default=False)
    failure_reason = models.CharField(max_length=255, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "master_login_history"
        ordering = ["-created_at"]


class UserSession(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)

    session_key = models.CharField(max_length=255)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(blank=True)

    is_active = models.BooleanField(default=True)
    expired_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "master_user_session"