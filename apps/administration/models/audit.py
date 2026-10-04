from django.conf import settings
from django.db import models

from .organization import Company, Location


class AuditTrail(models.Model):
    class Action(models.TextChoices):
        LOGIN = "LOGIN", "Login"
        LOGOUT = "LOGOUT", "Logout"
        CREATE = "CREATE", "Create"
        UPDATE = "UPDATE", "Update"
        DELETE = "DELETE", "Delete"
        APPROVE = "APPROVE", "Approve"
        REJECT = "REJECT", "Reject"
        SUBMIT = "SUBMIT", "Submit"
        CANCEL = "CANCEL", "Cancel"
        IMPORT = "IMPORT", "Import"
        EXPORT = "EXPORT", "Export"
        CLOSE_PERIOD = "CLOSE_PERIOD", "Close Period"
        REOPEN_PERIOD = "REOPEN_PERIOD", "Reopen Period"

    company = models.ForeignKey(
        Company,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_trails",
    )

    location = models.ForeignKey(
        Location,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_trails",
    )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="audit_trails",
    )

    action = models.CharField(
        max_length=30,
        choices=Action.choices,
    )

    module = models.CharField(
        max_length=100,
        db_index=True,
    )

    object_type = models.CharField(
        max_length=100,
        blank=True,
    )

    object_id = models.CharField(
        max_length=100,
        blank=True,
    )

    object_repr = models.CharField(
        max_length=255,
        blank=True,
    )

    before = models.JSONField(
        null=True,
        blank=True,
    )

    after = models.JSONField(
        null=True,
        blank=True,
    )

    ip_address = models.GenericIPAddressField(
        null=True,
        blank=True,
    )

    user_agent = models.TextField(
        blank=True,
    )

    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
    )

    class Meta:
        db_table = "master_audit_trail"
        ordering = ["-created_at"]

        indexes = [
            models.Index(fields=["module"]),
            models.Index(fields=["action"]),
            models.Index(fields=["user"]),
            models.Index(fields=["company"]),
            models.Index(fields=["location"]),
            models.Index(fields=["object_type", "object_id"]),
            models.Index(fields=["created_at"]),
        ]

    def __str__(self):
        return (
            f"{self.get_action_display()} | "
            f"{self.object_type} ({self.object_id})"
        )