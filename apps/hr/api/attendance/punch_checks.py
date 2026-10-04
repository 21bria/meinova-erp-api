"""
Pemeriksaan tap Self Service: kontrak, registri, dan kebijakan.

Berkas ini titik sambung mesin pemeriksaan **masa depan** (wajah,
liveness, geofence). `AttendancePunchService` hanya bertanya "pemeriksaan
X wajib?" dan "apa hasilnya?" — siklus hidup tap tidak perlu ditulis
ulang saat mesinnya datang. Mesin baru cukup:

    register_check("face", MyFaceCheck())

Yang **sengaja tidak ada** di ATT-BIO-1
---------------------------------------
Tidak ada pemeriksaan wajah, liveness, atau geofence sungguhan. Ketiganya
terdaftar sebagai `NotConfiguredCheck`, yang selalu menjawab
`NOT_CONFIGURED` — bukan PASS. Kebijakan bawaan mewajibkan ketiganya,
jadi selama mesinnya belum ada endpoint menjawab UNAVAILABLE (gagal
tertutup) dan, kalaupun lolos ke dalam, keputusannya REJECTED.

Satu-satunya pemeriksaan yang nyata: **lokasi** — koordinat ada dan
akurasi yang dilaporkan perangkat tidak lebih buruk dari batas. Itu
bukan deteksi pemalsuan GPS dan tidak mengaku sebagai itu.

Sejak ATT-GPS-1 **geofence** juga nyata (`GeofenceCheck`, Haversine ke
`AttendanceGeofence` lokasi kerja pegawai). Wajah dan liveness tetap
`NotConfiguredCheck`.

ATT-BIO-2A — fondasi netral penyedia
------------------------------------
Masih **tanpa** mesin wajah/liveness sungguhan. Yang ditambahkan hanya
kontrak yang berlaku apa pun penyedianya nanti (ATT-BIO-2B):

* `BiometricSubject` — subjek pendaftaran ACTIVE milik pegawai yang
  sedang login, diserahkan service ke mesin wajah. Mesin tidak pernah
  mencari pendaftaran sendiri, jadi tidak bisa membandingkan dengan
  pegawai lain.
* `PunchCheck.provider` — kode penyedia mesin wajah; pendaftaran dicari
  untuk penyedia ini.
* `FaceMatchPolicy` — ambang kecocokan dari settings
  `ATTENDANCE_FACE_MATCH_POLICY`. **Tidak ada nilai bawaan.** Kosong /
  tidak lengkap / penyedia berbeda = belum dikalibrasi = FACE dianggap
  belum terpasang (endpoint UNAVAILABLE, tidak ada yang ditulis).
  Mesin boleh menjawab PASS, tetapi service yang memutuskan: skornya
  harus ada, versi modelnya harus sama dengan yang dikalibrasi, dan
  skornya harus lolos pembanding kebijakan. Selain itu bukan PASS.
"""

from __future__ import annotations

import math
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from django.conf import settings
from decimal import InvalidOperation

from apps.hr.models.attendance.verification import (
    BiometricCheckResult,
    GeofenceCheckResult,
    LocationCheckResult,
    PunchCheckRequirement,
)


FACE = "face"
LIVENESS = "liveness"
LOCATION = "location"
GEOFENCE = "geofence"

# Urutan jalannya. Yang murah dan tidak butuh pihak ketiga lebih dulu;
# geofence butuh lokasi; wajah sesudah liveness supaya foto yang bukan
# orang hidup tidak pernah dicocokkan. Begitu satu pemeriksaan wajib
# gagal, sisanya tidak dijalankan (`NOT_RUN`).
CHECK_ORDER = (LOCATION, GEOFENCE, LIVENESS, FACE)

# Hasil yang dihitung lolos, per pemeriksaan.
PASSING = {
    LOCATION: LocationCheckResult.PASS,
    GEOFENCE: GeofenceCheckResult.INSIDE,
    LIVENESS: BiometricCheckResult.PASS,
    FACE: BiometricCheckResult.PASS,
}

# Pemeriksaan yang membutuhkan selfie.
NEEDS_PHOTO = frozenset({LIVENESS, FACE})


# ----------------------------------------------------------------------
# Kontrak
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class BiometricSubject:
    """
    Pendaftaran biometrik ACTIVE pegawai yang sedang login, untuk satu
    penyedia. `subject_id` = UUID acak buatan ERP yang dikenal penyedia
    (bukan rahasia, bukan materi biometrik). Jangan dicatat ke log.
    """

    provider: str
    subject_id: str
    version: int


