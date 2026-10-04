"""
Tap kehadiran Self Service — dari bukti mentah ke presensi harian.

    request ─► identitas (pemanggil) ─► gerbang ─► work_date ─► kunci
            ─► idempotensi ─► AttendanceLog ─► AttendanceLogVerification
            ─► keputusan ─┬─ REJECTED / REVIEW_REQUIRED: bukti tersimpan,
                          │   `attendance` kosong, writer TIDAK dipanggil
                          └─ ACCEPTED: AttendanceImportWriter.upsert()
                              ─► efek izin ─► log.attendance

Berkas ini **tidak** punya aturan hari kerja, jadwal, keterlambatan,
atau izin sendiri. Hari kerja dari `workdate.resolve()` (resolver yang
sama dengan importer, aman untuk shift malam), baris harian dari
`AttendanceImportWriter.upsert()`, menit telat dari
`AttendancePolicyResolver`, efek izin dari
`AttendancePermissionEffectService`, kunci payroll dari
`AttendancePermissionService.assert_period_open()`.

Yang ditambahkan di sini hanya hal yang memang belum ada di jalur tap
lain: tap bertipe (IN/OUT) dengan mesin status, idempotensi per
`client_punch_id`, kunci per pegawai, jeda minimum, dan keputusan
REJECTED vs REVIEW_REQUIRED.

Urutan keputusan (deterministik, yang pertama menang)
-----------------------------------------------------
1. mesin status IN/OUT                       → REJECTED
2. jeda minimum sejak tap DITERIMA terakhir  → REJECTED `punch_too_soon`
   (yang tersisa untuknya: IN lalu OUT dalam hitungan detik)
3. byte selfie identik dengan selfie tap
   pegawai yang sama sebelumnya (SHA-256)    → REJECTED `selfie_replayed`
4. pemeriksaan wajib (lokasi, geofence,
   [belum terdaftar → `not_enrolled`],
   liveness, wajah)                          → REJECTED
5. keadaan hari: payroll terkunci, sudah
   ditutup mangkir, cuti                     → REVIEW_REQUIRED
6. selain itu                                → ACCEPTED

REVIEW_REQUIRED hanya untuk tap yang pemeriksaannya **lolos** — yang
ditinjau HR nanti tap orang yang terbukti hadir, bukan tap yang gagal
wajah. Detail: `docs/claude/hr/attendance-self-punch.md`.
"""

from __future__ import annotations

import dataclasses
import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework import status as http_status
from rest_framework.exceptions import APIException, ValidationError

from apps.hr.api.attendance import punch_checks as checks
from apps.hr.api.attendance.permission_effect import (
    AttendancePermissionEffectService,
)
from apps.hr.api.attendance.biometric_enrollment import BiometricEnrollmentService
from apps.hr.applicability import HRFeature, is_applicable
from apps.hr.imports.attendance import workdate
from apps.hr.imports.attendance.config import (
    DEFAULT_GRACE_AFTER_MINUTES,
    DEFAULT_GRACE_BEFORE_MINUTES,
)
from apps.hr.imports.services.attendance import AttendanceImportWriter
from apps.hr.models import (
    AttendanceLog,
    AttendanceLogType,
    AttendanceLogVerification,
    AttendanceSource,
    AttendanceStatus,
    Employee,
    EmployeeAttendance,
)
from apps.hr.models.attendance.verification import (
    BiometricCheckResult,
    GeofenceCheckResult,
    LocationCheckResult,
    PunchDecision,
    PunchReason,
)


logger = logging.getLogger(__name__)


# `AttendanceLog.external_id` untuk tap Self Service. Unique
# `(source, external_id)` di tabel itu yang menjadikan pengiriman ulang
# idempoten di tingkat database.
EXTERNAL_PREFIX = "self-punch:"

PUNCH_TYPES = (AttendanceLogType.IN, AttendanceLogType.OUT)

# Pemeriksaan yang boleh belum terpasang di tenant uji coba GPS. Lokasi
# dan geofence tidak termasuk: uji cobanya justru untuk keduanya.
TRIAL_MAY_BE_UNCONFIGURED = frozenset({checks.FACE, checks.LIVENESS})


