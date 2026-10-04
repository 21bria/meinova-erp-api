"""
Satu baris file mesin -> satu tap presensi yang siap ditulis.

Urutannya sama untuk semua profile, HO maupun site — yang berbeda cuma
konfigurasinya:

    kolom file
      -> identifier mesin        (identity.py)
      -> Employee ERP            (identity.py)
      -> Feature Applicability   (apps.hr.applicability)
      -> Organization Scope      (apps.accounts.scoping)
      -> hari kerja + jadwal     (workdate.py -> apps.hr.api.attendance.schedule)
      -> duplikat                (AttendanceLog.external_id)

Tidak ada satu pun cabang di berkas ini yang membaca nama perusahaan,
nama lokasi, merek mesin, atau awalan nomor pegawai. Kalau nanti ada
yang menambahkannya, `test_no_hardcoded_context` akan gagal — dan itu
memang tujuannya.
"""

from __future__ import annotations

import hashlib
from datetime import date, datetime, time
from datetime import timezone as dt_timezone
from typing import Any

from django.utils.dateparse import parse_datetime

from apps.accounts.permissions import view_permission_for
from apps.accounts.scoping import DataScopeService
from apps.framework.imports import ImportNormalizer
from apps.hr.api.employee.scope import EMPLOYEE_SCOPE
from apps.hr.applicability import HRFeature, is_applicable
from apps.hr.imports.services.matcher import AttendanceEmployeeMatcher
from apps.hr.imports.services.normalizer import AttendanceImportNormalizer
from apps.hr.models import (
    AttendanceLog,
    AttendanceSource,
    Employee,
    OrganizationAssignment,
)

from . import statuses
from .config import (
    EVENT_MODE_EXPLICIT,
    EVENT_MODE_RAW_TAP,
    EVENT_UNKNOWN,
    KNOWN_EVENTS,
    ROW_MODE_DAILY_IN_OUT,
    AttendanceImportConfig,
)
from .identity import resolve_device, resolve_employee
from .workdate import ScheduleResolution
from . import workdate as workdate_module


# Format waktu bawaan. Sengaja **tidak** memuat format khas satu vendor:
# yang tidak ada di sini diisi lewat `datetime_formats` pada Import
# Profile, dan itulah gunanya kolom tersebut. Menambahkan format vendor
# ke daftar ini berarti importer diam-diam mulai mengenali satu merek
# mesin secara khusus.
FALLBACK_DATETIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y/%m/%d %H:%M:%S",
    "%Y/%m/%d %H:%M",
    "%d/%m/%Y %H:%M:%S",
    "%d/%m/%Y %H:%M",
    "%Y%m%d%H%M%S",
    "%Y%m%d%H%M",
)


# Sumber baris presensi hasil import file.
LOG_SOURCE = AttendanceSource.IMPORT


def parse_moment(
    value: Any,
    config: AttendanceImportConfig,
) -> datetime | None:
    """
    Teks waktu dari file -> datetime ber-timezone.

    Format yang dicoba: yang ditulis di Import Profile dulu, baru
    daftar cadangan. Urutan itu penting — `01/07/2026` sah dibaca dua
    cara, dan yang menentukan harus profile, bukan tebakan.
    """
    if value in (None, ""):
        return None

    if isinstance(value, datetime):
        parsed = value

    else:
        raw = str(value).strip()

        parsed = None

        try:
            parsed = parse_datetime(raw)
        except ValueError:
            parsed = None

        if parsed is None:
            for fmt in (
                *config.datetime_formats,
                *FALLBACK_DATETIME_FORMATS,
            ):
                try:
                    parsed = datetime.strptime(raw, fmt)
                except (TypeError, ValueError):
                    continue

                break

        if parsed is None:
            return None

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=config.timezone)

    return parsed


