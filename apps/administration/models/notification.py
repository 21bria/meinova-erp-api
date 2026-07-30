from django.conf import settings
from django.db import models


class Notification(models.Model):

    TYPE_CHOICES = [
        ("INFO", "Info"),
        ("SUCCESS", "Success"),
        ("WARNING", "Warning"),
        ("ERROR", "Error"),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
    )

    title = models.CharField(max_length=150)
    message = models.TextField(blank=True)

    type = models.CharField(
        max_length=20,
        choices=TYPE_CHOICES,
        default="INFO",
    )

    module = models.CharField(max_length=50, blank=True)

    link = models.CharField(max_length=255, blank=True)

    object_type = models.CharField(max_length=100, blank=True)
    object_id = models.CharField(max_length=100, blank=True)

    is_read = models.BooleanField(default=False)
    read_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "master_notification"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["user", "is_read"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return self.title

class NotificationSetting(models.Model):

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notification_setting",
    )

    in_app_enabled = models.BooleanField(default=True)
    email_enabled = models.BooleanField(default=True)

    push_enabled = models.BooleanField(default=False)
    sms_enabled = models.BooleanField(default=False)

    class Meta:
        db_table = "master_notification_setting"

    def __str__(self):
        return str(self.user)