# ----------------------------------------------------------------------
# Galat: tap tidak bisa diterima sama sekali (tidak ada yang ditulis)
# ----------------------------------------------------------------------


class AttendancePunchUnavailable(APIException):
    """Induk UNAVAILABLE. Tidak ada bukti yang ditulis."""

    status_code = http_status.HTTP_403_FORBIDDEN
    default_detail = "Tap kehadiran tidak tersedia untuk akun Anda."
    default_code = "attendance_punch_unavailable"


class AttendancePunchDisabled(AttendancePunchUnavailable):
    default_detail = "Tap kehadiran dari Self Service belum diaktifkan."
    default_code = "attendance_punch_disabled"


class AttendancePunchNotConfigured(AttendancePunchUnavailable):
    default_detail = (
        "Tap kehadiran belum bisa dipakai: pemeriksaan keamanan yang "
        "diwajibkan belum terpasang."
    )
    default_code = "attendance_punch_not_configured"


class AttendanceNotApplicable(AttendancePunchUnavailable):
    default_detail = "Presensi tidak berlaku untuk kelompok pegawai Anda."
    default_code = "attendance_not_applicable"


class AttendanceNoOrganization(AttendancePunchUnavailable):
    default_detail = (
        "Penempatan organisasi Anda belum tercatat. Hubungi HR."
    )
    default_code = "attendance_no_organization"


class AttendancePunchIdConflict(APIException):
    """
    `client_punch_id` sudah dipakai untuk tap lain. Sengaja tidak
    menyebut milik siapa atau apa isinya.
    """

    status_code = http_status.HTTP_409_CONFLICT
    default_detail = (
        "client_punch_id ini sudah dipakai untuk tap yang berbeda. "
        "Buat id baru untuk tap baru."
    )
    default_code = "attendance_punch_id_conflict"


# ----------------------------------------------------------------------
# Masukan & keluaran
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class PunchRequest:
    """
    Isi permintaan yang **sudah** lolos validasi bentuk. Tidak ada
    pegawai, tanggal kerja, jam server, atau hasil pemeriksaan di sini —
    semua itu milik server.
    """

    client_punch_id: uuid.UUID
    punch_type: str
    client_timestamp: datetime | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    accuracy_meters: Decimal | None = None
    photo: Any = None

    @property
    def external_id(self) -> str:
        return f"{EXTERNAL_PREFIX}{self.client_punch_id}"


@dataclass(frozen=True)
class PunchResult:
    log: AttendanceLog
    verification: AttendanceLogVerification
    attendance: EmployeeAttendance | None
    replayed: bool = False
    # Tap uji coba GPS (ATT-GPS-1): tidak pernah menjadi kehadiran.
    trial: bool = False

    @property
    def decision(self) -> str:
        return self.verification.decision


# ----------------------------------------------------------------------
# Pemetaan hasil pemeriksaan → kolom verifikasi & sebab
# ----------------------------------------------------------------------


RESULT_CHOICES = {
    checks.LOCATION: LocationCheckResult,
    checks.GEOFENCE: GeofenceCheckResult,
    checks.LIVENESS: BiometricCheckResult,
    checks.FACE: BiometricCheckResult,
}

