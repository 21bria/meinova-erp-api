from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models.base import BaseModel
from apps.administration.models import (
    CertificateType
)

from .employee import Employee


class EmployeeCertificate(BaseModel):
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="certificates",
    )

    certificate_type = models.ForeignKey(
        CertificateType,
        on_delete=models.PROTECT,
        related_name="employee_certificates",
    )

    certificate_name = models.CharField(
        max_length=200,
    )

    certificate_number = models.CharField(
        max_length=100,
        blank=True,
        default="",
    )

    issuing_organization = models.CharField(
        max_length=200,
        blank=True,
        default="",
    )

    issue_date = models.DateField(
        null=True,
        blank=True,
    )

    expiry_date = models.DateField(
        null=True,
        blank=True,
    )

    credential_id = models.CharField(
        max_length=150,
        blank=True,
        default="",
    )

    credential_url = models.URLField(
        blank=True,
        default="",
    )

    attachment = models.FileField(
        upload_to="employees/certificates/",
        null=True,
        blank=True,
    )

    is_lifetime = models.BooleanField(
        default=False,
    )

    is_verified = models.BooleanField(
        default=False,
    )

    verification_notes = models.TextField(
        blank=True,
        default="",
    )

    is_active = models.BooleanField(
        default=True,
    )

    notes = models.TextField(
        blank=True,
        default="",
    )

    class Meta:
        db_table = "hr_employee_certificate"

        ordering = [
            "-issue_date",
            "certificate_name",
        ]

        indexes = [
            models.Index(
                fields=["employee"],
                name="idx_emp_cert_employee",
            ),
            models.Index(
                fields=["certificate_type"],
                name="idx_emp_cert_type",
            ),
            models.Index(
                fields=["expiry_date"],
                name="idx_emp_cert_expiry",
            ),
            models.Index(
                fields=["is_verified"],
                name="idx_emp_cert_verified",
            ),
        ]

    def clean(self):
        super().clean()

        errors = {}

        if (
            self.issue_date
            and self.expiry_date
            and self.expiry_date < self.issue_date
        ):
            errors["expiry_date"] = (
                "Expiry Date tidak boleh lebih awal "
                "dari Issue Date."
            )

        if self.is_lifetime and self.expiry_date:
            errors["expiry_date"] = (
                "Expiry Date harus kosong jika sertifikat "
                "berlaku seumur hidup."
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return (
            f"{self.employee.employee_number} - "
            f"{self.certificate_name}"
        )