def parse_day(value: Any, config: AttendanceImportConfig) -> date | None:
    """
    Kolom tanggal -> `date`. Format profile dicoba lebih dulu.

    Urutannya penting dengan alasan yang sama seperti `parse_moment()`:
    `01/07/2026` sah dibaca dua cara, dan yang menentukan harus
    profile — bukan urutan daftar cadangan.
    """
    if isinstance(value, datetime):
        return value.date()

    if isinstance(value, date):
        return value

    text = ImportNormalizer.clean_text(value)

    if not text:
        return None

    for fmt in config.date_formats:
        try:
            return datetime.strptime(text, fmt).date()
        except (TypeError, ValueError):
            continue

    return AttendanceImportNormalizer.parse_attendance_date(text)


def parse_clock(
    value: Any,
    config: AttendanceImportConfig | None = None,
) -> time | None:
    """Kolom jam -> `time`. Format profile dicoba lebih dulu."""
    if isinstance(value, datetime):
        return value.time()

    if isinstance(value, time):
        return value

    text = ImportNormalizer.clean_text(value)

    if not text:
        return None

    for fmt in (config.time_formats if config is not None else ()):
        try:
            return datetime.strptime(text, fmt).time()
        except (TypeError, ValueError):
            continue

    return AttendanceImportNormalizer.parse_attendance_time(text)


# ----------------------------------------------------------------------
# Mode harian: satu baris -> maksimal dua event
# ----------------------------------------------------------------------


# Kunci internal yang ditempelkan `expand_daily_row()` ke baris hasil
# pemekaran. Berawalan `_` supaya tidak ikut ke `raw_payload`.
SLOT_KEY = "_event_slot"
SLOT_TIME_KEY = "_event_time"
SLOT_INCOMPLETE_KEY = "_daily_incomplete"
SLOT_REASON_KEY = "_daily_reason"


def expand_daily_row(
    raw_row: dict[str, Any],
    *,
    mapping: dict[str, Any],
    config: AttendanceImportConfig,
) -> list[dict[str, Any]]:
    """
    Satu baris harian jadi satu atau dua baris event.

    Yang **tidak** dilakukan di sini: mengarang jam yang tidak ada.
    Kolom pulang yang kosong menghasilkan satu event saja, ditandai
    `INCOMPLETE DAY` — bukan jam pulang yang disamakan dengan jam
    masuk. Bedanya terlihat di laporan: "pulangnya belum tercatat"
    dan "pulang tepat waktu" adalah dua hal yang berbeda, dan yang
    kedua tidak boleh terbit dari ketiadaan data.

    Baris yang **sama sekali** tidak punya jam tetap dikembalikan satu
    — supaya ia muncul di layar review sebagai baris bermasalah, bukan
    hilang begitu saja dari hitungan.
    """
    raw_in = ImportNormalizer.pick(raw_row, mapping.get("check_in") or [])
    raw_out = ImportNormalizer.pick(raw_row, mapping.get("check_out") or [])

    text_in = ImportNormalizer.clean_text(raw_in)
    text_out = ImportNormalizer.clean_text(raw_out)

    def emit(slot: str, value: Any, *, incomplete: bool, reason: str = ""):
        return {
            **raw_row,
            SLOT_KEY: slot,
            SLOT_TIME_KEY: value,
            SLOT_INCOMPLETE_KEY: incomplete,
            SLOT_REASON_KEY: reason,
        }

    if text_in and text_out and text_in != text_out:
        return [
            emit("in", raw_in, incomplete=False),
            emit("out", raw_out, incomplete=False),
        ]

    if text_in and text_out:
        # Jam masuk dan jam pulang identik. Itu satu tap yang tercatat
        # dua kali, bukan hari kerja nol menit — dan menerbitkan dua
        # event membuat baris presensinya terlihat lengkap.
        return [
            emit(
                "in",
                raw_in,
                incomplete=True,
                reason=(
                    "Check in and check out are identical; recorded as "
                    "a single tap."
                ),
            ),
        ]

    if text_in:
        return [
            emit(
                "in",
                raw_in,
                incomplete=True,
                reason="Row has no check out time.",
            ),
        ]

    if text_out:
        return [
            emit(
                "out",
                raw_out,
                incomplete=True,
                reason="Row has no check in time.",
            ),
        ]

    return [
        emit(
            "",
            None,
            incomplete=True,
            reason="Row has neither a check in nor a check out time.",
        ),
    ]


