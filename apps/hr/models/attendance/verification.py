"""
Hasil pemeriksaan satu tap Self Service — anak 1:1 `AttendanceLog`.

Pembagiannya:

* `AttendanceLog`        — **bukti mentah**: jam server, IN/OUT,
                           koordinat yang dikirim, selfie, payload.
* `AttendanceLogVerification` — **turunan**: apa kata tiap pemeriksaan,
                           apa keputusannya, dan kenapa.
* `EmployeeAttendance`   — **kesimpulan harian**, satu-satunya yang
                           dibaca Close dan Payroll.

Koordinat tidak disalin ke sini; yang disimpan hasil penilaiannya
(akurasi yang dinilai, jarak ke geofence). Satu fakta, satu tempat.

Kenapa bukan `BaseModel` / soft delete
--------------------------------------
Ini bukti audit, sama seperti `AttendanceLog` yang juga `models.Model`
polos. Bukti yang bisa di-soft-delete lalu dibuat ulang bukan bukti.
`on_delete=PROTECT` ke log-nya karena alasan yang sama.

Bukti yang sudah diputuskan tidak bisa diubah atau dihapus
--------------------------------------------------------
Begitu `decision` meninggalkan PENDING, **seluruh** kolom bukti
(`FROZEN_FIELDS`, termasuk `reason_detail`) beku di semua jalur ORM yang
didukung aplikasi:

* `instance.save()`                     — menolak perubahan kolom beku
* `QuerySet.update()` / `bulk_update()` — menolak kalau menyentuh kolom
  beku pada baris final; baris PENDING tetap bisa diisi
* `instance.delete()` / `QuerySet.delete()` — menolak baris final

Satu-satunya jalan membuang bukti final: `purge_for_governed_reset()`,
dipakai hanya oleh pembongkaran data demo yang sudah dijaga
(`demo_erp.reset`, `demo_erp.legacy_cleanup`, `hr.seeds.demo_reset`).

**Ini kekebalan tingkat aplikasi, bukan tingkat database.** SQL mentah,
`_base_manager`, dan akses DBA langsung tidak dihalangi — tidak ada
trigger atau hak akses database yang menjaganya.

Wajah yang tidak cocok tetap tercatat tidak cocok selamanya; koreksi
kehadiran — kalau perlu — lewat proses koreksi presensi HR yang terpisah.
Tahap peninjauan nanti menambah kolom resolusinya sendiri, tidak menimpa
hasil di sini.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.db import models


class PunchDecision(models.TextChoices):
    # Baris baru lahir PENDING di dalam transaksi yang sama dengan
    # keputusannya; PENDING yang tersimpan berarti proses terputus.
    PENDING = "pending", "Pending"
    ACCEPTED = "accepted", "Accepted"
    # Tidak memenuhi syarat menjadi kehadiran (pemeriksaan gagal, IN/OUT
    # tidak sah, terlalu rapat). Pegawai boleh mencoba lagi.
    REJECTED = "rejected", "Rejected"
    # Pemeriksaannya lolos, tapi keadaan bisnis hari itu (cuti, sudah
    # ditutup mangkir, payroll terkunci) melarang penerapan otomatis.
    REVIEW_REQUIRED = "review_required", "Review Required"


class PunchCheckRequirement(models.TextChoices):
    REQUIRED = "required", "Required"
    NOT_REQUIRED = "not_required", "Not Required"


class BiometricCheckResult(models.TextChoices):
    """Wajah dan liveness."""

    # Kebijakan tidak mewajibkannya; tidak dijalankan.
    NOT_REQUIRED = "not_required", "Not Required"
    # Wajib, tapi tidak ada mesin yang terpasang.
    NOT_CONFIGURED = "not_configured", "Not Configured"
    # Wajib dan terpasang, tapi tidak dijalankan: bukti kurang, atau
    # pemeriksaan sebelumnya sudah gagal.
    NOT_RUN = "not_run", "Not Run"
    PASS = "pass", "Pass"
    # Wajah: tidak cocok dengan pendaftaran. Liveness: bukan tangkapan
    # orang hidup.
    FAIL = "fail", "Fail"
    ERROR = "error", "Error"

    # ATT-BIO-2A. Selfie normal memuat tepat satu wajah; mesin tidak
    # boleh memilih salah satu wajah secara sembarang.
    NO_FACE = "no_face", "No Face Detected"
    MULTIPLE_FACES = "multiple_faces", "Multiple Faces"
    # Wajah: pegawai tidak punya pendaftaran ACTIVE di penyedia mesin
    # wajah yang terpasang. Ditetapkan service, bukan mesin.
    NOT_ENROLLED = "not_enrolled", "Not Enrolled"


class LocationCheckResult(models.TextChoices):
    NOT_REQUIRED = "not_required", "Not Required"
    NOT_CONFIGURED = "not_configured", "Not Configured"
    NOT_RUN = "not_run", "Not Run"
    PASS = "pass", "Pass"
    LOW_ACCURACY = "low_accuracy", "Low Accuracy"
    # Perangkat tidak mengirim koordinat.
    UNAVAILABLE = "unavailable", "Unavailable"
    ERROR = "error", "Error"


class GeofenceCheckResult(models.TextChoices):
    NOT_REQUIRED = "not_required", "Not Required"
    NOT_CONFIGURED = "not_configured", "Not Configured"
    NOT_RUN = "not_run", "Not Run"
    INSIDE = "inside", "Inside"
    OUTSIDE = "outside", "Outside"
    ERROR = "error", "Error"
    # ATT-GPS-1. Mesin geofence terpasang, tapi lokasi kerja pegawai
    # belum punya geofence aktif.
    NO_GEOFENCE = "no_geofence", "No Geofence For Work Location"
    # Pegawai tidak punya lokasi kerja dari penempatan aktifnya.
    NO_WORK_LOCATION = "no_work_location", "No Work Location"


class PunchReason(models.TextChoices):
    """
    Sebab keputusan selain ACCEPTED. Kode stabil — frontend dan laporan
    bergantung padanya; teks label boleh berubah, nilainya tidak.
    """

    # Ritme
    PUNCH_TOO_SOON = "punch_too_soon", "Punch too soon after the previous one"

    # IN/OUT
    DUPLICATE_CHECK_IN = "duplicate_check_in", "Already checked in"
    CHECK_OUT_WITHOUT_CHECK_IN = (
        "check_out_without_check_in",
        "Check out without check in",
    )
    DUPLICATE_CHECK_OUT = "duplicate_check_out", "Already checked out"

    # Pemeriksaan
    LOCATION_NOT_VERIFIED = "location_not_verified", "Location not verified"
    LOCATION_UNAVAILABLE = "location_unavailable", "Location unavailable"
    LOCATION_LOW_ACCURACY = "location_low_accuracy", "Location accuracy too low"
    GEOFENCE_NOT_VERIFIED = "geofence_not_verified", "Geofence not verified"
    OUTSIDE_GEOFENCE = "outside_geofence", "Outside geofence"
    LIVENESS_NOT_VERIFIED = "liveness_not_verified", "Liveness not verified"
    LIVENESS_FAILED = "liveness_failed", "Liveness failed"
    FACE_NOT_VERIFIED = "face_not_verified", "Face not verified"
    FACE_MISMATCH = "face_mismatch", "Face mismatch"
    VALIDATOR_ERROR = "validator_error", "Validator error"

    # ATT-GPS-1
    GEOFENCE_NOT_CONFIGURED = (
        "geofence_not_configured",
        "Work location has no geofence",
    )
    WORK_LOCATION_UNAVAILABLE = (
        "work_location_unavailable",
        "Work location unavailable",
    )
    # Mode uji coba GPS: tap tidak pernah menjadi kehadiran, apa pun hasil
    # pemeriksaannya.
    TRIAL_NOT_RECORDED = "trial_not_recorded", "Trial punch, attendance not recorded"

    # ATT-BIO-2A
    NO_FACE = "no_face", "No face detected"
    MULTIPLE_FACES = "multiple_faces", "Multiple faces detected"
    NOT_ENROLLED = "not_enrolled", "Not enrolled for face verification"
    # Byte selfie identik (SHA-256) dengan selfie yang pernah dipakai tap
    # pegawai yang sama. Bukan liveness, bukan pengenalan wajah.
    SELFIE_REPLAYED = "selfie_replayed", "Selfie already used"

    # Keadaan hari itu (REVIEW_REQUIRED)
    PAYROLL_PERIOD_LOCKED = "payroll_period_locked", "Payroll period locked"
    DAY_CLOSED_ABSENT = "day_closed_absent", "Day already closed as absent"
    ON_LEAVE = "on_leave", "On leave"


# Kolom yang beku begitu keputusan diambil: semua kecuali `id` dan cap
# waktu otomatis.
FROZEN_FIELDS = (
    "log",
    "decision",
    "reason_code",
    "reason_detail",
    "work_date",
    "face_result",
    "face_score",
    "face_threshold",
    "face_provider",
    "face_model_version",
    "liveness_result",
    "liveness_score",
    "liveness_threshold",
    "liveness_provider",
    "liveness_model_version",
    "location_result",
    "gps_accuracy_meters",
    "geofence_result",
    "distance_from_geofence_meters",
    "geofence_radius_meters",
    "policy_snapshot",
    "validated_at",
)


FINALIZED_MESSAGE = "Bukti verifikasi yang sudah diputuskan tidak bisa diubah."


def _frozen_names(fields) -> set[str]:
    """Nama field/kolom yang diminta, dinormalkan (`log_id` → `log`)."""
    names = set()

    for name in fields:
        name = str(name)
        names.add(name[:-3] if name.endswith("_id") else name)

    return names & set(FROZEN_FIELDS)


class AttendanceLogVerificationQuerySet(models.QuerySet):
    def _finalized(self):
        return self.exclude(decision=PunchDecision.PENDING)

    def update(self, **kwargs):
        if _frozen_names(kwargs):
            if self._finalized().exists():
                raise ValidationError(FINALIZED_MESSAGE)

            # Penyaring tambahan di SQL-nya sendiri: baris yang menjadi
            # final di antara pemeriksaan dan UPDATE tetap tidak tersentuh.
            return super(
                AttendanceLogVerificationQuerySet,
                self.filter(decision=PunchDecision.PENDING),
            ).update(**kwargs)

        return super().update(**kwargs)

    update.alters_data = True

    def bulk_update(self, objs, fields, batch_size=None):
        if _frozen_names(fields):
            pks = [obj.pk for obj in objs if obj.pk is not None]

            if self.model.objects.filter(pk__in=pks)._finalized().exists():
                raise ValidationError(FINALIZED_MESSAGE)

        return super().bulk_update(objs, fields, batch_size=batch_size)

    bulk_update.alters_data = True

    def delete(self):
        if self._finalized().exists():
            raise ValidationError(FINALIZED_MESSAGE)

        return super().delete()

    delete.alters_data = True
    delete.queryset_only = True

    def purge_for_governed_reset(self):
        """
        Hapus bukti apa adanya — **hanya** untuk pembongkaran data demo
        yang sudah dijaga cakupannya. Bukan jalur aplikasi.
        """
        return super().delete()

    purge_for_governed_reset.alters_data = True
    purge_for_governed_reset.queryset_only = True


def _score_field():
    return models.DecimalField(
        max_digits=9,
        decimal_places=6,
        null=True,
        blank=True,
    )


def _meters_field():
    return models.DecimalField(
        max_digits=10,
        decimal_places=2,
        null=True,
        blank=True,
    )


class AttendanceLogVerification(models.Model):
    log = models.OneToOneField(
        "hr.AttendanceLog",
        on_delete=models.PROTECT,
        related_name="verification",
    )

    decision = models.CharField(
        max_length=20,
        choices=PunchDecision.choices,
        default=PunchDecision.PENDING,
        db_index=True,
    )

    reason_code = models.CharField(
        max_length=40,
        choices=PunchReason.choices,
        blank=True,
        default="",
    )

    reason_detail = models.TextField(blank=True, default="")

    # Hari kerja hasil `workdate.resolve()` — tetap tercatat untuk tap
    # yang ditolak, yang `attendance`-nya kosong.
    work_date = models.DateField(null=True, blank=True)

    face_result = models.CharField(
        max_length=20,
        choices=BiometricCheckResult.choices,
        default=BiometricCheckResult.NOT_RUN,
    )
    face_score = _score_field()
    face_threshold = _score_field()
    face_provider = models.CharField(max_length=100, blank=True, default="")
    face_model_version = models.CharField(max_length=100, blank=True, default="")

    liveness_result = models.CharField(
        max_length=20,
        choices=BiometricCheckResult.choices,
        default=BiometricCheckResult.NOT_RUN,
    )
    liveness_score = _score_field()
    liveness_threshold = _score_field()
    liveness_provider = models.CharField(max_length=100, blank=True, default="")
    liveness_model_version = models.CharField(
        max_length=100,
        blank=True,
        default="",
    )

    location_result = models.CharField(
        max_length=20,
        choices=LocationCheckResult.choices,
        default=LocationCheckResult.NOT_RUN,
    )
    # Akurasi yang **dinilai**. Angka mentah kiriman perangkat tetap di
    # `AttendanceLog.raw_payload`.
    gps_accuracy_meters = _meters_field()

    geofence_result = models.CharField(
        max_length=20,
        choices=GeofenceCheckResult.choices,
        default=GeofenceCheckResult.NOT_RUN,
    )
    distance_from_geofence_meters = _meters_field()
    geofence_radius_meters = _meters_field()

    # Kebijakan yang berlaku saat keputusan diambil: kewajiban tiap
    # pemeriksaan, batas akurasi, jeda minimum. Kebijakan bisa berubah
    # besok; keputusan hari ini harus tetap bisa dijelaskan.
    policy_snapshot = models.JSONField(default=dict, blank=True)

    validated_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = AttendanceLogVerificationQuerySet.as_manager()

    class Meta:
        db_table = "hr_attendance_log_verification"
        ordering = ["-id"]

    def __str__(self) -> str:
        return f"{self.log_id} {self.decision}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            # Dibandingkan per kolom database (`log_id`, bukan objek `log`).
            columns = {
                name: self._meta.get_field(name).attname
                for name in FROZEN_FIELDS
            }

            stored = (
                type(self).objects
                .filter(pk=self.pk)
                .values(*columns.values())
                .first()
            )

            if stored and stored["decision"] != PunchDecision.PENDING:
                changed = [
                    name
                    for name, column in columns.items()
                    if stored[column] != getattr(self, column)
                ]

                if changed:
                    raise ValidationError(
                        "Hasil verifikasi yang sudah diputuskan tidak "
                        f"bisa diubah: {', '.join(changed)}.",
                    )

        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        if (
            self.pk is not None
            and type(self).objects.filter(pk=self.pk)._finalized().exists()
        ):
            raise ValidationError(FINALIZED_MESSAGE)

        return super().delete(*args, **kwargs)