# Sebab REJECTED per hasil yang tidak lolos. Hasil lain yang tidak
# disebut (NOT_CONFIGURED, NOT_RUN) jatuh ke `*_NOT_VERIFIED`.
FAILURE_REASON = {
    checks.LOCATION: {
        LocationCheckResult.UNAVAILABLE: PunchReason.LOCATION_UNAVAILABLE,
        LocationCheckResult.LOW_ACCURACY: PunchReason.LOCATION_LOW_ACCURACY,
        LocationCheckResult.ERROR: PunchReason.VALIDATOR_ERROR,
    },
    checks.GEOFENCE: {
        GeofenceCheckResult.OUTSIDE: PunchReason.OUTSIDE_GEOFENCE,
        GeofenceCheckResult.ERROR: PunchReason.VALIDATOR_ERROR,
        GeofenceCheckResult.NO_GEOFENCE: PunchReason.GEOFENCE_NOT_CONFIGURED,
        GeofenceCheckResult.NO_WORK_LOCATION: PunchReason.WORK_LOCATION_UNAVAILABLE,
    },
    checks.LIVENESS: {
        BiometricCheckResult.FAIL: PunchReason.LIVENESS_FAILED,
        BiometricCheckResult.ERROR: PunchReason.VALIDATOR_ERROR,
        BiometricCheckResult.NO_FACE: PunchReason.NO_FACE,
        BiometricCheckResult.MULTIPLE_FACES: PunchReason.MULTIPLE_FACES,
    },
    checks.FACE: {
        BiometricCheckResult.FAIL: PunchReason.FACE_MISMATCH,
        BiometricCheckResult.ERROR: PunchReason.VALIDATOR_ERROR,
        BiometricCheckResult.NO_FACE: PunchReason.NO_FACE,
        BiometricCheckResult.MULTIPLE_FACES: PunchReason.MULTIPLE_FACES,
        BiometricCheckResult.NOT_ENROLLED: PunchReason.NOT_ENROLLED,
    },
}

NOT_VERIFIED_REASON = {
    checks.LOCATION: PunchReason.LOCATION_NOT_VERIFIED,
    checks.GEOFENCE: PunchReason.GEOFENCE_NOT_VERIFIED,
    checks.LIVENESS: PunchReason.LIVENESS_NOT_VERIFIED,
    checks.FACE: PunchReason.FACE_NOT_VERIFIED,
}


def _apply_outcome(verification, key: str, outcome: checks.CheckOutcome) -> None:
    result = str(outcome.result)

    if key == checks.LOCATION:
        verification.location_result = result
        verification.gps_accuracy_meters = outcome.accuracy_meters
    elif key == checks.GEOFENCE:
        verification.geofence_result = result
        verification.distance_from_geofence_meters = outcome.distance_meters
        verification.geofence_radius_meters = outcome.radius_meters
    else:
        setattr(verification, f"{key}_result", result)
        setattr(verification, f"{key}_score", outcome.score)
        setattr(verification, f"{key}_threshold", outcome.threshold)
        setattr(verification, f"{key}_provider", outcome.provider[:100])
        setattr(verification, f"{key}_model_version", outcome.model_version[:100])


def _plain(result: str) -> checks.CheckOutcome:
    return checks.CheckOutcome(result=result)


# ----------------------------------------------------------------------
# Service
# ----------------------------------------------------------------------