def resolve_event(
    raw_value: Any,
    config: AttendanceImportConfig,
) -> tuple[str, bool]:
    """
    `(jenis event, terbaca)`.

    Nilai vendor seperti `0`/`1` diterjemahkan `value_mapping` pada
    profile **sebelum** sampai ke sini — jadi tidak ada satu pun tabel
    IN/OUT milik vendor yang tertanam di kode.
    """
    text = ImportNormalizer.clean_text(raw_value).lower()

    if config.event_mode == EVENT_MODE_RAW_TAP:
        # File memang tidak membawa IN/OUT. Kolom apa pun yang kebetulan
        # ada diabaikan dengan sengaja.
        return EVENT_UNKNOWN, True

    if text in KNOWN_EVENTS:
        return text, True

    if config.event_mode == EVENT_MODE_EXPLICIT:
        return EVENT_UNKNOWN, False

    return EVENT_UNKNOWN, True


def build_fingerprint(
    *,
    profile_code: str,
    device_code: str,
    raw_identifier: str,
    moment: datetime,
    event: str,
) -> str:
    """
    Identitas satu tap, stabil antar unggahan.

    Dipakai sebagai `AttendanceLog.external_id`, dan tabel itu sudah
    punya unique `(source, external_id)` — jadi mengunggah file yang
    sama dua kali ditolak database, bukan cuma oleh pemeriksaan di
    aplikasi yang bisa terlewat saat dua job jalan bersamaan.

    Sumbernya ikut disimpan di `raw_payload` supaya baris yang
    dianggap duplikat masih bisa dijelaskan tanpa membalik hash.
    """
    # Waktunya diseragamkan ke UTC supaya sidik jarinya tidak bergantung
    # pada cara satu proses kebetulan merender offset.
    payload = "|".join([
        str(device_code or "").strip().lower()
        or str(profile_code or "").strip().lower(),
        str(raw_identifier or "").strip().lower(),
        moment.astimezone(dt_timezone.utc).isoformat(),
        str(event or ""),
    ])

    digest = hashlib.sha1(
        payload.encode("utf-8"),
    ).hexdigest()

    return f"tap:{digest}"


def fingerprint_payload(
    *,
    profile_code: str,
    device_code: str,
    raw_identifier: str,
    moment: datetime,
    event: str,
) -> str:
    return "|".join([
        str(device_code or "") or str(profile_code or ""),
        str(raw_identifier or ""),
        moment.isoformat(),
        str(event or ""),
    ])


# ----------------------------------------------------------------------
# Diagnosa kolom yang tidak ketemu
# ----------------------------------------------------------------------


def _columns_of(normalized: dict[str, Any]) -> set[str]:
    return {
        str(key).strip().lower()
        for key in (normalized.get("raw_payload") or {})
    }


def _alias_present(
    columns: set[str],
    mapping: dict[str, Any],
    target: str,
) -> bool:
    return bool(columns & set(mapping.get(target) or []))


def _not_found_message(
    *,
    columns: set[str],
    mapping: dict[str, Any],
    targets: list[str],
) -> str:
    """
    Pesan untuk baris yang gagal karena **kolomnya tidak ada**.

    Ini beda sebab dari "nilainya tidak terbaca", dan membedakannya
    penting: yang pertama diperbaiki dengan mengubah `mapping` di Import
    Profile, yang kedua dengan mengubah `datetime_formats`. Pesan lama
    ("Timestamp '' could not be read with this profile's datetime
    formats") selalu menyebut sebab kedua — jadi orang menghabiskan dua
    putaran mengutak-atik format tanggal untuk file yang sebenarnya cuma
    salah nama kolom.
    """
    parts = []

    for target in targets:
        aliases = mapping.get(target) or []

        if not aliases:
            continue

        quoted = ", ".join(f"'{alias}'" for alias in aliases)

        parts.append(f"{target} (looked for {quoted})")

    if not parts:
        return ""

    return (
        "This profile could not find "
        + "; ".join(parts)
        + ". The file has: "
        + ", ".join(f"'{column}'" for column in sorted(columns))
        + ". Fix the column mapping on the Import Profile."
    )


