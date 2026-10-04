"""
Jembatan antara **identitas di mesin** dan **pegawai di ERP**.

Mesin absensi menyimpan nomor enroll-nya sendiri — `1`, `4`, `0001`,
`25064` — dan nomor itu tidak punya hubungan apa pun dengan Employee
Number. Nomor yang sama dipakai ulang di mesin lain untuk orang lain,
dan itu wajar: enroll dilakukan di masing-masing site oleh orang yang
tidak saling tahu.

Karena itu identitasnya **berpasangan dengan device**, bukan berdiri
sendiri:

    SITE-A | 0001 -> Employee A
    SITE-B | 0001 -> Employee B

Keduanya sah, dan constraint uniknya harus mengizinkan itu.

Yang **tidak** dilakukan tabel ini: membuat pegawai. File mesin cuma
membawa identifier eksternal; Employee ERP tetap satu-satunya sumber
kebenaran tentang siapa yang bekerja di sini. Nomor yang belum
dipetakan dilaporkan sebagai baris yang tidak bisa diimport, bukan
diam-diam menerbitkan orang baru.
"""

from __future__ import annotations

from django.db import models
from django.db.models import Q

from apps.core.models import BaseModel


class AttendanceDeviceEmployee(BaseModel):
    device = models.ForeignKey(
        "hr.AttendanceDevice",
        on_delete=models.CASCADE,
        related_name="employee_mappings",
    )

    external_employee_id = models.CharField(
        max_length=150,
        db_index=True,
        help_text=(
            "Nomor pegawai menurut mesin (No.ID / PIN / enroll "
            "number). Bukan Employee Number ERP."
        ),
    )

    employee = models.ForeignKey(
        "hr.Employee",
        on_delete=models.PROTECT,
        related_name="device_mappings",
    )

    notes = models.TextField(
        blank=True,
        default="",
    )

    class Meta:
        db_table = "hr_attendance_device_employee"

        ordering = [
            "device_id",
            "external_employee_id",
        ]

        constraints = [
            # Satu nomor mesin menunjuk satu orang **pada device itu**.
            # `is_deleted=False` ikut jadi syarat: pemetaan yang dihapus
            # harus boleh dibuat ulang, dan tanpa itu nomor yang salah
            # petakan terkunci selamanya.
            models.UniqueConstraint(
                fields=[
                    "device",
                    "external_employee_id",
                ],
                condition=Q(is_deleted=False),
                name="uq_hr_att_device_employee_external",
            ),
        ]

        indexes = [
            models.Index(
                fields=[
                    "device",
                    "is_active",
                ],
                name="idx_hr_att_dev_emp_active",
            ),
        ]

    def __str__(self) -> str:
        return (
            f"{self.device_id}/{self.external_employee_id} "
            f"-> {self.employee_id}"
        )