@dataclass(frozen=True)
class PunchEvidence:
    """
    Bahan pemeriksaan. **Seluruhnya dari server** atau bukti mentah yang
    sudah tersimpan di `AttendanceLog` — tidak ada satu kolom pun yang
    berarti "client bilang lolos".
    """

    employee: Any
    log: Any
    punch_type: str
    occurred_at: datetime
    work_date: date
    latitude: Decimal | None
    longitude: Decimal | None
    accuracy_meters: Decimal | None
    photo: Any
    policy: "PunchPolicy"
    # Diisi service untuk pemeriksaan wajah; None = belum terdaftar.
    subject: BiometricSubject | None = None


@dataclass(frozen=True)
class CheckOutcome:
    result: str
    detail: str = ""

    # Diisi mesin yang memang menghasilkannya. Kosong = tidak berlaku.
    score: Decimal | None = None
    threshold: Decimal | None = None
    provider: str = ""
    model_version: str = ""
    accuracy_meters: Decimal | None = None
    distance_meters: Decimal | None = None
    radius_meters: Decimal | None = None


class PunchCheck:
    """
    Satu pemeriksaan. Turunannya menyetel `configured` dan `run()`.

    `run()` boleh melempar; service menangkapnya jadi `ERROR`, bukan 500.
    """

    configured: bool = True

    # Kode penyedia. Wajib untuk mesin wajah: pendaftaran pegawai dicari
    # untuk penyedia ini, dan kebijakan ambangnya harus untuk penyedia
    # yang sama.
    provider: str = ""

    def run(self, evidence: PunchEvidence) -> CheckOutcome:  # pragma: no cover
        raise NotImplementedError


class NotConfiguredCheck(PunchCheck):
    """Belum ada mesinnya. Menjawab `NOT_CONFIGURED`, tidak pernah PASS."""

    configured = False

    def run(self, evidence: PunchEvidence) -> CheckOutcome:
        return CheckOutcome(
            result="not_configured",
            detail="Mesin pemeriksaan belum terpasang.",
        )


class LocationCheck(PunchCheck):
    """
    Koordinat ada dan akurasinya cukup. **Bukan** deteksi GPS palsu.

    Rentang lintang/bujur sudah ditolak serializer sebelum sampai sini.
    """

    def run(self, evidence: PunchEvidence) -> CheckOutcome:
        if evidence.latitude is None or evidence.longitude is None:
            return CheckOutcome(
                result=LocationCheckResult.UNAVAILABLE,
                detail="Perangkat tidak mengirim koordinat.",
            )

        limit = Decimal(evidence.policy.max_gps_accuracy_meters)
        accuracy = evidence.accuracy_meters

        if accuracy is None:
            return CheckOutcome(
                result=LocationCheckResult.LOW_ACCURACY,
                detail="Perangkat tidak melaporkan akurasi lokasi.",
            )

        if accuracy > limit:
            return CheckOutcome(
                result=LocationCheckResult.LOW_ACCURACY,
                detail=f"Akurasi {accuracy} m melebihi batas {limit} m.",
                accuracy_meters=accuracy,
            )

        return CheckOutcome(
            result=LocationCheckResult.PASS,
            accuracy_meters=accuracy,
        )


# Jari-jari rata-rata bumi (IUGG), meter. Galat Haversine terhadap
# elipsoid < 0,5% — jauh di bawah akurasi GPS ponsel pada radius
# puluhan–ratusan meter.
EARTH_RADIUS_M = 6_371_008.8

DISTANCE_STEP = Decimal("0.01")


def haversine_m(lat1, lon1, lat2, lon2) -> Decimal:
    """Jarak lingkaran besar dua titik (derajat desimal), dalam meter."""
    phi1 = math.radians(float(lat1))
    phi2 = math.radians(float(lat2))
    d_phi = phi2 - phi1
    d_lambda = math.radians(float(lon2) - float(lon1))

    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )

    meters = 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(a)))

    return Decimal(repr(meters)).quantize(DISTANCE_STEP)