def time_column_hint(
    normalized: dict[str, Any],
    mapping: dict[str, Any],
    config: AttendanceImportConfig,
) -> str:
    """Kolom waktu mana yang dicari profile tapi tidak ada di file."""
    columns = _columns_of(normalized)

    if not columns:
        return ""

    def present(target: str) -> bool:
        return _alias_present(columns, mapping, target)

    if config.row_mode == ROW_MODE_DAILY_IN_OUT:
        missing = [] if present("attendance_date") else ["attendance_date"]

        if not (present("check_in") or present("check_out")):
            missing += ["check_in", "check_out"]
    else:
        # Profil tap mentah boleh memakai satu kolom waktu **atau**
        # pasangan tanggal + jam; salah satunya ada berarti tidak ada
        # yang hilang.
        if present("log_time") or present("attendance_date"):
            return ""

        missing = ["log_time"]

    if not missing:
        return ""

    return _not_found_message(
        columns=columns,
        mapping=mapping,
        targets=missing,
    )


def identifier_column_hint(
    normalized: dict[str, Any],
    mapping: dict[str, Any],
    config: AttendanceImportConfig,
) -> str:
    columns = _columns_of(normalized)

    if not columns:
        return ""

    if config.identifier.column:
        if config.identifier.column.strip().lower() in columns:
            return ""

        return (
            f"This profile reads the machine ID from column "
            f"'{config.identifier.column}', which the file does not "
            f"have. The file has: "
            + ", ".join(f"'{column}'" for column in sorted(columns))
            + "."
        )

    if _alias_present(columns, mapping, "employee_code"):
        return ""

    return _not_found_message(
        columns=columns,
        mapping=mapping,
        targets=["employee_code"],
    )


# ----------------------------------------------------------------------
# Cakupan organisasi
# ----------------------------------------------------------------------


def in_organization_scope(
    employee: Employee,
    user,
    cache: dict[int, bool],
) -> bool:
    """
    Pegawai ini boleh disentuh oleh pengunggah file?

    CSV tidak boleh jadi pintu belakang: orang yang cakupannya satu site
    tidak boleh menulis presensi pegawai site lain hanya dengan menaruh
    nomornya di file. Yang menjawab tetap `DataScopeService` — mesin
    yang sama dengan yang menyaring layar daftarnya.
    """
    if employee is None:
        return False

    if employee.pk in cache:
        return cache[employee.pk]

    # Cakupannya ditanyakan **per izin**, sama dengan layar daftarnya.
    #
    # Tanpa `permission`, `for_user()` menjawab dengan cakupan gabungan
    # seluruh role pemegang akun — jadi satu role tak berbatas yang
    # tidak ada hubungannya dengan kepegawaian membuat `unrestricted`
    # menyala, dan seluruh pemeriksaan di bawahnya dilewati. Pintu
    # belakang yang ditutup fungsi ini justru terbuka lewat role lain.
    permission = view_permission_for(Employee)

    scope = DataScopeService.for_user(user, permission=permission)

    if scope.unrestricted:
        allowed = True
    elif scope.denied:
        allowed = False
    else:
        allowed = (
            DataScopeService.filter(
                Employee.objects.filter(pk=employee.pk),
                EMPLOYEE_SCOPE,
                user,
                required_permission=permission,
            )
            .exists()
        )

    cache[employee.pk] = allowed

    return allowed


