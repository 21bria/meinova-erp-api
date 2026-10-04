from datetime import datetime, timedelta

from django.core.exceptions import ValidationError
from django.db import models

from apps.core.models.base import BaseModel

from .employee import Employee


class OvertimeStatus(models.TextChoices):
    """
    Sama seperti EmployeeLeave: dipakai sebagai pencatatan. Nilai untuk
    alur approval sudah disiapkan supaya tidak perlu migrasi ulang.
    """

    RECORDED = "recorded", "Recorded"
    CANCELLED = "cancelled", "Cancelled"

    DRAFT = "draft", "Draft"
    SUBMITTED = "submitted", "Submitted"
    APPROVED = "approved", "Approved"
    REJECTED = "rejected", "Rejected"


class EmployeeOvertime(BaseModel):
    employee = models.ForeignKey(
        Employee,
        on_delete=models.CASCADE,
        related_name="overtimes",
    )

    company = models.ForeignKey(
        "administration.Company",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_overtimes",
    )

    branch = models.ForeignKey(
        "administration.Branch",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_overtimes",
    )

    location = models.ForeignKey(
        "administration.Location",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_overtimes",
    )

    overtime_type = models.ForeignKey(
        "administration.OvertimeType",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="employee_overtimes",
    )

    work_date = models.DateField()

    start_time = models.TimeField()
    end_time = models.TimeField()

    # Diisi otomatis oleh service dari start/end kalau kosong. Disimpan
    # sebagai menit supaya bisa dijumlahkan tanpa konversi.
    duration_minutes = models.PositiveIntegerField(
        null=True,
        blank=True,
    )

    status = models.CharField(
        max_length=20,
        choices=OvertimeStatus.choices,
        default=OvertimeStatus.RECORDED,
    )

    # Lembur yang tidak dibayar (mis. diganti dengan libur pengganti)
    # tetap perlu tercatat untuk rekap jam kerja.
    is_paid = models.BooleanField(default=True)

    reason = models.CharField(
        max_length=255,
        blank=True,
        default="",
    )

    notes = models.TextField(
        blank=True,
        default="",
    )

    class Meta:
        db_table = "hr_employee_overtime"

        ordering = [
            "-work_date",
            "employee",
        ]

        indexes = [
            models.Index(
                fields=["employee"],
                name="idx_emp_ot_employee",
            ),
            models.Index(
                fields=["work_date"],
                name="idx_emp_ot_work_date",
            ),
            models.Index(
                fields=["overtime_type"],
                name="idx_emp_ot_type",
            ),
            models.Index(
                fields=["status"],
                name="idx_emp_ot_status",
            ),
        ]

    def calculate_duration_minutes(self) -> int | None:
        """
        Lembur lewat tengah malam itu hal biasa (shift malam), jadi
        end_time < start_time diperlakukan sebagai hari berikutnya —
        bukan error.
        """
        if not self.start_time or not self.end_time:
            return None

        base = datetime(2000, 1, 1)

        start = datetime.combine(base, self.start_time)
        end = datetime.combine(base, self.end_time)

        if end <= start:
            end += timedelta(days=1)

        return int((end - start).total_seconds() // 60)

    @property
    def duration_hours(self):
        if self.duration_minutes is None:
            return None

        return round(self.duration_minutes / 60, 2)

    def clean(self):
        super().clean()

        errors = {}

        if (
            self.duration_minutes is not None
            and self.duration_minutes <= 0
        ):
            errors["duration_minutes"] = (
                "Durasi lembur harus lebih besar dari nol."
            )

        # 16 jam dipakai sebagai pagar kewarasan, bukan aturan bisnis:
        # nilai di atas itu hampir selalu salah isi jam.
        if (
            self.duration_minutes is not None
            and self.duration_minutes > 16 * 60
        ):
            errors["duration_minutes"] = (
                "Durasi lembur melebihi 16 jam — periksa jam mulai "
                "dan jam selesai."
            )

        if errors:
            raise ValidationError(errors)

    def __str__(self):
        return (
            f"{self.employee.employee_number} - "
            f"{self.work_date} "
            f"({self.start_time} - {self.end_time})"
        )
