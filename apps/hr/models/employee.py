from django.conf import settings
from django.db import models

from apps.core.models.base import BaseModel


class Employee(BaseModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employee_profile",
    )

    employee_number = models.CharField(max_length=50, unique=True)
    nik = models.CharField(
        max_length=50,
        blank=True,
        default="",
    )

    passport_number = models.CharField(max_length=100,blank=True,default="")
    tax_number = models.CharField(max_length=50,blank=True,default="")

    first_name = models.CharField(max_length=100)
    last_name = models.CharField(
        max_length=100,
        blank=True,
        default="",
    )

    gender = models.ForeignKey(
        "administration.Gender",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employees",
    )

    religion = models.ForeignKey(
        "administration.Religion",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employees",
    )

    nationality = models.ForeignKey(
        "administration.Nationality",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employees",
    )

    blood_type = models.ForeignKey(
        "administration.BloodType",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employees",
    )

    marital_status = models.ForeignKey(
        "administration.MaritalStatus",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="employees",
    )

    birth_place = models.CharField(
        max_length=150,
        blank=True,
        default="",
    )

    birth_date = models.DateField(null=True,blank=True)
    personal_email = models.EmailField(
        blank=True,
        default="",
    )

    work_email = models.EmailField(
        blank=True,
        default="",
    )

    phone = models.CharField(
        max_length=50,
        blank=True,
        default="",
    )

    mobile = models.CharField(
        max_length=50,
        blank=True,
        default="",
    )
    emergency_contact_phone = models.CharField(max_length=50,blank=True,default="")
    emergency_contact_name = models.CharField(max_length=150,blank=True, default="")
    avatar = models.ImageField(
        upload_to="employees/avatars/",
        null=True,
        blank=True,
    )

    notes = models.TextField(
        blank=True,
        default="",
    )

    is_active = models.BooleanField( default=True)

    class Meta:
        db_table = "hr_employee"
        ordering = ["first_name", "last_name"]
        indexes = [
            models.Index(
                fields=["employee_number"],
                name="idx_hr_employee_number",
            ),
            models.Index(
                fields=["nik"],
                name="idx_hr_employee_nik",
            ),
            models.Index(
                fields=["first_name", "last_name"],
                name="idx_hr_employee_name",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.employee_number} - {self.full_name}"

    def __str__(self) -> str:
        return f"{self.employee_number} - {self.full_name}"

    @property
    def full_name(self) -> str:
        parts = [
            self.first_name,
            self.last_name,
        ]

        return " ".join(
            part.strip()
            for part in parts
            if part and part.strip()
        )

    @property
    def display_name(self) -> str:
        return self.full_name