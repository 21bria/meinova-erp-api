from django.conf import settings
from django.db import models


class GenderChoices(models.TextChoices):
    MALE = "male", "Male"
    FEMALE = "female", "Female"
    OTHER = "other", "Other"


class UserProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
    )

    full_name = models.CharField(max_length=150, blank=True)
    phone = models.CharField(max_length=30, blank=True)

    gender = models.CharField(
        max_length=20,
        choices=GenderChoices.choices,
        blank=True,
    )

    bio = models.TextField(blank=True)

    avatar = models.ImageField(
        upload_to="avatars/%Y/%m/",
        blank=True,
        null=True,
    )

    language = models.CharField(
        max_length=20,
        default="id",
    )

    timezone = models.CharField(
        max_length=50,
        default="Asia/Jakarta",
    )

    birth_date = models.DateField(
        blank=True,
        null=True,
    )

    address = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "accounts_profiles"

        indexes = [
            models.Index(fields=["full_name"]),
        ]

    def __str__(self):
        return self.full_name or self.user.username