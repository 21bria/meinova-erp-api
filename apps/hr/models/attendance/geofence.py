"""
Area kerja untuk tap Self Service (ATT-GPS-1).

Satu lingkaran (titik pusat + radius meter) per `administration.Location`
— lokasi kerja yang sama dengan yang dipakai penempatan pegawai
(`OrganizationAssignment.location`). Pemeriksaannya (`GeofenceCheck`)
memakai jarak Haversine di Python; tidak ada GIS/PostGIS.

Satu geofence **aktif** per lokasi (unique bersyarat). Menggantinya =
nonaktifkan yang lama, buat yang baru; riwayatnya tetap ada. Bukti tap
menyimpan jarak dan radius yang **dipakai saat itu**, jadi mengubah
geofence besok tidak mengubah penjelasan tap hari ini.
"""

from __future__ import annotations

from decimal import Decimal

from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models import Q

from apps.core.models.base import BaseModel


class AttendanceGeofence(BaseModel):
    location = models.ForeignKey(
        "administration.Location",
        on_delete=models.PROTECT,
        related_name="attendance_geofences",
    )

    # Presisi sama dengan `AttendanceLog.latitude/longitude` (7 desimal,
    # ~1 cm).
    latitude = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        validators=[
            MinValueValidator(Decimal("-90")),
            MaxValueValidator(Decimal("90")),
        ],
    )
    longitude = models.DecimalField(
        max_digits=10,
        decimal_places=7,
        validators=[
            MinValueValidator(Decimal("-180")),
            MaxValueValidator(Decimal("180")),
        ],
    )

    radius_m = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        help_text="Radius area kerja dalam meter, dari titik pusat.",
    )

    class Meta:
        db_table = "hr_attendance_geofence"
        ordering = ["location_id", "-id"]

        constraints = [
            models.UniqueConstraint(
                fields=["location"],
                condition=Q(is_active=True, is_deleted=False),
                name="uq_hr_att_geofence_active_location",
            ),
            models.CheckConstraint(
                condition=Q(latitude__gte=-90, latitude__lte=90),
                name="ck_hr_att_geofence_latitude",
            ),
            models.CheckConstraint(
                condition=Q(longitude__gte=-180, longitude__lte=180),
                name="ck_hr_att_geofence_longitude",
            ),
            models.CheckConstraint(
                condition=Q(radius_m__gt=0),
                name="ck_hr_att_geofence_radius",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.location_id} r={self.radius_m}m"
