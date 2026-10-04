from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models.base import BaseModel

from .employee import Employee


class TrainingProgramStatus(models.TextChoices):
    PLANNED = "planned", "Planned"
    ONGOING = "ongoing", "Ongoing"
    COMPLETED = "completed", "Completed"
    CANCELLED = "cancelled", "Cancelled"


class ParticipantStatus(models.TextChoices):
    REGISTERED = "registered", "Registered"
    ATTENDED = "attended", "Attended"
    ABSENT = "absent", "Absent"
    CANCELLED = "cancelled", "Cancelled"


class TrainingProgram(BaseModel):
    """
    Batch/penyelenggaraan pelatihan — beda dari `EmployeeTraining`, yang
    adalah riwayat pelatihan milik satu pegawai (termasuk pelatihan yang
    diikuti sebelum bergabung, di luar program internal). Program yang
    selesai dapat dicatatkan balik ke riwayat pegawai lewat
    `TrainingParticipant.employee_training`.
    """

    # Kode unik per tenant, bukan per company: program pelatihan lazim
    # lintas company dalam satu grup.
    code = models.CharField(max_length=50)
    name = models.CharField(max_length=200)

    training_category = models.ForeignKey(
        "administration.TrainingCategory",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="training_programs",
    )

    provider = models.ForeignKey(
        "administration.TrainingProvider",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="training_programs",
    )

    company = models.ForeignKey(
        "administration.Company",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="training_programs",
    )

    start_date = models.DateField()
    end_date = models.DateField(
        null=True,
        blank=True,
    )

    duration_hours = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
    )

    # Teks bebas, bukan FK ke Location: pelatihan sering di hotel /
    # kantor vendor yang tidak ada di master lokasi kerja.
    venue = models.CharField(
        max_length=255,
        blank=True,
        default="",
    )

    quota = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
    )

    cost = models.DecimalField(
        max_digits=18,
        decimal_places=2,
        null=True,
        blank=True,
    )

    currency = models.ForeignKey(
        "administration.Currency",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="training_programs",
    )

    status = models.CharField(
        max_length=20,
        choices=TrainingProgramStatus.choices,
        default=TrainingProgramStatus.PLANNED,
    )

    is_mandatory = models.BooleanField(default=False)

    description = models.TextField(
        blank=True,
        default="",
    )

    class Meta:
        db_table = "hr_training_program"

        ordering = [
            "-start_date",
            "name",
        ]

        constraints = [
            models.UniqueConstraint(
                fields=["code"],
                condition=Q(is_deleted=False),
                name="uniq_active_hr_training_program_code",
            ),
        ]

        indexes = [
            models.Index(
                fields=["training_category"],
                name="idx_training_prog_category",
            ),
            models.Index(
                fields=["start_date"],
                name="idx_training_prog_start",
            ),
            models.Index(
                fields=["status"],
                name="idx_training_prog_status",
            ),
        ]

    @property
    def participant_count(self) -> int:
        return self.participants.filter(is_deleted=False).count()

    def clean(self):
        super().clean()

        errors = {}

        if (
            self.start_date
            and self.end_date
            and self.end_date < self.start_date
        ):
            errors["end_date"] = (
                "End Date tidak boleh lebih awal dari Start Date."
            )

        if self.quota is not None and self.quota <= 0:
            errors["quota"] = "Quota harus lebih besar dari nol."

        if self.cost is not None and self.cost < 0:
            errors["cost"] = "Cost tidak boleh negatif."

        if self.cost is not None and self.cost > 0 and self.currency_id is None:
            errors["currency"] = (
                "Currency wajib diisi jika Cost diisi."
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.code} - {self.name}"


class TrainingParticipant(BaseModel):
    program = models.ForeignKey(
        TrainingProgram,
        on_delete=models.CASCADE,
        related_name="participants",
    )

    employee = models.ForeignKey(
        Employee,
        on_delete=models.PROTECT,
        related_name="training_participations",
    )

    status = models.CharField(
        max_length=20,
        choices=ParticipantStatus.choices,
        default=ParticipantStatus.REGISTERED,
    )

    score = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
    )

    # Null = belum dinilai. Sengaja bukan default False supaya peserta
    # yang belum diuji tidak terbaca sebagai tidak lulus.
    is_passed = models.BooleanField(
        null=True,
        blank=True,
    )

    certificate_number = models.CharField(
        max_length=100,
        blank=True,
        default="",
    )

    # Terisi kalau hasil program ini sudah dicatatkan ke riwayat pegawai.
    employee_training = models.OneToOneField(
        "hr.EmployeeTraining",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="training_participant",
    )

    notes = models.TextField(
        blank=True,
        default="",
    )

    class Meta:
        db_table = "hr_training_participant"

        ordering = [
            "program",
            "employee",
        ]

        constraints = [
            models.UniqueConstraint(
                fields=["program", "employee"],
                condition=Q(is_deleted=False),
                name="uniq_active_hr_training_participant",
            ),
        ]

        indexes = [
            models.Index(
                fields=["employee"],
                name="idx_training_part_employee",
            ),
            models.Index(
                fields=["status"],
                name="idx_training_part_status",
            ),
        ]

    def clean(self):
        super().clean()

        errors = {}

        if self.score is not None and self.score < 0:
            errors["score"] = "Score tidak boleh negatif."

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return f"{self.program_id} - {self.employee.employee_number}"
