"""
Siklus hidup pendaftaran biometrik wajah (ATT-BIO-2A).

Satu-satunya jalur tulis `EmployeeBiometricEnrollment`. Belum ada API,
layar, atau perintah yang memanggilnya: pendaftaran sungguhan butuh
penyedia (ATT-BIO-2B), dan adapter penyedia itulah yang nanti
mendaftarkan wajah ke penyedia **di dalam** `enroll()` sebelum baris
ACTIVE dianggap sah. Otorisasi pemanggil (siapa boleh mendaftarkan
siapa) juga milik API BIO-2B — service ini tidak menebaknya.

Aturan yang ditegakkan di sini dan di database:

* satu ACTIVE per (pegawai, penyedia);
* daftar ulang = cabut + baris baru, `version` naik, `subject_id` baru —
  identitas yang sudah dicabut tidak pernah hidup lagi;
* pencabutan mencatat kapan, oleh siapa, dan kenapa;
* `subject_id` selalu `uuid4()` — tidak pernah diturunkan dari data
  pegawai, dan tidak bisa dioper pemanggil.
"""

from __future__ import annotations

import uuid

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone

from apps.hr.api.attendance.punch_checks import BiometricSubject
from apps.hr.models import (
    BiometricEnrollmentSource,
    BiometricEnrollmentStatus,
    Employee,
    EmployeeBiometricEnrollment,
)


class BiometricEnrollmentService:
    @staticmethod
    def subject_for(employee, provider: str) -> BiometricSubject | None:
        """
        Subjek ACTIVE milik **pegawai ini** untuk satu penyedia. Tidak ada
        jalur yang mencari pendaftaran dari isi permintaan atau milik
        pegawai lain.
        """
        provider = (provider or "").strip()

        if employee is None or not provider:
            return None

        enrollment = (
            EmployeeBiometricEnrollment.objects
            .active()
            .filter(employee=employee, provider=provider)
            .only("provider", "subject_id", "version")
            .first()
        )

        if enrollment is None:
            return None

        return BiometricSubject(
            provider=enrollment.provider,
            subject_id=str(enrollment.subject_id),
            version=enrollment.version,
        )

    @classmethod
    @transaction.atomic
    def enroll(
        cls,
        *,
        employee,
        provider: str,
        user,
        source: str = BiometricEnrollmentSource.HR_ASSISTED,
        now=None,
    ) -> EmployeeBiometricEnrollment:
        provider = (provider or "").strip()

        if not provider:
            raise ValidationError({"provider": ["Penyedia wajib diisi."]})

        # Satu pendaftaran per pegawai pada satu waktu: nomor versi dan
        # pemeriksaan ACTIVE di bawah tidak boleh balapan.
        Employee.objects.select_for_update().only("pk").get(pk=employee.pk)

        existing = EmployeeBiometricEnrollment.objects.filter(
            employee=employee,
            provider=provider,
        )

        if existing.active().exists():
            raise ValidationError(
                "Pegawai ini sudah punya pendaftaran aktif untuk penyedia "
                "tersebut. Cabut dulu, atau daftar ulang.",
            )

        last = existing.aggregate(last=Max("version"))["last"] or 0

        enrollment = EmployeeBiometricEnrollment(
            employee=employee,
            provider=provider,
            subject_id=uuid.uuid4(),
            version=last + 1,
            status=BiometricEnrollmentStatus.ACTIVE,
            enrollment_source=source,
            enrolled_at=now or timezone.now(),
            enrolled_by=user,
        )

        enrollment.full_clean()
        enrollment.save()

        return enrollment

    @classmethod
    @transaction.atomic
    def revoke(
        cls,
        enrollment: EmployeeBiometricEnrollment,
        *,
        user,
        reason: str = "",
        now=None,
    ) -> EmployeeBiometricEnrollment:
        locked = (
            EmployeeBiometricEnrollment.objects
            .select_for_update()
            .get(pk=enrollment.pk)
        )

        if locked.status == BiometricEnrollmentStatus.REVOKED:
            raise ValidationError("Pendaftaran ini sudah dicabut.")

        locked.status = BiometricEnrollmentStatus.REVOKED
        locked.revoked_at = now or timezone.now()
        locked.revoked_by = user
        locked.revocation_reason = (reason or "").strip()[:255]

        locked.full_clean()
        locked.save(
            update_fields=[
                "status",
                "revoked_at",
                "revoked_by",
                "revocation_reason",
                "updated_at",
            ],
        )

        return locked

    @classmethod
    @transaction.atomic
    def reenroll(
        cls,
        *,
        employee,
        provider: str,
        user,
        reason: str = "",
        source: str = BiometricEnrollmentSource.HR_ASSISTED,
        now=None,
    ) -> EmployeeBiometricEnrollment:
        """Cabut yang ACTIVE (kalau ada), lalu buat versi baru."""
        provider = (provider or "").strip()

        Employee.objects.select_for_update().only("pk").get(pk=employee.pk)

        current = (
            EmployeeBiometricEnrollment.objects
            .active()
            .filter(employee=employee, provider=provider)
            .first()
        )

        if current is not None:
            cls.revoke(current, user=user, reason=reason or "Re-enrollment", now=now)

        return cls.enroll(
            employee=employee,
            provider=provider,
            user=user,
            source=source,
            now=now,
        )