class GeofenceCheck(PunchCheck):
    """
    Koordinat tap berada di dalam geofence aktif lokasi kerja pegawai?
    (ATT-GPS-1)

    Lokasi kerja = `AttendanceLog.location` tap ini, yang diisi service
    dari penempatan aktif pegawai (`AttendanceImportWriter.get_assignment`)
    — otoritas lokasi yang sama dengan jalur tap lain, bukan sumber baru.

    Berjalan **sesudah** pemeriksaan lokasi, jadi koordinat yang sampai
    sini sudah ada dan akurasinya sudah lolos batas. Di dalam = jarak ke
    titik pusat ≤ radius (batasnya termasuk). Akurasi tidak dipakai untuk
    memperlebar atau mempersempit lingkaran.
    """

    def run(self, evidence: PunchEvidence) -> CheckOutcome:
        from apps.hr.models import AttendanceGeofence

        location_id = getattr(evidence.log, "location_id", None)

        if location_id is None:
            return CheckOutcome(
                result=GeofenceCheckResult.NO_WORK_LOCATION,
                detail="Penempatan aktif pegawai tidak punya lokasi kerja.",
            )

        geofence = (
            AttendanceGeofence.objects
            .filter(location_id=location_id, is_active=True, is_deleted=False)
            .first()
        )

        if geofence is None:
            return CheckOutcome(
                result=GeofenceCheckResult.NO_GEOFENCE,
                detail="Lokasi kerja belum punya geofence aktif.",
            )

        if evidence.latitude is None or evidence.longitude is None:
            return CheckOutcome(
                result=GeofenceCheckResult.ERROR,
                detail="Koordinat tidak tersedia.",
            )

        distance = haversine_m(
            evidence.latitude,
            evidence.longitude,
            geofence.latitude,
            geofence.longitude,
        )

        radius = Decimal(geofence.radius_m)

        return CheckOutcome(
            result=(
                GeofenceCheckResult.INSIDE
                if distance <= radius
                else GeofenceCheckResult.OUTSIDE
            ),
            distance_meters=distance,
            radius_meters=radius,
            accuracy_meters=evidence.accuracy_meters,
        )


# ----------------------------------------------------------------------
# Mode uji coba GPS (ATT-GPS-1)
# ----------------------------------------------------------------------


def trial_schemas() -> frozenset[str]:
    """
    Schema tenant yang **eksplisit** didaftarkan untuk uji coba GPS.

    Hanya nama schema persis. Pola (`*`), nama kosong, dan schema publik
    dibuang — tidak ada cara menyalakannya untuk semua tenant sekaligus.
    """
    from django_tenants.utils import get_public_schema_name

    raw = getattr(settings, "ATTENDANCE_SELF_PUNCH_TRIAL_SCHEMAS", ()) or ()

    if isinstance(raw, str):
        raw = raw.split(",")

    public = get_public_schema_name()

    names = set()

    for name in raw:
        name = str(name or "").strip()

        if not name or name == public or any(ch in name for ch in "*?[]%"):
            continue

        names.add(name)

    return frozenset(names)


def trial_active() -> bool:
    """Tenant yang sedang melayani permintaan ini terdaftar uji coba?"""
    from django.db import connection

    schema = str(getattr(connection, "schema_name", "") or "")

    return bool(schema) and schema in trial_schemas()


# ----------------------------------------------------------------------
# Registri
# ----------------------------------------------------------------------


def _default_registry() -> dict[str, PunchCheck]:
    return {
        LOCATION: LocationCheck(),
        GEOFENCE: GeofenceCheck(),
        LIVENESS: NotConfiguredCheck(),
        FACE: NotConfiguredCheck(),
    }


_REGISTRY: dict[str, PunchCheck] = _default_registry()


def get_check(key: str) -> PunchCheck:
    return _REGISTRY[key]


def register_check(key: str, check: PunchCheck) -> None:
    """Pasang mesin untuk satu pemeriksaan. Kunci harus salah satu `CHECK_ORDER`."""
    if key not in CHECK_ORDER:
        raise KeyError(f"Pemeriksaan tidak dikenal: {key}")

    _REGISTRY[key] = check


@contextmanager
def override_checks(**checks: PunchCheck):
    """Ganti mesin sementara — untuk test. Registri dipulihkan sesudahnya."""
    previous = dict(_REGISTRY)

    try:
        for key, check in checks.items():
            register_check(key, check)

        yield
    finally:
        _REGISTRY.clear()
        _REGISTRY.update(previous)


# ----------------------------------------------------------------------
# Kebijakan
# ----------------------------------------------------------------------


COMPARATORS = {
    # Skor kemiripan: makin tinggi makin mirip.
    "gte": lambda score, threshold: score >= threshold,
    # Skor jarak: makin rendah makin mirip.
    "lte": lambda score, threshold: score <= threshold,
}


