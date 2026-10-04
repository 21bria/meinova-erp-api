"""
`POST /api/me/attendance/punch/` — tap kehadiran untuk diri sendiri.

**Adapter tipis**, sama seperti pengajuan pribadi (`SelfRequestView`):
subjeknya `self.employee`, bentuk permintaannya milik serializer HR, dan
seluruh aturannya milik `AttendancePunchService` di domain HR. Yang
dikerjakan berkas ini cuma menolak kolom yang tidak diterima `/me` dan
menyusun balasan yang **cukup** untuk pegawainya sendiri.

Balasan tidak memuat skor, ambang, nama penyedia, atau koordinat yang
dinilai — itu bukti terbatas, bukan informasi untuk pegawai.
"""

from __future__ import annotations

from decimal import Decimal

from django.utils import timezone

from apps.core.responses.api import success_response
from apps.hr.api.attendance import punch_checks as checks
from apps.hr.api.attendance.punch import (
    TRIAL_MAY_BE_UNCONFIGURED,
    AttendancePunchService,
)
from apps.hr.api.attendance.punch_serializers import (
    AttendancePunchRequestSerializer,
)
from apps.hr.api.attendance.schedule import WALL_CLOCK_TZ
from apps.hr.models.attendance.verification import PunchDecision, PunchReason
from apps.self_service.api.views import SelfServiceAPIView
from apps.self_service.exceptions import FieldNotAccepted
from apps.self_service.services.requests import (
    IDENTITY_FIELDS,
    IDENTITY_MESSAGE,
    NOT_ALLOWED_MESSAGE,
)


ACCEPTED_FIELDS = frozenset(
    {
        "client_punch_id",
        "punch_type",
        "client_timestamp",
        "latitude",
        "longitude",
        "location_accuracy",
        "selfie",
    }
)

SERVER_DERIVED_MESSAGE = (
    "Nilai ini ditentukan server dan tidak diterima dari permintaan."
)

# Kolom yang terlihat seperti hasil pemeriksaan. Ditolak dengan pesan
# yang menyebut sebabnya, bukan sekadar "tidak dikenal".
SERVER_DERIVED_FIELDS = frozenset(
    {
        "work_date",
        "server_timestamp",
        "occurred_at",
        "face_pass",
        "face_result",
        "face_score",
        "liveness_pass",
        "liveness_result",
        "inside_geofence",
        "geofence_result",
        "distance",
        "decision",
        "status",
        "company",
        "location",
    }
)

MESSAGES = {
    PunchDecision.ACCEPTED: "Tap kehadiran tercatat.",
    PunchReason.PUNCH_TOO_SOON: "Tap terlalu rapat dengan tap sebelumnya.",
    PunchReason.DUPLICATE_CHECK_IN: "Anda sudah check in untuk hari kerja ini.",
    PunchReason.CHECK_OUT_WITHOUT_CHECK_IN: "Belum ada check in untuk hari kerja ini.",
    PunchReason.DUPLICATE_CHECK_OUT: "Anda sudah check out untuk hari kerja ini.",
    PunchReason.LOCATION_NOT_VERIFIED: "Lokasi tidak bisa diverifikasi.",
    PunchReason.LOCATION_UNAVAILABLE: "Lokasi perangkat tidak tersedia.",
    PunchReason.LOCATION_LOW_ACCURACY: "Akurasi lokasi terlalu rendah. Coba lagi di tempat terbuka.",
    PunchReason.GEOFENCE_NOT_VERIFIED: "Area kerja tidak bisa diverifikasi.",
    PunchReason.OUTSIDE_GEOFENCE: "Anda berada di luar area kerja.",
    PunchReason.LIVENESS_NOT_VERIFIED: "Verifikasi selfie tidak bisa dilakukan.",
    PunchReason.LIVENESS_FAILED: "Verifikasi selfie tidak berhasil.",
    PunchReason.FACE_NOT_VERIFIED: "Verifikasi selfie tidak bisa dilakukan.",
    PunchReason.FACE_MISMATCH: "Verifikasi selfie tidak berhasil.",
    PunchReason.VALIDATOR_ERROR: "Verifikasi gagal dijalankan. Coba lagi.",
    PunchReason.NO_FACE: "Wajah tidak terlihat pada selfie. Ambil foto ulang.",
    PunchReason.MULTIPLE_FACES: "Selfie hanya boleh memuat wajah Anda sendiri. Ambil foto ulang.",
    PunchReason.NOT_ENROLLED: "Data wajah Anda belum terdaftar. Hubungi HR.",
    PunchReason.SELFIE_REPLAYED: "Selfie ini sudah pernah dipakai. Ambil foto baru.",
    PunchReason.GEOFENCE_NOT_CONFIGURED: "Area kerja untuk lokasi Anda belum diatur. Hubungi HR.",
    PunchReason.WORK_LOCATION_UNAVAILABLE: "Lokasi kerja Anda belum tercatat. Hubungi HR.",
    PunchReason.TRIAL_NOT_RECORDED: "Uji coba GPS: kehadiran tidak dicatat.",
    PunchReason.PAYROLL_PERIOD_LOCKED: "Periode payroll hari ini sudah dikunci; tap dicatat untuk ditinjau HR.",
    PunchReason.DAY_CLOSED_ABSENT: "Hari ini sudah ditutup sebagai tidak hadir; tap dicatat untuk ditinjau HR.",
    PunchReason.ON_LEAVE: "Anda tercatat cuti pada hari ini; tap dicatat untuk ditinjau HR.",
}


