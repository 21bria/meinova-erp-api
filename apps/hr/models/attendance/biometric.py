"""
Pendaftaran biometrik wajah pegawai — siklus hidupnya saja (ATT-BIO-2A).

Yang **ada** di sini: siapa yang terdaftar, di penyedia mana, versi ke
berapa, kapan, oleh siapa, dan apakah sudah dicabut. Yang **tidak** ada
di sini dan tidak boleh ditambahkan: foto, template, embedding, vektor,
token, kredensial, atau handle rahasia milik penyedia. Materi biometrik
tinggal di penyedia; kredensial penyedia tinggal di settings deployment.

`subject_id`
------------
UUID acak (`uuid4`) yang **dibuat ERP** saat pendaftaran dan diserahkan
ke penyedia sebagai identitas subjeknya. Tidak diturunkan dari nomor
pegawai, nama, email, tenant, atau data bisnis lain; tidak bermakna dan
tidak memberi wewenang apa pun tanpa kredensial penyedia — karena itu
boleh disimpan tanpa enkripsi. Field ini **tidak boleh** memuat
kredensial, token akses, template biometrik, embedding, atau referensi
rahasia yang diterbitkan penyedia. Penyedia yang mengharuskan ERP
menyimpan rujukan rahasia/terbalikkan adalah keputusan arsitektur
keamanan ATT-BIO-2B, bukan isi field ini.

Foto profil (`Employee.avatar_file`, `Profile.avatar`) **bukan**
pendaftaran biometrik, dan tidak pernah didaftarkan otomatis.

Siklus hidup
------------
    ACTIVE ──revoke──► REVOKED   (final)

* Satu ACTIVE per (pegawai, penyedia) — unique bersyarat di database.
* Daftar ulang = cabut yang lama + baris **baru** dengan `version`
  berikutnya dan `subject_id` **baru**. Identitas yang sudah dicabut
  tidak pernah dipakai lagi; riwayat tidak pernah ditimpa.
* Kolom identitas (`employee`, `provider`, `subject_id`, `version`,
  `enrolled_*`) tidak bisa diubah; baris REVOKED beku seluruhnya.
* Tidak bisa dihapus lewat aplikasi (bukti audit, sama seperti
  `AttendanceLogVerification`) — karena itu `models.Model` polos, bukan
  `BaseModel` ber-soft-delete.

Tidak ada serializer, API, atau admin untuk model ini. Penulisannya
hanya lewat `BiometricEnrollmentService`.
"""

from __future__ import annotations

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class BiometricEnrollmentStatus(models.TextChoices):
    ACTIVE = "active", "Active"
    REVOKED = "revoked", "Revoked"


class BiometricEnrollmentSource(models.TextChoices):
    # Didaftarkan petugas HR (jalur yang diharapkan pertama kali ada).
    HR_ASSISTED = "hr_assisted", "HR Assisted"
    # Didaftarkan pegawai sendiri lewat alur penyedia (ATT-BIO-2B).
    SELF_SERVICE = "self_service", "Self Service"


IMMUTABLE_FIELDS = (
    "employee",
    "provider",
    "subject_id",
    "version",
    "enrollment_source",
    "enrolled_at",
    "enrolled_by",
)

FROZEN_WHEN_REVOKED = IMMUTABLE_FIELDS + (
    "status",
    "revoked_at",
    "revoked_by",
    "revocation_reason",
)

DELETE_MESSAGE = "Pendaftaran biometrik adalah bukti audit dan tidak bisa dihapus."


class BiometricEnrollmentQuerySet(models.QuerySet):
    def active(self):
        return self.filter(status=BiometricEnrollmentStatus.ACTIVE)

    def update(self, **kwargs):
        # Semua perubahan lewat `save()` supaya aturan kolom beku berlaku.
        raise ValidationError(
            "Pendaftaran biometrik hanya diubah lewat BiometricEnrollmentService.",
        )

    update.alters_data = True

    def delete(self):
        raise ValidationError(DELETE_MESSAGE)

    delete.alters_data = True
    delete.queryset_only = True


class EmployeeBiometricEnrollment(models.Model):
    employee = models.ForeignKey(
        "hr.Employee",
        on_delete=models.PROTECT,
        related_name="biometric_enrollments",
    )

    # Kode penyedia (adapter BIO-2B), mis. nama adapter + region. Bukan
    # kredensial.
    provider = models.CharField(max_length=50)

    # Lihat docstring modul: UUID acak buatan ERP, tidak rahasia.
    subject_id = models.UUIDField(
        default=uuid.uuid4,
        unique=True,
        editable=False,
    )

    # 1, 2, 3, … per (pegawai, penyedia). Naik setiap daftar ulang.
    version = models.PositiveIntegerField()

    status = models.CharField(
        max_length=20,
        choices=BiometricEnrollmentStatus.choices,
        default=BiometricEnrollmentStatus.ACTIVE,
        db_index=True,
    )

    enrollment_source = models.CharField(
        max_length=20,
        choices=BiometricEnrollmentSource.choices,
    )

    enrolled_at = models.DateTimeField()
    enrolled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        # PROTECT, bukan SET_NULL: pelaku pendaftaran/pencabutan adalah
        # bagian bukti audit dan tidak boleh hilang diam-diam.
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )

    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        # PROTECT, bukan SET_NULL: pelaku pendaftaran/pencabutan adalah
        # bagian bukti audit dan tidak boleh hilang diam-diam.
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
    )
    revocation_reason = models.CharField(max_length=255, blank=True, default="")

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = BiometricEnrollmentQuerySet.as_manager()

    class Meta:
        db_table = "hr_employee_biometric_enrollment"
        ordering = ["employee_id", "provider", "-version"]

        constraints = [
            models.UniqueConstraint(
                fields=["employee", "provider"],
                condition=Q(status="active"),
                name="uq_hr_bio_enroll_one_active",
            ),
            models.UniqueConstraint(
                fields=["employee", "provider", "version"],
                name="uq_hr_bio_enroll_version",
            ),
            models.CheckConstraint(
                condition=(
                    Q(status="active", revoked_at__isnull=True)
                    | Q(status="revoked", revoked_at__isnull=False)
                ),
                name="ck_hr_bio_enroll_revoked_at",
            ),
        ]

    def __str__(self) -> str:
        # Tanpa `subject_id`: string model ini bisa sampai ke log.
        return f"{self.employee_id} {self.provider} v{self.version} {self.status}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            columns = {
                name: self._meta.get_field(name).attname
                for name in FROZEN_WHEN_REVOKED
            }

            stored = (
                type(self).objects
                .filter(pk=self.pk)
                .values(*columns.values())
                .first()
            )

            if stored:
                frozen = (
                    FROZEN_WHEN_REVOKED
                    if stored["status"] == BiometricEnrollmentStatus.REVOKED
                    else IMMUTABLE_FIELDS
                )

                changed = [
                    name
                    for name in frozen
                    if stored[columns[name]] != getattr(self, columns[name])
                ]

                if changed:
                    raise ValidationError(
                        "Kolom pendaftaran biometrik tidak bisa diubah: "
                        f"{', '.join(changed)}.",
                    )

        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError(DELETE_MESSAGE)