def organization_of(
    employee: Employee,
    cache: dict[int, OrganizationAssignment | None],
) -> OrganizationAssignment | None:
    if employee.pk in cache:
        return cache[employee.pk]

    assignment = (
        OrganizationAssignment.objects
        .filter(
            employee=employee,
            is_active=True,
            is_deleted=False,
        )
        .select_related(
            "company",
            "branch",
            "location",
        )
        .order_by(
            "-organization_effective_date",
            "-id",
        )
        .first()
    )

    cache[employee.pk] = assignment

    return assignment


# ----------------------------------------------------------------------
# Normalisasi satu baris
# ----------------------------------------------------------------------


def _daily_moment(
    raw_row: dict[str, Any],
    normalized: dict[str, Any],
    config: AttendanceImportConfig,
) -> tuple[str, datetime | None, str, bool]:
    """`(teks asli, datetime, event, terbaca)` untuk satu slot harian."""
    slot = str(raw_row.get(SLOT_KEY) or "")

    raw_date = ImportNormalizer.clean_text(
        normalized.get("attendance_date"),
    )

    raw_clock = ImportNormalizer.clean_text(raw_row.get(SLOT_TIME_KEY))

    raw_timestamp = " ".join(part for part in (raw_date, raw_clock) if part)

    day = parse_day(normalized.get("attendance_date"), config)

    clock = parse_clock(raw_row.get(SLOT_TIME_KEY), config)

    if not slot or day is None or clock is None:
        # Pesannya menyebut kolom yang benar-benar gagal. "Timestamp
        # tidak terbaca" pada file yang memang tidak punya kolom
        # timestamp mengirim orang mencari masalah di tempat yang salah
        # — itu yang terjadi pada percobaan pertama mode ini.
        missing = []

        if day is None:
            missing.append(f"work date '{raw_date}'")

        if clock is None:
            missing.append(f"time '{raw_clock}'")

        normalized["_daily_error"] = (
            "Could not read "
            + " and ".join(missing or ["the daily in/out columns"])
            + " with this profile's date and time formats."
        )

        return raw_timestamp, None, EVENT_UNKNOWN, True

    moment = datetime.combine(day, clock).replace(tzinfo=config.timezone)

    return raw_timestamp, moment, slot, True