def _wall_clock(value):
    if value is None:
        return None

    return value.astimezone(WALL_CLOCK_TZ).isoformat()


TRIAL_MESSAGE = (
    "Uji coba GPS selesai. Verifikasi wajah tidak aktif pada uji coba "
    "ini; kehadiran tidak dicatat."
)


def _decimal(value):
    """Meter dengan dua desimal, sama seperti yang tersimpan di bukti."""
    if value is None:
        return None

    return str(Decimal(value).quantize(Decimal("0.01")))


def build_trial(result) -> dict:
    """
    Hasil uji coba GPS untuk pegawai yang tap sendiri (ATT-GPS-1). Tidak
    ada skor wajah, penyedia, subjek pendaftaran, atau koordinat pusat
    geofence — hanya yang perlu dilihat orang yang sedang mencoba.
    """
    verification = result.verification

    return {
        "mode": "gps_trial",
        "location_result": verification.location_result,
        "accuracy_m": _decimal(verification.gps_accuracy_meters),
        "geofence_result": verification.geofence_result,
        "distance_m": _decimal(verification.distance_from_geofence_meters),
        "radius_m": _decimal(verification.geofence_radius_meters),
        "selfie_stored": result.log.photo_id is not None,
        "biometric_verification": "unavailable",
        "attendance_recorded": False,
    }


def build_payload(result) -> dict:
    verification = result.verification
    attendance = result.attendance
    decision = verification.decision
    reason = verification.reason_code or ""

    payload = {
        "result": decision,
        "punch_type": result.log.log_type,
        "recorded_at": _wall_clock(result.log.occurred_at),
        "work_date": (
            verification.work_date.isoformat()
            if verification.work_date
            else None
        ),
        "reason_code": reason or None,
        "message": MESSAGES.get(reason or decision, ""),
        "replayed": result.replayed,
        "attendance": None,
    }

    if result.trial:
        payload["trial"] = build_trial(result)
        payload["message"] = TRIAL_MESSAGE

    if attendance is not None:
        payload["attendance"] = {
            "work_date": attendance.work_date.isoformat(),
            "status": attendance.status,
            "check_in": _wall_clock(attendance.check_in),
            "check_out": _wall_clock(attendance.check_out),
        }

    return payload


def availability(employee) -> dict:
    """
    Bisakah pegawai ini tap dari Self Service sekarang? Hanya ya/tidak dan
    apakah ini uji coba — bukan daftar mesin yang belum terpasang.
    """
    trial = checks.trial_active()

    if not trial and not AttendancePunchService.is_enabled():
        return {"available": False, "trial": False}

    policy = checks.resolve_policy(employee, timezone.localdate())
    missing = set(policy.unconfigured_required())

    available = not missing or (trial and missing <= TRIAL_MAY_BE_UNCONFIGURED)

    if not available:
        return {"available": False, "trial": False}

    # Batas akurasi yang dipakai server, supaya layar bisa memperingatkan
    # sebelum mengirim. Server tetap yang memutuskan.
    return {
        "available": True,
        "trial": bool(trial),
        "max_gps_accuracy_m": int(policy.max_gps_accuracy_meters),
    }


class SelfAttendancePunchView(SelfServiceAPIView):
    http_method_names = ["get", "post", "options"]

    def get(self, request):
        return success_response(data=availability(self.employee))

    @staticmethod
    def clean_keys(payload) -> None:
        errors = {}

        for key in payload.keys():
            if key in IDENTITY_FIELDS:
                errors[key] = [IDENTITY_MESSAGE]
            elif key in SERVER_DERIVED_FIELDS:
                errors[key] = [SERVER_DERIVED_MESSAGE]
            elif key not in ACCEPTED_FIELDS:
                errors[key] = [NOT_ALLOWED_MESSAGE]

        if errors:
            raise FieldNotAccepted(errors)

    def post(self, request):
        self.clean_keys(request.data)

        serializer = AttendancePunchRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        result = AttendancePunchService.record(
            employee=self.employee,
            user=request.user,
            request=serializer.to_request(),
        )

        payload = build_payload(result)

        return success_response(
            data=payload,
            message=payload["message"] or "Tap kehadiran diproses.",
            status_code=200 if result.replayed else 201,
        )