@dataclass(frozen=True)
class FaceMatchPolicy:
    """
    Ambang kecocokan wajah yang **sudah dikalibrasi** untuk satu penyedia
    dan satu versi model. Tidak ada angka bawaan di kode.

    settings.ATTENDANCE_FACE_MATCH_POLICY = {
        "provider": "<kode penyedia>",
        "model_version": "<versi model yang dikalibrasi>",
        "threshold": "<angka desimal, sebagai string>",
        "comparator": "gte" | "lte",
    }
    """

    provider: str
    model_version: str
    threshold: Decimal
    comparator: str

    @classmethod
    def from_settings(cls) -> "FaceMatchPolicy | None":
        raw = getattr(settings, "ATTENDANCE_FACE_MATCH_POLICY", None)

        if not isinstance(raw, dict):
            return None

        provider = str(raw.get("provider") or "").strip()
        model_version = str(raw.get("model_version") or "").strip()
        comparator = str(raw.get("comparator") or "").strip()
        threshold = raw.get("threshold")

        if not provider or not model_version or comparator not in COMPARATORS:
            return None

        # Angka lewat string: float membawa galat pembulatan ke ambang.
        if threshold is None or isinstance(threshold, (float, bool)):
            return None

        try:
            value = Decimal(str(threshold))
        except (InvalidOperation, ValueError):
            return None

        if not value.is_finite():
            return None

        return cls(
            provider=provider,
            model_version=model_version,
            threshold=value,
            comparator=comparator,
        )

    def accepts(self, score: Decimal | None) -> bool:
        if score is None:
            return False

        return COMPARATORS[self.comparator](Decimal(score), self.threshold)

    def snapshot(self) -> dict:
        return {
            "provider": self.provider,
            "model_version": self.model_version,
            "threshold": str(self.threshold),
            "comparator": self.comparator,
        }


@dataclass(frozen=True)
class PunchPolicy:
    requirements: dict[str, str] = field(default_factory=dict)
    max_gps_accuracy_meters: int = 100
    min_interval_seconds: int = 60
    face_match: FaceMatchPolicy | None = None

    def is_required(self, key: str) -> bool:
        return self.requirements.get(key) == PunchCheckRequirement.REQUIRED

    def face_calibrated(self) -> bool:
        """Ambang ada, dan untuk penyedia mesin wajah yang terpasang."""
        check = get_check(FACE)

        return (
            self.face_match is not None
            and bool(check.provider)
            and self.face_match.provider == check.provider
        )

    def is_configured(self, key: str) -> bool:
        if not get_check(key).configured:
            return False

        if key == FACE:
            return self.face_calibrated()

        return True

    def unconfigured_required(self) -> list[str]:
        return [
            key
            for key in CHECK_ORDER
            if self.is_required(key) and not self.is_configured(key)
        ]

    def snapshot(self) -> dict:
        return {
            "requirements": dict(self.requirements),
            "max_gps_accuracy_meters": self.max_gps_accuracy_meters,
            "min_interval_seconds": self.min_interval_seconds,
            "configured": {
                key: self.is_configured(key)
                for key in CHECK_ORDER
            },
            "face_match": (
                self.face_match.snapshot()
                if self.face_match is not None
                else None
            ),
        }


def resolve_policy(employee, work_date: date) -> PunchPolicy:
    """
    Kebijakan tap untuk satu pegawai pada satu hari kerja.

    **Titik sambung**, bukan aturan akhir. ATT-BIO-1 mewajibkan keempat
    pemeriksaan untuk semua orang. Kebijakan Business Trip / Travel
    Request / penugasan lapangan (geofence lain atau tidak wajib, GPS
    tetap wajib) masuk di sini pada tahap berikutnya — tidak ada bypass
    global, dan tidak ada yang bisa dimatikan lewat settings.
    """
    return PunchPolicy(
        requirements={
            key: PunchCheckRequirement.REQUIRED
            for key in CHECK_ORDER
        },
        max_gps_accuracy_meters=int(
            getattr(settings, "ATTENDANCE_SELF_PUNCH_MAX_GPS_ACCURACY_METERS", 100),
        ),
        min_interval_seconds=int(
            getattr(settings, "ATTENDANCE_SELF_PUNCH_MIN_INTERVAL_SECONDS", 60),
        ),
        face_match=FaceMatchPolicy.from_settings(),
    )
