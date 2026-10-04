"""
Panggung tap kehadiran Self Service (ATT-BIO-1).

Di atas pondasi Attendance Import — company, lokasi, shift, dan
pegawai yang sama — ditambah akun login, selfie, shift malam 20:00–05:00,
dan mesin pemeriksaan **pengganti test**.

Tentang mesin pengganti: produksi tidak punya mesin wajah, liveness,
atau geofence di tahap ini, dan memang harus gagal tertutup. Untuk
menguji jalur ACCEPTED, test memasang mesin pengganti lewat
`override_checks()` — registri dipulihkan begitu blok selesai, jadi
tidak ada PASS palsu yang tertinggal di luar test.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from itertools import count
from uuid import uuid4
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from apps.administration.models.references.hr_attendance import Shift
from apps.hr.api.attendance import punch_checks as checks
from apps.hr.api.attendance.biometric_enrollment import BiometricEnrollmentService
from apps.hr.api.attendance.punch import AttendancePunchService, PunchRequest
from apps.hr.models import EmployeeLeave, LEAVE_DEDUCTING_STATUSES
from apps.administration.models import LeaveType
from apps.uploads.models import UploadedFile
from apps.uploads.services.upload_service import UploadService

from .base import AttendanceImportTestCase


User = get_user_model()

WIB = ZoneInfo("Asia/Jakarta")

# Rabu — hari kerja kantor (10:00–18:00) untuk pegawai bershift.
WEDNESDAY = date(2026, 7, 1)
THURSDAY = date(2026, 7, 2)
# Sabtu — tidak terjadwal untuk pegawai kantor.
SATURDAY = date(2026, 7, 4)

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00"
    b"\x01\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9c"
    b"c\x00\x01\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)

ENABLED = override_settings(ATTENDANCE_SELF_PUNCH_ENABLED=True)

# Penyedia wajah pengganti test dan kebijakan ambangnya (ATT-BIO-2A).
# Angka ini milik test, bukan rekomendasi produksi — produksi tidak
# punya ambang sampai penyedia sungguhan dikalibrasi.
TEST_FACE_PROVIDER = "test-double"
TEST_FACE_MODEL = "test-model-1"
TEST_FACE_POLICY = {
    "provider": TEST_FACE_PROVIDER,
    "model_version": TEST_FACE_MODEL,
    "threshold": "0.80",
    "comparator": "gte",
}


def unique_png() -> bytes:
    """PNG 1x1 sah dengan warna acak — byte (dan SHA-256-nya) berbeda tiap kali."""
    import io
    import os

    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (1, 1), tuple(os.urandom(3))).save(
        buffer,
        format="PNG",
        pnginfo=_png_info(os.urandom(8).hex()),
    )

    return buffer.getvalue()


def _png_info(nonce: str):
    from PIL.PngImagePlugin import PngInfo

    info = PngInfo()
    info.add_text("nonce", nonce)

    return info


def wib(day: date, hour: int, minute: int = 0, second: int = 0) -> datetime:
    return datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=WIB)


class FixedCheck(checks.PunchCheck):
    """Mesin pengganti test: selalu menjawab hasil yang sama."""

    provider = TEST_FACE_PROVIDER

    def __init__(self, result: str, **extra):
        self.result = result
        self.extra = extra
        self.calls = []

    def run(self, evidence):
        self.calls.append(evidence)

        return checks.CheckOutcome(
            result=self.result,
            provider=TEST_FACE_PROVIDER,
            **self.extra,
        )


def face_pass(score: str = "0.93", **extra) -> FixedCheck:
    """Mesin wajah pengganti yang menjawab PASS dengan skor dan versi model."""
    extra.setdefault("model_version", TEST_FACE_MODEL)

    return FixedCheck("pass", score=Decimal(score), **extra)


class ExplodingCheck(checks.PunchCheck):
    provider = TEST_FACE_PROVIDER

    def run(self, evidence):
        raise RuntimeError("engine down")


@contextmanager
def passing_engines(*, face_policy=TEST_FACE_POLICY, **overrides):
    """
    Wajah, liveness, geofence lolos — kecuali yang diganti — dengan
    kebijakan ambang wajah test terpasang (`face_policy=None` = belum
    dikalibrasi).
    """
    engines = {
        checks.FACE: face_pass(),
        checks.LIVENESS: FixedCheck("pass"),
        checks.GEOFENCE: FixedCheck("inside"),
    }

    engines.update(overrides)

    with override_settings(ATTENDANCE_FACE_MATCH_POLICY=face_policy):
        with checks.override_checks(**engines):
            yield engines


class SelfPunchTestCase(AttendanceImportTestCase):
    reusable_schema_name = "fast_attendance_punch"

    # Saklar per kelas. **Bukan** `@override_settings` di kelas: basis
    # tenant yang dipakai ulang tidak memanggil `SimpleTestCase.setUpClass`,
    # yang justru memasang override tingkat kelas — dekoratornya diam-diam
    # tidak berlaku. Dekorator di tingkat metode tetap berlaku.
    punch_enabled = False

    _seq = count(1)

    def setUp(self):
        super().setUp()

        if self.punch_enabled:
            switch = override_settings(ATTENDANCE_SELF_PUNCH_ENABLED=True)
            switch.enable()
            self.addCleanup(switch.disable)

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "attendance-punch"
        tenant.name = "Attendance Punch"

    @classmethod
    def build_baseline(cls):
        super().build_baseline()

        cls.late_night_shift, _ = Shift.objects.get_or_create(
            code="AIM-NIGHT-2005",
            is_deleted=False,
            defaults={
                "name": "Night 20-05",
                "start_time": "20:00",
                "end_time": "05:00",
                "crosses_midnight": True,
            },
        )

        cls.leave_type, _ = LeaveType.objects.get_or_create(
            code="AIM-PUNCH-ANNUAL",
            is_deleted=False,
            defaults={"name": "Annual"},
        )

    # ------------------------------------------------------------------

    @classmethod
    def make_user(cls, *, superuser: bool = False):
        n = next(cls._seq)

        return User.objects.create_user(
            username=f"punch.user{n}",
            email=f"punch.user{n}@example.test",
            password="Test-Only#Pw1",
            is_superuser=superuser,
            is_staff=superuser,
        )

    def make_punch_employee(self, *, shift=None, enrolled=True, **kwargs):
        """
        Pegawai ber-akun. `enrolled=True` = punya pendaftaran wajah ACTIVE
        di penyedia test — pendaftaran eksplisit, bukan dari avatar.
        """
        user = self.make_user()

        employee = self.make_employee(
            shift=shift or self.office_shift,
            user=user,
            **kwargs,
        )

        if enrolled:
            BiometricEnrollmentService.enroll(
                employee=employee,
                provider=TEST_FACE_PROVIDER,
                user=None,
            )

        return employee, user

    @staticmethod
    def make_selfie(
        user,
        *,
        category=UploadedFile.Category.ATTENDANCE_SELFIE,
        content: bytes | None = None,
    ):
        """
        Selfie baru dengan byte **unik** (seperti tangkapan kamera
        sungguhan), kecuali `content` dioper — untuk menguji selfie yang
        dipakai ulang (ATT-BIO-2A).
        """
        return UploadService.create(
            uploaded_file=SimpleUploadedFile(
                f"selfie-{uuid4().hex[:8]}.png",
                content if content is not None else unique_png(),
                content_type="image/png",
            ),
            metadata={"category": category},
            user=user,
            generate_preview=False,
        )

    def make_leave(self, employee, day):
        return EmployeeLeave.objects.create(
            employee=employee,
            company=self.company,
            location=self.site,
            leave_type=self.leave_type,
            start_date=day,
            end_date=day,
            total_days=1,
            status=LEAVE_DEDUCTING_STATUSES[-1],
        )

    def request(
        self,
        punch_type: str = "in",
        *,
        punch_id=None,
        photo="auto",
        user=None,
        latitude="-6.2000000",
        longitude="106.8166667",
        accuracy="12.50",
    ) -> PunchRequest:
        from decimal import Decimal

        if photo == "auto":
            photo = self.make_selfie(user) if user is not None else None

        return PunchRequest(
            client_punch_id=punch_id or uuid4(),
            punch_type=punch_type,
            latitude=None if latitude is None else Decimal(latitude),
            longitude=None if longitude is None else Decimal(longitude),
            accuracy_meters=None if accuracy is None else Decimal(accuracy),
            photo=photo,
        )

    def punch(self, employee, user, punch_type, at, **kwargs):
        """Satu tap lewat service, dengan selfie milik `user`."""
        req = kwargs.pop("req", None) or self.request(
            punch_type,
            user=user,
            **kwargs,
        )

        return AttendancePunchService.record(
            employee=employee,
            user=user,
            request=req,
            now=at,
        )
