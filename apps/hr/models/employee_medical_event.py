from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models.base import BaseModel

from .employee import Employee


class EmployeeMedicalEvent(BaseModel):
    class MedicalType(models.TextChoices):
        MEDICAL_CHECKUP = "medical_checkup", "Medical Checkup"
        FITNESS_TO_WORK = "fitness_to_work", "Fitness to Work"
        DRUG_TEST = "drug_test", "Drug Test"
        VACCINATION = "vaccination", "Vaccination"
        VISION_TEST = "vision_test", "Vision Test"
        HEARING_TEST = "hearing_test", "Hearing Test"
        OTHER = "other", "Other"

    class FitnessStatus(models.TextChoices):
        NOT_APPLICABLE = "not_applicable", "Not Applicable"
        FIT = "fit", "Fit"
        FIT_WITH_RESTRICTION = (
            "fit_with_restriction",
            "Fit With Restriction",
        )
        TEMPORARY_UNFIT = (
            "temporary_unfit",
            "Temporary Unfit",
        )
        PERMANENT_UNFIT = (
            "permanent_unfit",
            "Permanent Unfit",
        )

    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="medical_events",
    )

    medical_type = models.CharField(
        max_length=40,
        choices=MedicalType.choices,
    )

    event_date = models.DateField()

    provider_name = models.CharField(
        max_length=200,
        blank=True,
        default="",
    )

    doctor_name = models.CharField(
        max_length=200,
        blank=True,
        default="",
    )

    result = models.CharField(
        max_length=150,
        blank=True,
        default="",
    )

    fitness_status = models.CharField(
        max_length=40,
        choices=FitnessStatus.choices,
        default=FitnessStatus.NOT_APPLICABLE,
    )

    restriction_notes = models.TextField(
        blank=True,
        default="",
    )

    next_due_date = models.DateField(
        null=True,
        blank=True,
    )

    attachment = models.FileField(
        upload_to="employees/medical/",
        null=True,
        blank=True,
    )

    is_confidential = models.BooleanField(
        default=True,
    )

    is_verified = models.BooleanField(
        default=False,
    )

    is_active = models.BooleanField(
        default=True,
    )

    notes = models.TextField(
        blank=True,
        default="",
    )

    class Meta:
        db_table = "hr_employee_medical_event"

        ordering = [
            "-event_date",
            "-created_at",
        ]

        indexes = [
            models.Index(
                fields=["employee"],
                name="idx_emp_med_employee",
            ),
            models.Index(
                fields=["medical_type"],
                name="idx_emp_med_type",
            ),
            models.Index(
                fields=["event_date"],
                name="idx_emp_med_date",
            ),
            models.Index(
                fields=["fitness_status"],
                name="idx_emp_med_fitness",
            ),
            models.Index(
                fields=["next_due_date"],
                name="idx_emp_med_next_due",
            ),
        ]

    def clean(self):
        super().clean()

        errors = {}

        if (
            self.event_date
            and self.next_due_date
            and self.next_due_date < self.event_date
        ):
            errors["next_due_date"] = (
                "Next Due Date tidak boleh lebih awal "
                "dari Event Date."
            )

        if (
            self.fitness_status
            == self.FitnessStatus.FIT_WITH_RESTRICTION
            and not self.restriction_notes.strip()
        ):
            errors["restriction_notes"] = (
                "Restriction Notes wajib diisi jika status "
                "Fit With Restriction."
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return (
            f"{self.employee.employee_number} - "
            f"{self.get_medical_type_display()} - "
            f"{self.event_date}"
        )