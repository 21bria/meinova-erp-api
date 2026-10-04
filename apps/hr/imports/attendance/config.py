"""
Membaca **format file** dari satu `ImportProfile`.

Import Profile menjelaskan filenya: pemisah kolom, encoding, kolom mana
yang berisi nomor mesin, kolom mana yang berisi waktu, format waktunya,
zona waktunya, dan apakah barisnya membawa IN/OUT atau cuma tap mentah.

Yang **tidak** dijelaskan Import Profile: jam kerja, shift, hari libur,
dan siapa yang dijadwalkan hari itu. Semua itu milik domain HR dan
dijawab `apps.hr.api.attendance.schedule`. Menaruh "HO 10:00-18:00" di
sini berarti satu perusahaan yang mengubah jam kerjanya harus mengubah
profil impor — dan profil impor yang menentukan jam kerja akan
bertentangan dengan Work Schedule-nya sendiri dalam hitungan minggu.

Seluruh konfigurasi baru tinggal di `ImportProfile.options`, kolom JSON
yang **sudah ada**. Tidak ada migrasi, dan profile lama yang kolomnya
kosong jatuh ke perilaku lama persis seperti sebelumnya.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from apps.hr.api.attendance.schedule import WALL_CLOCK_TZ


OPTIONS_KEY = "attendance"


# ----------------------------------------------------------------------
# Bentuk BARIS file — berapa event yang lahir dari satu baris.
#
# Ini sumbu yang **berbeda** dari `event_mode` di bawah, dan tercampurnya
# sudah sekali membuat file harian terbaca separuh:
#
# * `row_mode`   menjawab "satu baris file itu berapa tap?"
# * `event_mode` menjawab "tap itu IN, OUT, atau tidak diberi tahu?"
#
# Mesin tap mentah mengeluarkan satu baris per tekan; mesin lain
# mengeluarkan satu baris per hari berisi jam masuk dan jam pulang
# sekaligus. Yang kedua **tidak** boleh dipaksa jadi satu event —
# membuang kolom jam pulangnya adalah cara paling sunyi untuk
# melaporkan hari kerja yang terlihat lengkap padahal separuh.
# ----------------------------------------------------------------------

ROW_MODE_RAW_TAP = "raw_tap"
ROW_MODE_DAILY_IN_OUT = "daily_in_out"

ROW_MODES = (
    ROW_MODE_RAW_TAP,
    ROW_MODE_DAILY_IN_OUT,
)

ROW_MODE_LABELS = {
    ROW_MODE_RAW_TAP: "Raw Tap (one row = one tap)",
    ROW_MODE_DAILY_IN_OUT: (
        "Daily In/Out (one row = one work date, up to two taps)"
    ),
}


# Mode penentuan jenis event.
EVENT_MODE_AUTO = "auto"
EVENT_MODE_RAW_TAP = "raw_tap"
EVENT_MODE_EXPLICIT = "explicit"

EVENT_MODES = (
    EVENT_MODE_AUTO,
    EVENT_MODE_RAW_TAP,
    EVENT_MODE_EXPLICIT,
)

EVENT_MODE_LABELS = {
    EVENT_MODE_AUTO: "Auto (use file column when present)",
    EVENT_MODE_RAW_TAP: "Raw Tap (no IN/OUT in file)",
    EVENT_MODE_EXPLICIT: "Explicit IN/OUT from file",
}


# Langkah transform identifier. Urutannya ditentukan daftar di profile,
# bukan urutan di sini — "tambahkan awalan lalu potong nol depan"
# menghasilkan sesuatu yang lain daripada kebalikannya.
TRANSFORM_STEPS = (
    "trim",
    "upper",
    "lower",
    "strip_leading_zeros",
    "left_pad",
    "prefix",
    "suffix",
)


# Jenis event yang dikenali sesudah `value_mapping` profile dijalankan.
EVENT_IN = "in"
EVENT_OUT = "out"
EVENT_BREAK_IN = "break_in"
EVENT_BREAK_OUT = "break_out"
EVENT_UNKNOWN = "unknown"

KNOWN_EVENTS = (
    EVENT_IN,
    EVENT_OUT,
    EVENT_BREAK_IN,
    EVENT_BREAK_OUT,
)


# Seberapa jauh sebelum jam masuk / sesudah jam pulang sebuah tap masih
# dianggap milik hari kerja itu. Empat jam di kedua sisi: cukup lebar
# untuk orang yang datang subuh atau pulang terlambat, cukup sempit
# supaya tap shift malam tidak tertarik ke hari yang salah. Bisa diubah
# per profile, tapi jangan dijadikan cara menambal roster yang salah.
DEFAULT_GRACE_BEFORE_MINUTES = 240
DEFAULT_GRACE_AFTER_MINUTES = 240


def _as_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []

    if isinstance(value, str):
        return [value]

    if isinstance(value, (list, tuple)):
        return [str(item) for item in value if str(item).strip()]

    return []


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def resolve_timezone(name: Any) -> ZoneInfo:
    """
    Zona waktu **file**, bukan zona waktu penyimpanan.

    Mesin absensi menulis jam dinding tanpa offset: `03/07/2026 07.28.54`
    berarti jam tujuh pagi di tempat mesinnya berdiri. `TIME_ZONE`
    proyek ini UTC, jadi menganggap angka itu UTC menggeser seluruh
    presensi tujuh jam — dan geserannya tidak berbunyi, cuma membuat
    semua orang terlihat terlambat setengah hari.

    Bawaannya karena itu jam dinding yang sama dengan yang dipakai
    resolver jadwal (`WALL_CLOCK_TZ`), bukan `TIME_ZONE`.
    """
    text = str(name or "").strip()

    if not text:
        return WALL_CLOCK_TZ

    try:
        return ZoneInfo(text)
    except (ZoneInfoNotFoundError, ValueError):
        return WALL_CLOCK_TZ


@dataclass(frozen=True)
class IdentifierConfig:
    """Cara mengubah nomor mentah mesin jadi kandidat Employee Number."""

    column: str = ""
    steps: tuple[str, ...] = ()
    prefix: str = ""
    suffix: str = ""
    pad_length: int = 0
    pad_char: str = "0"

    # Kalau pemetaan device tidak menemukan apa pun, boleh mencoba
    # mencocokkan hasil transform ke Employee Number. Bawaannya `True`
    # — itu perilaku importer lama, dan mematikannya diam-diam membuat
    # file yang selama ini masuk mendadak nol baris.
    match_employee_number: bool = True

    @property
    def has_transform(self) -> bool:
        return bool(self.steps)


@dataclass(frozen=True)
class AttendanceImportConfig:
    timezone: ZoneInfo = WALL_CLOCK_TZ
    timezone_name: str = str(WALL_CLOCK_TZ)

    datetime_formats: tuple[str, ...] = ()

    # Mode harian memisah tanggal dan jam ke dua kolom, jadi formatnya
    # juga dua. Keduanya tetap milik profile — tidak ada format khas
    # satu mesin yang ditanam di kode.
    date_formats: tuple[str, ...] = ()
    time_formats: tuple[str, ...] = ()

    row_mode: str = ROW_MODE_RAW_TAP

    event_mode: str = EVENT_MODE_AUTO

    device_code: str = ""
    require_device: bool = False

    grace_before_minutes: int = DEFAULT_GRACE_BEFORE_MINUTES
    grace_after_minutes: int = DEFAULT_GRACE_AFTER_MINUTES

    identifier: IdentifierConfig = field(default_factory=IdentifierConfig)

    @classmethod
    def from_options(
        cls,
        options: Any,
        *,
        datetime_formats: Any = None,
    ) -> "AttendanceImportConfig":
        """
        `options` boleh berisi blok `attendance`, boleh juga langsung
        berisi kuncinya. Keduanya diterima supaya profile yang ditulis
        tangan tidak gagal diam-diam karena satu tingkat nesting.
        """
        raw = _as_dict(options)

        section = _as_dict(raw.get(OPTIONS_KEY)) or raw

        identifier_raw = _as_dict(section.get("identifier"))

        steps = _as_list(identifier_raw.get("transform"))

        # Langkah yang tidak dikenal dibuang, bukan melempar: profile
        # ditulis manusia lewat JSON, dan satu salah ketik tidak boleh
        # mematikan seluruh layar impor. Yang salah ketik ketahuan lewat
        # hasil transform yang tidak berubah.
        steps = tuple(
            step
            for step in (str(item).strip().lower() for item in steps)
            if step in TRANSFORM_STEPS
        )

        event_mode = str(
            section.get("event_mode") or EVENT_MODE_AUTO,
        ).strip().lower()

        if event_mode not in EVENT_MODES:
            event_mode = EVENT_MODE_AUTO

        # Bawaannya tap mentah — itu perilaku sebelum mode harian ada,
        # dan profile lama tidak boleh berubah artinya.
        row_mode = str(
            section.get("row_mode") or ROW_MODE_RAW_TAP,
        ).strip().lower()

        if row_mode not in ROW_MODES:
            row_mode = ROW_MODE_RAW_TAP

        work_date = _as_dict(section.get("work_date"))

        timezone_name = str(
            section.get("timezone") or "",
        ).strip()

        resolved_timezone = resolve_timezone(timezone_name)

        formats = tuple(
            _as_list(section.get("datetime_formats"))
            or _as_list(datetime_formats)
        )

        return cls(
            timezone=resolved_timezone,
            timezone_name=timezone_name or str(WALL_CLOCK_TZ),
            datetime_formats=formats,
            date_formats=tuple(_as_list(section.get("date_formats"))),
            time_formats=tuple(_as_list(section.get("time_formats"))),
            row_mode=row_mode,
            event_mode=event_mode,
            device_code=str(section.get("device_code") or "").strip(),
            require_device=bool(section.get("require_device", False)),
            grace_before_minutes=max(
                _as_int(
                    work_date.get("grace_before_minutes"),
                    DEFAULT_GRACE_BEFORE_MINUTES,
                ),
                0,
            ),
            grace_after_minutes=max(
                _as_int(
                    work_date.get("grace_after_minutes"),
                    DEFAULT_GRACE_AFTER_MINUTES,
                ),
                0,
            ),
            identifier=IdentifierConfig(
                column=str(identifier_raw.get("column") or "").strip(),
                steps=steps,
                prefix=str(identifier_raw.get("prefix") or ""),
                suffix=str(identifier_raw.get("suffix") or ""),
                pad_length=max(
                    _as_int(identifier_raw.get("pad_length"), 0),
                    0,
                ),
                pad_char=(
                    str(identifier_raw.get("pad_char") or "0")[:1]
                    or "0"
                ),
                match_employee_number=bool(
                    identifier_raw.get("match_employee_number", True),
                ),
            ),
        )
