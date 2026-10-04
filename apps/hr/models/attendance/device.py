from __future__ import annotations
from django.db import models

from .choices import AttendanceDeviceType

class AttendanceDevice(models.Model):
    """
    Registry mesin presensi.
    Mendukung mesin fingerprint, face recognition, RFID,
    mobile, atau integrasi vendor lain.
    """

    company = models.ForeignKey(
        "administration.Company",
        on_delete=models.CASCADE,
        related_name="attendance_devices",
    )

    branch = models.ForeignKey(
        "administration.Branch",
        on_delete=models.SET_NULL,
        related_name="attendance_devices",
        null=True,
        blank=True,

    )

    location = models.ForeignKey(
        "administration.Location",
        on_delete=models.SET_NULL,
        related_name="attendance_devices",
        null=True,
        blank=True,
    )

    code = models.CharField(max_length=100,unique=True)

    name = models.CharField(max_length=150)

    device_type = models.CharField(max_length=30,choices=AttendanceDeviceType.choices,default=AttendanceDeviceType.FINGERPRINT)

    vendor = models.CharField(max_length=150,blank=True,default="",)
    model_name = models.CharField(max_length=150,blank=True,default="")
    serial_number = models.CharField(max_length=150,blank=True,default="",db_index=True)
    ip_address = models.GenericIPAddressField(null=True,blank=True)

    port = models.PositiveIntegerField(null=True,blank=True)
    timezone = models.CharField(max_length=50,default="Asia/Jakarta",)
    # Profil format file yang dikeluarkan mesin ini.
    #
    # Menempel di device, bukan di importer: satu tenant lazim punya
    # beberapa merek mesin dengan header berbeda, dan yang membedakan
    # mereka adalah **mesinnya**, bukan lokasi atau perusahaannya.
    # Boleh kosong — device yang datanya masuk lewat agent on-premise
    # tidak pernah menghasilkan file.
    import_profile = models.ForeignKey(
        "imports.ImportProfile",
        on_delete=models.SET_NULL,
        related_name="attendance_devices",
        null=True,
        blank=True,
    )

    integration_key = models.CharField(max_length=255,blank=True,default="",)

    # ------------------------------------------------------------------
    # Kredensial agent (SEC-ATT-SYNC-1)
    #
    # Satu device = satu kredensial mesin, hidup di schema tenant-nya.
    # Yang disimpan hanya `agent_key_id` (bagian publik, untuk mencari
    # barisnya) dan hash Django (`make_password`) atas
    # `tenant_id:key_id:secret` — tenant ikut di-hash, jadi baris yang
    # disalin ke schema lain pun tidak bisa dipakai di sana. Secret mentah
    # tidak pernah disimpan dan hanya ditampilkan sekali saat diterbitkan.
    # Rotasi = terbitkan ulang (yang lama langsung mati); cabut = kosongkan.
    # Lihat `apps.hr.api.attendance_sync.credentials`.
    # ------------------------------------------------------------------
    agent_key_id = models.CharField(max_length=32, blank=True, default="", db_index=True)
    agent_key_hash = models.CharField(max_length=255, blank=True, default="")
    agent_key_issued_at = models.DateTimeField(null=True, blank=True)
    agent_key_revoked_at = models.DateTimeField(null=True, blank=True)
    last_sync_at = models.DateTimeField(null=True,blank=True,)
    is_active = models.BooleanField(default=True)

    notes = models.TextField(blank=True,default="")
    created_at = models.DateTimeField(auto_now_add=True,)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "hr_attendance_device"
        ordering = [
            "company_id",
            "location_id",
            "name",
        ]
        constraints = [
            # Id kunci menentukan baris mana yang hash-nya diperiksa;
            # dua device ber-id sama membuat pencariannya ambigu.
            models.UniqueConstraint(
                fields=["agent_key_id"],
                condition=~models.Q(agent_key_id=""),
                name="uq_hr_att_device_agent_key_id",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.code} - {self.name}"