def normalize_row(
    raw_row: dict[str, Any],
    *,
    mapping: dict[str, Any],
    defaults: dict[str, Any] | None,
    value_mapping: dict[str, Any] | None,
    config: AttendanceImportConfig,
) -> dict[str, Any]:
    normalized: dict[str, Any] = {
        "_row_number": raw_row.get("_row_number"),
        "_source_type": raw_row.get("_source_type"),
        "raw_payload": {
            key: value
            for key, value in raw_row.items()
            if not str(key).startswith("_")
        },
    }

    for target, aliases in mapping.items():
        normalized[target] = ImportNormalizer.pick(raw_row, aliases)

    # Kolom identifier boleh ditunjuk langsung lewat
    # `options.attendance.identifier.column`. Itu jalan pintas untuk
    # profile yang ditulis tangan; jalur kanonisnya tetap `mapping`.
    if config.identifier.column:
        picked = ImportNormalizer.pick(
            raw_row,
            [config.identifier.column.strip().lower()],
        )

        if picked not in (None, ""):
            normalized["employee_code"] = picked

    for key, value in (defaults or {}).items():
        if normalized.get(key) in (None, ""):
            normalized[key] = value

    for target, table in (value_mapping or {}).items():
        if not isinstance(table, dict):
            continue

        normalized[target] = ImportNormalizer.translate(
            normalized.get(target),
            table,
        )

    raw_identifier = ImportNormalizer.clean_text(
        normalized.get("employee_code"),
    )

    normalized["raw_employee_id"] = raw_identifier
    normalized["employee_code"] = raw_identifier

    normalized["employee_name"] = ImportNormalizer.clean_text(
        normalized.get("employee_name"),
    )

    normalized["device_code"] = (
        config.device_code
        or ImportNormalizer.clean_text(normalized.get("device_code"))
    )

    normalized["external_id"] = ImportNormalizer.clean_text(
        normalized.get("external_id"),
    )

    # ------------------------------------------------------------------
    # Waktu
    # ------------------------------------------------------------------

    if config.row_mode == ROW_MODE_DAILY_IN_OUT:
        # Baris sudah dimekarkan `expand_daily_row()`: slot dan jamnya
        # menempel di baris ini, jadi di sini tinggal merakit waktunya.
        # Kolom `log_time` sengaja **tidak** dilihat sama sekali —
        # profile harian memang tidak punya kolom itu, dan menuntutnya
        # adalah persis kegagalan yang membuat mode ini dibuat.
        raw_timestamp, moment, event, event_ok = _daily_moment(
            raw_row,
            normalized,
            config,
        )

        normalized["_incomplete_day"] = bool(
            raw_row.get(SLOT_INCOMPLETE_KEY),
        )

        normalized["_incomplete_reason"] = str(
            raw_row.get(SLOT_REASON_KEY) or "",
        )

    else:
        raw_timestamp = normalized.get("log_time")

        moment = parse_moment(raw_timestamp, config)

        event, event_ok = resolve_event(normalized.get("log_type"), config)

        if moment is None:
            # Bentuk lama yang tetap didukung: profile tap mentah yang
            # filenya ternyata berisi tanggal + satu jam. Cuma satu
            # event yang lahir — yang butuh dua memakai
            # `row_mode = daily_in_out`.
            day = parse_day(normalized.get("attendance_date"), config)

            check_in = parse_clock(normalized.get("check_in"), config)
            check_out = parse_clock(normalized.get("check_out"), config)

            if day is not None and check_in is not None:
                moment = datetime.combine(day, check_in).replace(
                    tzinfo=config.timezone,
                )

                raw_timestamp = f"{day.isoformat()} {check_in}"

                if config.event_mode != EVENT_MODE_RAW_TAP:
                    event, event_ok = "in", True

            elif day is not None and check_out is not None:
                moment = datetime.combine(day, check_out).replace(
                    tzinfo=config.timezone,
                )

                raw_timestamp = f"{day.isoformat()} {check_out}"

                if config.event_mode != EVENT_MODE_RAW_TAP:
                    event, event_ok = "out", True

    normalized["raw_timestamp"] = (
        raw_timestamp
        if isinstance(raw_timestamp, str)
        else ImportNormalizer.clean_text(raw_timestamp)
    )

    normalized["log_time"] = moment
    normalized["log_type"] = event
    normalized["_event_recognized"] = event_ok

    return normalized


# ----------------------------------------------------------------------
# Resolusi satu baris
# ----------------------------------------------------------------------


