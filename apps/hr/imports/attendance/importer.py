"""
Import Attendance di atas pipeline import generik.

**Satu mesin untuk semua**. Head Office dan site tidak punya importer
sendiri-sendiri; yang berbeda cuma `ImportProfile`-nya — pemisah kolom,
nama kolom, format waktu, zona waktu, dan apakah filenya membawa IN/OUT
atau cuma tap mentah. Menambah klien dengan merek mesin baru berarti
menambah satu baris profile, bukan satu cabang `if` di kode.

Yang **tidak** ditentukan profile: jam kerja, shift, hari libur, dan
siapa yang dijadwalkan. Semua itu dijawab resolver jadwal HR yang sama
yang dipakai penutup hari dan laporan — lihat `workdate.py`.

Jalur lama (`/api/hr/attendance/import/...`, `AttendanceImportService`)
sengaja dibiarkan hidup dan **tidak** ikut berubah; ia memakai
`AttendanceImportNormalizer` apa adanya.
"""

from __future__ import annotations

from typing import Any

from apps.framework.imports import (
    BaseImporter,
    ImportNormalizer,
    register_importer,
)
from apps.hr.imports.services.attendance import AttendanceImportWriter
from apps.hr.imports.services.normalizer import AttendanceImportNormalizer
from apps.hr.models import AttendanceLog, AttendanceLogType

from . import resolver, statuses
from .config import (
    EVENT_MODE_LABELS,
    EVENT_MODE_RAW_TAP,
    ROW_MODE_DAILY_IN_OUT,
    ROW_MODE_LABELS,
    AttendanceImportConfig,
)


def _config_of(context: dict[str, Any] | None) -> AttendanceImportConfig:
    """
    Konfigurasi profile, dihitung sekali per file.

    Disimpan di `context["state"]`, bukan di class: dua job Celery di
    worker yang sama memakai profile berbeda, dan state di class
    membuat yang kedua diam-diam memakai konfigurasi yang pertama.
    """
    context = context if context is not None else {}

    state = context.setdefault("state", {})

    if "config" not in state:
        profile = context.get("profile")

        state["config"] = AttendanceImportConfig.from_options(
            context.get("options"),
            datetime_formats=getattr(profile, "datetime_formats", None),
        )

    return state["config"]


def _caches(context: dict[str, Any] | None) -> dict[str, Any]:
    context = context if context is not None else {}

    return context.setdefault("state", {}).setdefault("caches", {})


def _mapping_of(context: dict[str, Any] | None) -> dict[str, list[str]]:
    """
    Mapping efektif profile, dihitung sekali per file.

    `expand_row()` membutuhkannya — ia berjalan **sebelum**
    `normalize()`, jadi tidak bisa menunggu mapping dioper lewat
    argumen seperti hook lain.
    """
    context = context if context is not None else {}

    state = context.setdefault("state", {})

    if "mapping" not in state:
        state["mapping"] = AttendanceImporter.get_mapping(
            context.get("mapping"),
        )

    return state["mapping"]


def _profile_code(context: dict[str, Any] | None) -> str:
    context = context if context is not None else {}

    profile = context.get("profile")

    return str(getattr(profile, "code", "") or "")