class AttendancePunchService:
    @staticmethod
    def is_enabled() -> bool:
        return bool(getattr(settings, "ATTENDANCE_SELF_PUNCH_ENABLED", False))

    # ------------------------------------------------------------------
    # Titik masuk
    # ------------------------------------------------------------------

    @classmethod
    def record(
        cls,
        *,
        employee: Employee,
        user,
        request: PunchRequest,
        now: datetime | None = None,
    ) -> PunchResult:
        """
        `employee` **wajib** dari konteks login (`CurrentEmployeeService`)
        — service ini tidak pernah mencarinya dari isi permintaan.
        """
        if request.punch_type not in PUNCH_TYPES:
            raise ValidationError({"punch_type": ["Harus 'in' atau 'out'."]})

        # Uji coba GPS hanya untuk schema tenant yang didaftarkan eksplisit
        # (`ATTENDANCE_SELF_PUNCH_TRIAL_SCHEMAS`). Di luar itu perilakunya
        # persis seperti sebelum ATT-GPS-1.
        trial = checks.trial_active()

        if not trial and not cls.is_enabled():
            raise AttendancePunchDisabled()

        if not is_applicable(employee, HRFeature.ATTENDANCE):
            raise AttendanceNotApplicable()

        assignment = AttendanceImportWriter.get_assignment(employee)

        if assignment is None or assignment.company_id is None:
            raise AttendanceNoOrganization()

        moment = now or timezone.now()

        # Hari kerja kanonik — tidak pernah `moment.date()`.
        resolution = workdate.resolve(
            employee=employee,
            moment=moment,
            grace_before_minutes=DEFAULT_GRACE_BEFORE_MINUTES,
            grace_after_minutes=DEFAULT_GRACE_AFTER_MINUTES,
        )

        policy = checks.resolve_policy(employee, resolution.work_date)

        # Gagal tertutup: pemeriksaan yang diwajibkan tanpa mesin berarti
        # tidak ada tap yang bisa diterima, jadi tidak ada yang ditulis.
        #
        # Uji coba: hanya wajah/liveness yang boleh belum terpasang — dan
        # tetap wajib, jadi tap-nya tetap tidak pernah ACCEPTED.
        missing = set(policy.unconfigured_required())

        if missing and not (trial and missing <= TRIAL_MAY_BE_UNCONFIGURED):
            raise AttendancePunchNotConfigured()

        with transaction.atomic():
            # Satu pegawai, satu tap pada satu waktu. Baris Employee
            # selalu ada dan stabil; baris presensi harian mungkin belum
            # ada, jadi tidak bisa jadi satu-satunya sasaran kunci.
            Employee.objects.select_for_update().only("pk").get(pk=employee.pk)

            existing = cls._existing(request)

            if existing is not None:
                return cls._replay(existing, employee=employee, request=request)

            cls._assert_photo(request.photo, user=user)

            log = cls._create_log(
                employee=employee,
                assignment=assignment,
                request=request,
                moment=moment,
            )

            verification = AttendanceLogVerification.objects.create(
                log=log,
                work_date=resolution.work_date,
                policy_snapshot={**policy.snapshot(), "trial": trial},
            )

            row = (
                EmployeeAttendance.objects
                .select_for_update()
                .filter(
                    employee=employee,
                    work_date=resolution.work_date,
                    is_deleted=False,
                )
                .first()
            )

            decision, reason, detail = cls._decide(
                employee=employee,
                log=log,
                verification=verification,
                request=request,
                moment=moment,
                work_date=resolution.work_date,
                policy=policy,
                row=row,
            )

            # Tap uji coba **tidak pernah** menjadi kehadiran, sekalipun
            # (kelak) semua pemeriksaannya lolos.
            if trial and decision != PunchDecision.REJECTED:
                decision = PunchDecision.REJECTED
                reason = PunchReason.TRIAL_NOT_RECORDED
                detail = "Mode uji coba GPS: kehadiran tidak dicatat."

            attendance = None

            if decision == PunchDecision.ACCEPTED and not trial:
                attendance = cls._apply(
                    employee=employee,
                    user=user,
                    request=request,
                    moment=moment,
                    resolution=resolution,
                    verification=verification,
                )

            log.attendance = attendance
            log.is_processed = True
            log.processed_at = moment
            log.processing_error = "" if attendance else reason
            log.save(
                update_fields=[
                    "attendance",
                    "is_processed",
                    "processed_at",
                    "processing_error",
                ],
            )

            verification.decision = decision
            verification.reason_code = reason
            verification.reason_detail = detail
            verification.validated_at = moment
            verification.save()

        return PunchResult(
            log=log,
            verification=verification,
            attendance=attendance,
            trial=trial,
        )

    # ------------------------------------------------------------------
    # Idempotensi
    # ------------------------------------------------------------------

    @staticmethod
    def _existing(request: PunchRequest) -> AttendanceLog | None:
        return (
            AttendanceLog.objects
            .select_related("verification", "attendance")
            .filter(
                source=AttendanceSource.MOBILE,
                external_id=request.external_id,
            )
            .first()
        )

    @staticmethod
    def _replay(log, *, employee, request: PunchRequest) -> PunchResult:
        """
        Pengiriman ulang `client_punch_id` yang sama: kembalikan hasil
        yang tersimpan, tanpa menulis apa pun.

        Id yang sama untuk pegawai lain, jenis tap lain, atau selfie lain
        bukan pengiriman ulang — itu 409, tanpa menyebut isinya.
        """
        photo_id = getattr(request.photo, "pk", None)

        if (
            log.employee_id != employee.pk
            or log.log_type != request.punch_type
            or log.photo_id != photo_id
        ):
            raise AttendancePunchIdConflict()

        verification = getattr(log, "verification", None)

        if verification is None:
            # Log Self Service tanpa verifikasi tidak lahir dari jalur
            # ini. Jangan ditebak isinya.
            raise AttendancePunchIdConflict()

        return PunchResult(
            log=log,
            verification=verification,
            attendance=log.attendance,
            replayed=True,
            trial=bool((verification.policy_snapshot or {}).get("trial")),
        )

    # ------------------------------------------------------------------
    # Bukti
    # ------------------------------------------------------------------

    @staticmethod
    def _assert_photo(photo, *, user) -> None:
        """
        Selfie lewat aturan lampiran yang sama dengan seluruh sistem
        (`FileAccessService.attachment_problem`): milik pengunggahnya,
        belum dipakai record lain, belum dihapus. Ditambah: memang
        diunggah sebagai selfie presensi, dan memang gambar.
        """
        if photo is None:
            return

        from apps.uploads.models import UploadedFile
        from apps.uploads.services.access_service import FileAccessService

        problem = FileAccessService.attachment_problem(
            uploaded_file=photo,
            user=user,
        )

        if problem is None and photo.category != UploadedFile.Category.ATTENDANCE_SELFIE:
            problem = "Selfie harus diunggah dengan kategori attendance_selfie."

        if problem is None and photo.file_type != UploadedFile.FileType.IMAGE:
            problem = "Selfie harus berupa gambar."

        if problem is not None:
            raise ValidationError({"selfie": [problem]})

    @staticmethod
    def _create_log(*, employee, assignment, request: PunchRequest, moment) -> AttendanceLog:
        raw_payload = {
            "client_punch_id": str(request.client_punch_id),
            "punch_type": request.punch_type,
            "client_timestamp": (
                request.client_timestamp.isoformat()
                if request.client_timestamp
                else None
            ),
            "latitude": None if request.latitude is None else str(request.latitude),
            "longitude": None if request.longitude is None else str(request.longitude),
            "location_accuracy": (
                None
                if request.accuracy_meters is None
                else str(request.accuracy_meters)
            ),
            "selfie_id": getattr(request.photo, "pk", None),
        }

        try:
            with transaction.atomic():
                return AttendanceLog.objects.create(
                    employee=employee,
                    company=assignment.company,
                    branch=assignment.branch,
                    location=assignment.location,
                    occurred_at=moment,
                    log_type=request.punch_type,
                    source=AttendanceSource.MOBILE,
                    employee_identifier=(employee.employee_number or "")[:150],
                    external_id=request.external_id,
                    latitude=request.latitude,
                    longitude=request.longitude,
                    photo=request.photo,
                    raw_payload=raw_payload,
                    is_processed=False,
                )
        except IntegrityError:
            # Pegawai lain baru saja memakai id yang sama (kunci per
            # pegawai tidak menahan dua pegawai berbeda). Unique
            # `(source, external_id)` yang menangkapnya.
            raise AttendancePunchIdConflict()

    # ------------------------------------------------------------------
    # Keputusan
    # ------------------------------------------------------------------

    @classmethod
    def _decide(
        cls,
        *,
        employee,
        log,
        verification,
        request: PunchRequest,
        moment,
        work_date,
        policy: checks.PunchPolicy,
        row,
    ) -> tuple[str, str, str]:
        reason = cls._state_violation(request.punch_type, row)

        if reason is None:
            reason = cls._too_soon(employee=employee, log=log, moment=moment, policy=policy)

        if reason is None:
            reason = cls._replayed_selfie(employee=employee, log=log, photo=request.photo)

        if reason is not None:
            cls._skip_checks(verification, policy)
            return PunchDecision.REJECTED, reason, ""

        # Subjek wajah milik pegawai yang login saja — dicari di sini,
        # bukan oleh mesin, supaya mesin tidak pernah bisa membandingkan
        # dengan pendaftaran pegawai lain.
        subject = None

        if policy.is_required(checks.FACE):
            subject = BiometricEnrollmentService.subject_for(
                employee,
                checks.get_check(checks.FACE).provider,
            )

        reason, detail = cls._run_checks(
            verification=verification,
            evidence=checks.PunchEvidence(
                employee=employee,
                log=log,
                punch_type=request.punch_type,
                occurred_at=moment,
                work_date=work_date,
                latitude=request.latitude,
                longitude=request.longitude,
                accuracy_meters=request.accuracy_meters,
                photo=request.photo,
                policy=policy,
                subject=subject,
            ),
            policy=policy,
        )

        if reason is not None:
            return PunchDecision.REJECTED, reason, detail

        reason, detail = cls._business_conflict(
            employee=employee,
            work_date=work_date,
            row=row,
        )

        if reason is not None:
            return PunchDecision.REVIEW_REQUIRED, reason, detail

        return PunchDecision.ACCEPTED, "", ""

    @staticmethod
    def _too_soon(*, employee, log, moment, policy) -> str | None:
        """
        Penahan tap ganda tak sengaja (IN lalu OUT dalam hitungan detik).

        Dihitung dari tap **DITERIMA** terakhir saja: tap yang ditolak
        karena GPS buruk harus bisa langsung dicoba lagi.
        """
        seconds = int(policy.min_interval_seconds or 0)

        if seconds <= 0:
            return None

        recent = (
            AttendanceLog.objects
            .filter(
                employee=employee,
                source=AttendanceSource.MOBILE,
                verification__decision=PunchDecision.ACCEPTED,
                occurred_at__gt=moment - timedelta(seconds=seconds),
            )
            .exclude(pk=log.pk)
            .exists()
        )

        return PunchReason.PUNCH_TOO_SOON if recent else None

    @staticmethod
    def _replayed_selfie(*, employee, log, photo) -> str | None:
        """
        Byte selfie yang **persis sama** (SHA-256 `UploadedFile`) dengan
        selfie tap Self Service pegawai yang sama sebelumnya — apa pun
        keputusan tap itu, termasuk yang ditolak.

        Hanya bukti identik. Bukan liveness, bukan pengenalan wajah: dua
        foto berbeda dari orang yang sama tidak pernah dianggap ulangan.

        Cakupannya pegawai ini saja (dan tenant ini, karena schema). Selfie
        orang lain yang dipakai di akun sendiri tidak cocok dengan
        pendaftaran wajah akun itu; membandingkan lintas pegawai cuma
        membocorkan bahwa orang lain pernah mengunggah gambar yang sama.

        Kiriman ulang yang sah (`client_punch_id` sama) sudah dijawab
        `_replay()` sebelum sampai sini, dan log tap ini sendiri
        dikecualikan.
        """
        checksum = str(getattr(photo, "checksum_sha256", "") or "")

        if not checksum:
            return None

        used = (
            AttendanceLog.objects
            .filter(
                employee=employee,
                source=AttendanceSource.MOBILE,
                photo__checksum_sha256=checksum,
            )
            .exclude(pk=log.pk)
            .exists()
        )

        return PunchReason.SELFIE_REPLAYED if used else None

    @staticmethod
    def _state_violation(punch_type: str, row) -> str | None:
        """
        IN/OUT terhadap baris harian kanonik, apa pun sumber jam masuknya
        (mesin, import, koreksi HR, tap Self Service).
        """
        has_in = row is not None and row.check_in is not None
        has_out = row is not None and row.check_out is not None

        if punch_type == AttendanceLogType.IN:
            return PunchReason.DUPLICATE_CHECK_IN if has_in else None

        if not has_in:
            return PunchReason.CHECK_OUT_WITHOUT_CHECK_IN

        if has_out:
            return PunchReason.DUPLICATE_CHECK_OUT

        return None

    @staticmethod
    def _skip_checks(verification, policy) -> None:
        for key in checks.CHECK_ORDER:
            result = (
                "not_run"
                if policy.is_required(key)
                else "not_required"
            )

            _apply_outcome(verification, key, _plain(result))

    @staticmethod
    def _run_checks(*, verification, evidence, policy) -> tuple[str | None, str]:
        failure: tuple[str | None, str] = (None, "")
        applied: set[str] = set()

        for key in checks.CHECK_ORDER:
            if key in applied:
                continue

            if not policy.is_required(key):
                _apply_outcome(verification, key, _plain("not_required"))
                continue

            if failure[0] is not None:
                # Mesin yang memang belum terpasang dicatat apa adanya,
                # bukan "tidak dijalankan".
                _apply_outcome(
                    verification,
                    key,
                    _plain(
                        "not_run"
                        if policy.is_configured(key)
                        else "not_configured"
                    ),
                )
                continue

            # Belum terdaftar: diputuskan sebelum pemeriksaan biometrik
            # pertama, jadi selfie orang yang tidak terdaftar tidak pernah
            # dikirim ke mesin liveness/wajah mana pun.
            if (
                key in checks.NEEDS_PHOTO
                and evidence.photo is not None
                and policy.is_required(checks.FACE)
                and policy.is_configured(checks.FACE)
                and evidence.subject is None
            ):
                _apply_outcome(
                    verification,
                    checks.FACE,
                    checks.CheckOutcome(
                        result=BiometricCheckResult.NOT_ENROLLED,
                        provider=checks.get_check(checks.FACE).provider,
                    ),
                )
                applied.add(checks.FACE)

                if key != checks.FACE:
                    _apply_outcome(verification, key, _plain("not_run"))

                failure = (PunchReason.NOT_ENROLLED, "")
                continue

            outcome = AttendancePunchService._run_one(key, evidence)

            _apply_outcome(verification, key, outcome)

            if str(outcome.result) != checks.PASSING[key]:
                reason = FAILURE_REASON[key].get(
                    str(outcome.result),
                    NOT_VERIFIED_REASON[key],
                )
                failure = (reason, outcome.detail)

        return failure

    @staticmethod
    def _run_one(key: str, evidence) -> checks.CheckOutcome:
        if key in checks.NEEDS_PHOTO and evidence.photo is None:
            return checks.CheckOutcome(
                result="not_run",
                detail="Selfie tidak dikirim.",
            )

        check = checks.get_check(key)

        if not check.configured:
            return checks.CheckOutcome(
                result="not_configured",
                detail="Mesin pemeriksaan belum terpasang.",
            )

        try:
            outcome = check.run(evidence)
        except Exception:
            logger.exception("Attendance punch check %s failed", key)

            return checks.CheckOutcome(
                result="error",
                detail="Pemeriksaan gagal dijalankan.",
            )

        # Mesin yang menjawab di luar kosakatanya tidak dipercaya —
        # "pass" untuk geofence bukan INSIDE.
        if str(outcome.result) not in RESULT_CHOICES[key].values:
            logger.error(
                "Attendance punch check %s returned unknown result %r",
                key,
                outcome.result,
            )

            return checks.CheckOutcome(
                result="error",
                detail="Hasil pemeriksaan tidak dikenal.",
            )

        if key in checks.NEEDS_PHOTO and not outcome.provider and check.provider:
            outcome = dataclasses.replace(outcome, provider=check.provider)

        if key == checks.FACE:
            outcome = AttendancePunchService._apply_face_policy(
                outcome,
                evidence.policy,
            )

        return outcome

    @staticmethod
    def _apply_face_policy(outcome, policy) -> checks.CheckOutcome:
        """
        Keputusan cocok/tidak cocok milik **kebijakan ERP**, bukan mesin.

        Mesin melaporkan skor; PASS hanya kalau ambang terkalibrasi ada
        untuk penyedia ini, versi modelnya sama dengan yang dikalibrasi,
        skornya ada, dan skornya lolos pembanding. PASS dari mesin dengan
        skor yang tidak lolos = FAIL. FAIL dari mesin tidak pernah
        dinaikkan jadi PASS. Ambang yang dipakai selalu dicatat.
        """
        face_match = policy.face_match

        if face_match is None or face_match.provider != outcome.provider:
            if str(outcome.result) != BiometricCheckResult.PASS:
                return outcome

            return dataclasses.replace(
                outcome,
                result=BiometricCheckResult.NOT_CONFIGURED,
                detail="Ambang kecocokan wajah belum dikalibrasi.",
            )

        outcome = dataclasses.replace(outcome, threshold=face_match.threshold)

        if str(outcome.result) != BiometricCheckResult.PASS:
            return outcome

        if outcome.model_version != face_match.model_version:
            return dataclasses.replace(
                outcome,
                result=BiometricCheckResult.ERROR,
                detail="Versi model wajah berbeda dari yang dikalibrasi.",
            )

        if outcome.score is None:
            return dataclasses.replace(
                outcome,
                result=BiometricCheckResult.ERROR,
                detail="Mesin wajah tidak melaporkan skor.",
            )

        if not face_match.accepts(outcome.score):
            return dataclasses.replace(
                outcome,
                result=BiometricCheckResult.FAIL,
                detail="Skor di bawah ambang kecocokan.",
            )

        return outcome

    @staticmethod
    def _business_conflict(*, employee, work_date, row) -> tuple[str | None, str]:
        """
        Keadaan hari itu yang melarang penerapan otomatis. Tap-nya sah,
        jadi REVIEW_REQUIRED, bukan REJECTED.

        Yang **tidak** jadi konflik, karena jalur tap lain pun tidak
        menjadikannya konflik:

        * izin (PERMIT / dokumen Attendance Permission) — efeknya
          diterapkan sesudah upsert;
        * BUSINESS_TRIP — tap fisik di hari dinas tetap hari hadir;
        * hari tidak terjadwal / DAY_OFF / HOLIDAY — Off Worked.
        """
        from apps.hr.api.attendance.closing import AttendanceClosingService
        from apps.hr.api.attendance_permission.services import (
            AttendancePermissionService,
        )

        try:
            AttendancePermissionService.assert_period_open(
                employee=employee,
                work_date=work_date,
            )
        except DjangoValidationError as exc:
            return PunchReason.PAYROLL_PERIOD_LOCKED, "; ".join(exc.messages)

        status = getattr(row, "status", None)

        # `full_clean()` menolak ABSENT ber-jam masuk; mengubahnya jadi
        # hadir diam-diam menghapus keputusan penutup hari.
        if status == AttendanceStatus.ABSENT:
            return PunchReason.DAY_CLOSED_ABSENT, ""

        if status in (AttendanceStatus.LEAVE, AttendanceStatus.SICK):
            return PunchReason.ON_LEAVE, ""

        # Cuti yang sudah disetujui untuk hari yang barisnya belum
        # terbit (hari berjalan; penutup hari belum lewat).
        leave_days = AttendanceClosingService._leave_days(
            [employee],
            work_date,
            work_date,
        )

        if work_date in leave_days.get(employee.pk, set()):
            return PunchReason.ON_LEAVE, ""

        return None, ""

    # ------------------------------------------------------------------
    # Penerapan
    # ------------------------------------------------------------------

    @staticmethod
    def _apply(*, employee, user, request: PunchRequest, moment, resolution, verification):
        scheduled = None

        if resolution.has_schedule:
            scheduled = (
                resolution.scheduled_check_in,
                resolution.scheduled_check_out,
            )

        attendance, _created = AttendanceImportWriter.upsert(
            employee=employee,
            normalized={"log_time": moment},
            user=user,
            work_date=resolution.work_date,
            scheduled=scheduled,
            source=AttendanceSource.MOBILE,
            log_type=request.punch_type,
        )

        side = "in" if request.punch_type == AttendanceLogType.IN else "out"

        setattr(attendance, f"check_{side}_latitude", request.latitude)
        setattr(attendance, f"check_{side}_longitude", request.longitude)

        fields = [f"check_{side}_latitude", f"check_{side}_longitude"]

        if verification.geofence_result == GeofenceCheckResult.INSIDE:
            attendance.is_geofence_valid = True
            fields.append("is_geofence_valid")

        attendance.save(update_fields=fields + ["updated_at"])

        # Writer tidak menerapkan izin; jalur manual menerapkannya.
        # Tanpa ini izin yang disetujui **sebelum** baris lahir tidak
        # pernah memaafkan telatnya.
        AttendancePermissionEffectService.recalculate(
            employee=employee,
            work_date=resolution.work_date,
        )

        attendance.refresh_from_db()

        return attendance