def resolve_row(
    normalized: dict[str, Any],
    *,
    config: AttendanceImportConfig,
    profile_code: str,
    mapping: dict[str, Any] | None = None,
    user=None,
    caches: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, list[str]]]:
    caches = caches if caches is not None else {}

    mapping = mapping or {}

    device_cache = caches.setdefault("device", {})
    scope_cache = caches.setdefault("scope", {})
    organization_cache = caches.setdefault("organization", {})
    seen_fingerprints = caches.setdefault("fingerprints", set())
    known_fingerprints = caches.setdefault("known_fingerprints", {})

    resolved: dict[str, Any] = {"status": statuses.VALID}
    errors: dict[str, list[str]] = {}

    def fail(status: str, field_name: str, message: str):
        resolved["status"] = status
        resolved["message"] = message

        errors.setdefault(field_name, []).append(message)

        return resolved, errors

    raw_identifier = normalized.get("raw_employee_id") or ""

    # ------------------------------------------------------------------
    # Device
    # ------------------------------------------------------------------

    device_code = normalized.get("device_code") or ""

    device = resolve_device(
        device_code=device_code,
        cache=device_cache,
    )

    resolved["device"] = device

    if device is None and device_code and (
        config.require_device
        or config.device_code
    ):
        return fail(
            statuses.UNKNOWN_DEVICE,
            "device_code",
            f"Attendance device '{device_code}' is not registered "
            f"or not active.",
        )

    if device is None and config.require_device:
        return fail(
            statuses.UNKNOWN_DEVICE,
            "device_code",
            "This import profile requires an attendance device, but "
            "none was resolved from the profile or the file.",
        )

    # ------------------------------------------------------------------
    # Waktu & event
    # ------------------------------------------------------------------

    moment: datetime | None = normalized.get("log_time")

    if not raw_identifier:
        return fail(
            statuses.UNKNOWN_EMPLOYEE,
            "employee_code",
            identifier_column_hint(normalized, mapping, config)
            or "Row does not contain a machine employee identifier.",
        )

    if moment is None:
        return fail(
            statuses.INVALID_DATETIME,
            "log_time",
            # Urutannya menentukan seberapa cepat orang menemukan
            # sebabnya: kolom yang **tidak ada** dilaporkan lebih dulu,
            # karena itu sebab yang paling sering dan paling mudah
            # tertukar dengan salah format.
            time_column_hint(normalized, mapping, config)
            or normalized.get("_daily_error")
            or (
                f"Timestamp '{normalized.get('raw_timestamp')}' could "
                f"not be read with this profile's datetime formats."
            ),
        )

    if not normalized.get("_event_recognized", True):
        return fail(
            statuses.INVALID_EVENT,
            "log_type",
            "This profile expects an explicit IN/OUT value, but the "
            "row's event column could not be mapped.",
        )

    # ------------------------------------------------------------------
    # Pegawai
    # ------------------------------------------------------------------

    match = resolve_employee(
        raw_identifier=raw_identifier,
        device=device,
        config=config.identifier,
        caches=caches,
    )

    employee = match.employee

    if employee is None:
        if device is not None:
            return fail(
                statuses.UNKNOWN_DEVICE_EMPLOYEE,
                "employee_code",
                f"Machine ID '{raw_identifier}' is not mapped to an "
                f"employee on device '{device.code}'.",
            )

        return fail(
            statuses.UNKNOWN_EMPLOYEE,
            "employee_code",
            f"Machine ID '{raw_identifier}' does not match any "
            f"employee.",
        )

    # ------------------------------------------------------------------
    # Cakupan organisasi — sebelum identitas pegawai dibuka
    # ------------------------------------------------------------------
    #
    # Pemeriksaannya di sini, bukan sesudah preview disusun: baris di
    # luar cakupan tidak boleh membocorkan nama dan nomor pegawainya ke
    # layar orang yang tidak berhak melihatnya. Yang ditampilkan cuma
    # nomor mesin yang memang ada di file yang ia unggah sendiri.

    if not in_organization_scope(employee, user, scope_cache):
        return fail(
            statuses.OUTSIDE_ORGANIZATION_SCOPE,
            "employee_code",
            f"Machine ID '{raw_identifier}' belongs to an employee "
            f"outside your organization scope.",
        )

    resolved["employee"] = employee
    resolved["match_source"] = match.source
    resolved["matched_value"] = match.matched_value

    # ------------------------------------------------------------------
    # Feature Applicability
    # ------------------------------------------------------------------

    if not is_applicable(employee, HRFeature.ATTENDANCE):
        return fail(
            statuses.NOT_APPLICABLE,
            "employee_code",
            f"Attendance is not applicable for "
            f"{employee.employee_number} (Employee Group).",
        )

    assignment = organization_of(employee, organization_cache)

    if assignment is None or assignment.company_id is None:
        return fail(
            statuses.NO_ORGANIZATION,
            "employee_code",
            f"{employee.employee_number} has no active organization "
            f"assignment, so attendance cannot be recorded.",
        )

    resolved["organization"] = assignment

    # ------------------------------------------------------------------
    # Hari kerja & jadwal
    # ------------------------------------------------------------------

    schedule: ScheduleResolution = workdate_module.resolve(
        employee=employee,
        moment=moment,
        grace_before_minutes=config.grace_before_minutes,
        grace_after_minutes=config.grace_after_minutes,
        caches=caches,
    )

    resolved["schedule"] = schedule
    resolved["work_date"] = schedule.work_date

    # ------------------------------------------------------------------
    # Duplikat
    # ------------------------------------------------------------------

    fingerprint = build_fingerprint(
        profile_code=profile_code,
        device_code=device_code,
        raw_identifier=raw_identifier,
        moment=moment,
        event=normalized.get("log_type") or "",
    )

    normalized["_fingerprint"] = fingerprint

    normalized["_fingerprint_source"] = fingerprint_payload(
        profile_code=profile_code,
        device_code=device_code,
        raw_identifier=raw_identifier,
        moment=moment,
        event=normalized.get("log_type") or "",
    )

    resolved["fingerprint"] = fingerprint

    if fingerprint in seen_fingerprints:
        resolved["status"] = statuses.DUPLICATE
        resolved["message"] = (
            "Duplicate of an earlier row in this same file."
        )

        normalized["_duplicate"] = True

        return resolved, errors

    if fingerprint not in known_fingerprints:
        known_fingerprints[fingerprint] = (
            AttendanceLog.objects
            .filter(
                source=LOG_SOURCE,
                external_id=fingerprint,
            )
            .exists()
        )

    if known_fingerprints[fingerprint]:
        resolved["status"] = statuses.DUPLICATE
        resolved["message"] = (
            "This tap has already been imported."
        )

        normalized["_duplicate"] = True

        return resolved, errors

    seen_fingerprints.add(fingerprint)

    # ------------------------------------------------------------------
    # Peringatan yang tidak menghalangi
    # ------------------------------------------------------------------

    if not schedule.has_schedule:
        resolved["status"] = (
            statuses.NO_ROSTER_SHIFT
            if schedule.roster_based
            else statuses.NO_SCHEDULE
        )

        resolved["message"] = (
            "No roster segment or shift covers this tap; it is "
            "imported without a scheduled window."
            if schedule.roster_based
            else "No work schedule covers this tap; it is imported "
                 "without a scheduled window."
        )

    # Hari harian yang cuma membawa satu sisi. Tetap masuk — tapi harus
    # terlihat, supaya "pulangnya belum tercatat" tidak terbaca sebagai
    # "pulang tepat waktu". Tidak menimpa status jadwal yang hilang;
    # yang itu lebih menentukan, jadi alasannya cuma ditempelkan.
    if normalized.get("_incomplete_day"):
        note = normalized.get("_incomplete_reason") or (
            "Row does not contain a complete in/out pair."
        )

        if resolved["status"] == statuses.VALID:
            resolved["status"] = statuses.INCOMPLETE_DAY
            resolved["message"] = note
        else:
            resolved["message"] = (
                f"{resolved.get('message', '')} {note}".strip()
            )

    # Nama dari mesin dipakai sebagai alarm, bukan gerbang — aturan yang
    # sama dengan jalur agent on-premise. Nomor yang salah enroll akan
    # menempel ke orang lain tanpa suara kalau tidak dicatat, tapi
    # absensi tidak boleh hilang gara-gara ejaan nama.
    device_name = normalized.get("employee_name") or ""

    if device_name and not AttendanceEmployeeMatcher.names_match(
        device_name,
        employee,
    ):
        resolved["name_warning"] = (
            f"Machine registered this ID as '{device_name}', but "
            f"{employee.employee_number} is "
            f"{AttendanceEmployeeMatcher.employee_name(employee)} in "
            f"the master data."
        )

    return resolved, errors