@register_importer
class AttendanceImporter(BaseImporter):
    module = "hr/attendance"
    label = "Attendance"

    source_types = ("csv",)

    context_aware = True

    # Alias bawaan tetap milik `AttendanceImportNormalizer` supaya jalur
    # import lama dan jalur ini memakai definisi yang sama. Profile yang
    # header filenya lain cukup menimpanya lewat `mapping`.
    mapping = AttendanceImportNormalizer.DEFAULT_MAPPING

    # `required_fields` sengaja kosong: `validate()` di bawah tidak
    # memakainya, dan hampir semua keadaan yang membuat baris absensi
    # tidak bisa masuk baru ketahuan sesudah pegawainya dicari.
    identity_field = "raw_employee_id"

    preview_columns = (
        {"key": "row_number", "label": "Row"},
        {"key": "raw_employee_id", "label": "Raw Employee ID"},
        {"key": "employee_code", "label": "Employee Number"},
        {"key": "employee_name", "label": "Employee Name"},
        {"key": "raw_timestamp", "label": "Raw Timestamp"},
        {"key": "log_time", "label": "Normalized Timestamp"},
        {"key": "work_date", "label": "Work Date"},
        {"key": "schedule_label", "label": "Schedule / Shift"},
        {"key": "log_type", "label": "Event"},
        {"key": "device_code", "label": "Device"},
        {"key": "status_label", "label": "Status"},
        {"key": "message", "label": "Message"},
    )

    template_columns = (
        "employee_code",
        "log_time",
        "log_type",
        "device_code",
    )

    template_sample_rows = (
        {
            "employee_code": "1001",
            "log_time": "2026-01-15 08:01:00",
            "log_type": "in",
            "device_code": "ATTENDANCE-01",
        },
        {
            "employee_code": "1001",
            "log_time": "2026-01-15 17:05:00",
            "log_type": "out",
            "device_code": "ATTENDANCE-01",
        },
    )

    # ------------------------------------------------------------------
    # Penjelasan profile untuk layar import
    # ------------------------------------------------------------------

    @classmethod
    def describe_profile(cls, profile) -> dict[str, Any]:
        described = super().describe_profile(profile)

        config = AttendanceImportConfig.from_options(
            getattr(profile, "options", None),
            datetime_formats=getattr(profile, "datetime_formats", None),
        )

        merged = cls.get_mapping(getattr(profile, "mapping", None) or None)

        def first_alias(target: str) -> str:
            aliases = merged.get(target) or []

            return aliases[0] if aliases else ""

        employee_column = (
            config.identifier.column
            or first_alias("employee_code")
        )

        summary = described["summary"]

        summary.append({
            "label": "Employee ID Column",
            "value": employee_column or "—",
        })

        summary.append({
            "label": "Row Mode",
            "value": ROW_MODE_LABELS.get(config.row_mode, config.row_mode),
        })

        if config.row_mode == ROW_MODE_DAILY_IN_OUT:
            # Profile harian **tidak** punya kolom timestamp, dan
            # menyebutkannya di layar adalah cara paling cepat membuat
            # orang mengira filenya yang salah.
            summary.append({
                "label": "Work Date Column",
                "value": first_alias("attendance_date") or "—",
            })

            summary.append({
                "label": "Check In Column",
                "value": first_alias("check_in") or "—",
            })

            summary.append({
                "label": "Check Out Column",
                "value": first_alias("check_out") or "—",
            })

            summary.append({
                "label": "Date Format",
                "value": ", ".join(config.date_formats) or "common formats",
            })

            summary.append({
                "label": "Time Format",
                "value": ", ".join(config.time_formats) or "HH:MM / HH:MM:SS",
            })
        else:
            summary.append({
                "label": "Timestamp Column",
                "value": first_alias("log_time") or "—",
            })

            summary.append({
                "label": "Datetime Format",
                "value": (
                    ", ".join(config.datetime_formats)
                    or "ISO / common formats"
                ),
            })

        summary.append({
            "label": "Source Timezone",
            "value": config.timezone_name,
        })

        if config.row_mode != ROW_MODE_DAILY_IN_OUT:
            # Pada mode harian jenis event ditentukan kolomnya sendiri
            # (jam masuk -> IN, jam pulang -> OUT), jadi `event_mode`
            # tidak berlaku dan menampilkannya cuma menyesatkan.
            summary.append({
                "label": "Event Mode",
                "value": EVENT_MODE_LABELS.get(
                    config.event_mode,
                    config.event_mode,
                ),
            })

        if config.device_code:
            summary.append({
                "label": "Attendance Device",
                "value": config.device_code,
            })

        described["columns"] = [
            {"target": target, "aliases": aliases}
            for target, aliases in merged.items()
            if aliases
        ]

        notes = described["notes"]

        notes.append(
            "Machine IDs are resolved through Attendance Device "
            "Employee Mapping first; employees are never created by "
            "an import.",
        )

        notes.append(
            "Work date, scheduled hours, and shift come from the HR "
            "schedule resolver — never from this profile.",
        )

        if config.row_mode == ROW_MODE_DAILY_IN_OUT:
            notes.append(
                "Each file row is one work date and produces up to two "
                "taps. A row with only one of the two times is imported "
                "and flagged Incomplete Day — the missing side is never "
                "invented.",
            )

        elif config.event_mode == EVENT_MODE_RAW_TAP:
            notes.append(
                "This profile treats every row as a raw tap; first and "
                "last tap of a work date become check in and check out.",
            )

        return described

    # ------------------------------------------------------------------
    # Pemekaran baris
    # ------------------------------------------------------------------

    @classmethod
    def expand_row(
        cls,
        raw_row: dict[str, Any],
        *,
        context: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        config = _config_of(context)

        if config.row_mode != ROW_MODE_DAILY_IN_OUT:
            return [raw_row]

        return resolver.expand_daily_row(
            raw_row,
            mapping=_mapping_of(context),
            config=config,
        )

    # ------------------------------------------------------------------
    # Normalisasi
    # ------------------------------------------------------------------

    @classmethod
    def normalize(
        cls,
        raw_row: dict[str, Any],
        *,
        mapping: dict[str, Any] | None = None,
        defaults: dict[str, Any] | None = None,
        value_mapping: dict[str, Any] | None = None,
        date_formats: Any = None,
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        config = _config_of(context)

        return resolver.normalize_row(
            raw_row,
            mapping=cls.get_mapping(mapping),
            defaults=defaults,
            value_mapping=value_mapping,
            config=config,
        )

    # ------------------------------------------------------------------
    # Validasi
    # ------------------------------------------------------------------

    @classmethod
    def validate(
        cls,
        normalized: dict[str, Any],
        *,
        context: dict[str, Any] | None = None,
    ) -> dict[str, list[str]]:
        # Validasi baris dan resolusi relasi tidak dipisah di sini
        # dengan sengaja: hampir semua keadaan yang membuat baris
        # absensi tidak bisa masuk (nomor tak terpetakan, di luar
        # cakupan, tidak berlaku) baru ketahuan setelah pegawainya
        # dicari. Memecahnya jadi dua tahap cuma membuat setengah
        # statusnya lahir di tempat yang salah.
        return {}

    # ------------------------------------------------------------------
    # Resolusi
    # ------------------------------------------------------------------

    @classmethod
    def resolve(
        cls,
        normalized: dict[str, Any],
        *,
        context: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, list[str]]]:
        context = context if context is not None else {}

        return resolver.resolve_row(
            normalized,
            config=_config_of(context),
            profile_code=_profile_code(context),
            mapping=_mapping_of(context),
            user=context.get("user"),
            caches=_caches(context),
        )

    # ------------------------------------------------------------------
    # Preview
    # ------------------------------------------------------------------

    @classmethod
    def build_preview_row(
        cls,
        *,
        normalized: dict[str, Any],
        resolved: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        employee = resolved.get("employee")
        schedule = resolved.get("schedule")

        status = resolved.get("status") or statuses.VALID

        moment = normalized.get("log_time")

        message = resolved.get("message") or ""

        name_warning = resolved.get("name_warning") or ""

        if name_warning:
            message = (
                f"{message} {name_warning}".strip()
                if message
                else name_warning
            )

        return {
            "raw_employee_id": normalized.get("raw_employee_id") or "",

            # Nama lama dipertahankan supaya layar/laporan yang sudah
            # membacanya tidak kosong mendadak.
            "employee_code": (
                employee.employee_number if employee else ""
            ),
            "employee_id": employee.id if employee else None,
            "employee_name": (
                employee.full_name if employee else ""
            ),

            "raw_timestamp": normalized.get("raw_timestamp") or "",
            "log_time": moment.isoformat() if moment else None,

            "work_date": (
                resolved["work_date"].isoformat()
                if resolved.get("work_date")
                else None
            ),

            "schedule_label": (
                schedule.label if schedule is not None else ""
            ),

            "log_type": normalized.get("log_type") or "",
            "device_code": normalized.get("device_code") or "",

            "match_source": resolved.get("match_source") or "",

            "status": status,
            "status_label": statuses.label(status),
            "message": message,
        }

    # ------------------------------------------------------------------
    # Penulisan
    # ------------------------------------------------------------------

    @classmethod
    def write(
        cls,
        *,
        normalized: dict[str, Any],
        resolved: dict[str, Any],
        user=None,
        context: dict[str, Any] | None = None,
    ):
        context = context if context is not None else {}

        employee = resolved["employee"]
        assignment = resolved["organization"]
        schedule = resolved.get("schedule")
        device = resolved.get("device")

        moment = normalized["log_time"]

        batch_id = str(
            (context.get("options") or {}).get("import_batch_id")
            or "",
        )[:100]

        # Event mentah disimpan lebih dulu. `AttendanceLog` adalah
        # catatan tap apa adanya; `EmployeeAttendance` adalah
        # kesimpulannya. Menyimpan yang kedua tanpa yang pertama berarti
        # tidak ada jalan pulang saat jadwal seseorang diperbaiki dan
        # harinya perlu dihitung ulang.
        #
        # Unique `(source, external_id)` pada tabel itu yang menjadikan
        # unggahan berulang idempoten di tingkat database, bukan cuma di
        # tingkat pemeriksaan aplikasi.
        AttendanceLog.objects.create(
            employee=employee,
            device=device,
            company=assignment.company,
            branch=assignment.branch,
            location=assignment.location,
            occurred_at=moment,
            log_type=(
                normalized.get("log_type")
                or AttendanceLogType.UNKNOWN
            ),
            source=resolver.LOG_SOURCE,
            employee_identifier=(
                normalized.get("raw_employee_id") or ""
            )[:150],
            external_id=(normalized.get("_fingerprint") or "")[:200],
            raw_payload={
                **(normalized.get("raw_payload") or {}),
                "_fingerprint_source": normalized.get(
                    "_fingerprint_source",
                    "",
                ),
            },
            import_batch_id=batch_id,
            is_processed=True,
        )

        scheduled = None

        if schedule is not None and schedule.has_schedule:
            scheduled = (
                schedule.scheduled_check_in,
                schedule.scheduled_check_out,
            )

        return AttendanceImportWriter.upsert(
            employee=employee,
            normalized={
                **normalized,
                "device_code": normalized.get("device_code") or "",
                "external_id": (
                    normalized.get("external_id")
                    or normalized.get("_fingerprint")
                    or ""
                ),
            },
            user=user,
            work_date=(
                resolved.get("work_date")
                or (schedule.work_date if schedule else None)
            ),
            scheduled=scheduled,
        )

    # ------------------------------------------------------------------
    # Util
    # ------------------------------------------------------------------

    @classmethod
    def get_identity(cls, normalized: dict[str, Any]) -> str:
        return ImportNormalizer.clean_text(
            normalized.get("raw_employee_id"),
        )
