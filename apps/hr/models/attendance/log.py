from __future__ import annotations


from django.db import models
from django.db.models import Q
from .choices import (
    AttendanceLogType,
    AttendanceSource,
)

class AttendanceLog(models.Model):
    """
    Raw log presensi.

    Jangan langsung mengganti atau menghapus log ini ketika
    melakukan kalkulasi ulang attendance harian.
    """

    employee = models.ForeignKey(
        "hr.Employee",
        on_delete=models.PROTECT,
        related_name="attendance_logs",
        null=True,
        blank=True,
    )

    attendance = models.ForeignKey(
        "hr.EmployeeAttendance",
        on_delete=models.SET_NULL,
        related_name="logs",
        null=True,
        blank=True,
    )

    device = models.ForeignKey(
        "hr.AttendanceDevice",
        on_delete=models.SET_NULL,
        related_name="attendance_logs",
        null=True,
        blank=True,
    )

    company = models.ForeignKey(
        "administration.Company",
        on_delete=models.PROTECT,
        related_name="attendance_logs",
    )

    branch = models.ForeignKey(
        "administration.Branch",
        on_delete=models.SET_NULL,
        related_name="attendance_logs",
        null=True,
        blank=True,
    )

    location = models.ForeignKey(
        "administration.Location",
        on_delete=models.SET_NULL,
        related_name="attendance_logs",
        null=True,
        blank=True,
    )

    occurred_at = models.DateTimeField(db_index=True)
    log_type = models.CharField(
        max_length=20,
        choices=AttendanceLogType.choices,
        default=AttendanceLogType.UNKNOWN,
        db_index=True,
    )

    source = models.CharField(
        max_length=20,
        choices=AttendanceSource.choices,
        default=AttendanceSource.DEVICE,
        db_index=True,
    )

    employee_identifier = models.CharField(
        max_length=150,
        blank=True,
        default="",
        db_index=True,
        help_text=(
            "Employee number, PIN, card number, "
            "or external machine identifier."
        ),
    )

    external_id = models.CharField(max_length=200,blank=True,default="",db_index=True)

    latitude = models.DecimalField(max_digits=10,decimal_places=7,null=True,blank=True)
    longitude = models.DecimalField(max_digits=10,decimal_places=7,null=True,blank=True)

    address = models.CharField(max_length=500,blank=True,default="",)
    photo = models.ForeignKey(
        "uploads.UploadedFile",
        on_delete=models.SET_NULL,
        related_name="attendance_log_photos",
        null=True,
        blank=True,
    )

    raw_payload = models.JSONField(default=dict,blank=True)
    import_batch_id = models.CharField(max_length=100,blank=True,default="",db_index=True)
    is_processed = models.BooleanField(default=False,db_index=True,)
    processed_at = models.DateTimeField(null=True,blank=True)
    processing_error = models.TextField(blank=True,default="",)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "hr_attendance_log"

        ordering = [
            "-occurred_at",
            "-id",
        ]

        constraints = [
            models.UniqueConstraint(
                fields=[
                    "source",
                    "external_id",
                ],
                condition=~Q(external_id=""),
                name="uq_hr_att_log_source_external",
            ),
        ]

        indexes = [
            models.Index(
                fields=[
                    "employee",
                    "occurred_at",
                ],
                name="idx_hr_att_log_emp_time",
            ),
            models.Index(
                fields=[
                    "device",
                    "occurred_at",
                ],
                name="idx_hr_att_log_device_time",
            ),
            models.Index(
                fields=[
                    "company",
                    "location",
                    "occurred_at",
                ],
                name="idx_hr_att_log_org_time",
            ),
            models.Index(
                fields=[
                    "is_processed",
                    "occurred_at",
                ],
                name="idx_hr_att_log_process_time",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.employee_identifier or self.employee_id} "
            f"{self.log_type} {self.occurred_at}"
        )