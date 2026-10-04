# apps/hr/models/employee_document.py

from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models.base import BaseModel
from apps.administration.models import DocumentType

from .employee import Employee

from apps.uploads.models import UploadedFile

class EmployeeDocument(BaseModel):
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="documents",
    )

    document_type = models.ForeignKey(
        DocumentType,
        on_delete=models.PROTECT,
        related_name="employee_documents",
    )

    document_name = models.CharField(max_length=200)

    document_number = models.CharField(max_length=150,blank=True,default="")
    issue_date = models.DateField(null=True,blank=True)
    expiry_date = models.DateField(null=True,blank=True)
    issuing_authority = models.CharField(max_length=200,blank=True,default="")

    uploaded_file = models.OneToOneField(
        UploadedFile,
        on_delete=models.PROTECT,
        related_name="+",
        null=True,
        blank=True,
    )
    
    is_required = models.BooleanField(default=False)
    is_verified = models.BooleanField(default=False)
    verification_notes = models.TextField(blank=True,default="" )
    is_active = models.BooleanField(default=True)
    notes = models.TextField(blank=True,default="")

    class Meta:
        db_table = "hr_employee_document"

        ordering = [
            "document_type__sort_order",
            "document_name",
        ]

        indexes = [
            models.Index(
                fields=["employee"],
                name="idx_emp_doc_employee",
            ),
            models.Index(
                fields=["document_type"],
                name="idx_emp_doc_type",
            ),
            models.Index(
                fields=["expiry_date"],
                name="idx_emp_doc_expiry",
            ),
            models.Index(
                fields=["is_verified"],
                name="idx_emp_doc_verified",
            ),
        ]

    def clean(self):
        super().clean()

        errors = {}

        if (
            self.issue_date
            and self.expiry_date
            and self.expiry_date
            < self.issue_date
        ):
            errors["expiry_date"] = (
                "Expiry Date cannot be earlier "
                "than Issue Date."
            )

        if (
            self.is_required
            and not self.file
        ):
            errors["file"] = (
                "Attachment is required."
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return (
            f"{self.employee.employee_number} - "
            f"{self.document_name}"
        )