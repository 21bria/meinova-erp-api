from __future__ import annotations

from django.utils import timezone
from datetime import (
    date,
    datetime,
    time,
)
from typing import Any

from django.utils.dateparse import (
    parse_date,
    parse_datetime,
)


class AttendanceImportNormalizer:
    DEFAULT_MAPPING = {
        # ----------------------------------------------------------
        # Employee
        # ----------------------------------------------------------
        "employee_code": [
            "employee_code",
            "employee_number",
            "employee_id",
            "userid",
            "user_id",
            "pin",
            "enroll_number",
            "no",
        ],

        "employee_name": [
            "employee_name",
            "name",
            "full_name",
        ],

        "department": [
            "department",
            "depart",
            "dept",
        ],

        # ----------------------------------------------------------
        # Single Log
        # ----------------------------------------------------------
        "log_time": [
            "log_time",
            "check_time",
            "checktime",
            "timestamp",
            "datetime",
            "date_time",
            "ymdhm",
        ],

        "log_type": [
            "log_type",
            "check_type",
            "checktype",
            "type",
            "status",
            "inout",
        ],

        # ----------------------------------------------------------
        # Summary
        # ----------------------------------------------------------
        "attendance_date": [
            "attendance_date",
            "work_date",
            "date",
            "ymd",
        ],

        "check_in": [
            "check_in",
            "time_in",
            "in",
            "work1",
        ],

        "check_out": [
            "check_out",
            "time_out",
            "out",
            "work2",
        ],

        "shift": [
            "shift",
            "shift_code",
            "shift_name",
            "work_shift",
        ],

        # ----------------------------------------------------------
        # Optional
        # ----------------------------------------------------------
        "device_code": [
            "device_code",
            "device",
            "machine_id",
            "serial_number",
            "sn",
            "rid",
        ],

        "external_id": [
            "external_id",
            "record_id",
            "log_id",
            "id",
            "serno",
        ],

        "remark": [
            "remark",
            "remarks",
            "note",
            "notes",
        ],
    }

    @classmethod
    def pick_value(
        cls,
        row: dict[str, Any],
        aliases: list[str],
    ) -> Any:
        for alias in aliases:
            if alias not in row:
                continue

            value = row.get(alias)

            if value not in (
                None,
                "",
            ):
                return value

        return None

    @staticmethod
    def normalize_text(
        value: Any,
    ) -> str:
        return str(
            value or "",
        ).strip()

    
    @staticmethod
    def ensure_aware(
        value: datetime | None,
    ) -> datetime | None:
        if value is None:
            return None

        if timezone.is_naive(
            value,
        ):
            return timezone.make_aware(
                value,
                timezone.get_current_timezone(),
            )

        return value

    
    @classmethod
    def parse_log_time(
        cls,
        value: Any,
    ) -> datetime | None:
        if value in (
            None,
            "",
        ):
            return None

        if isinstance(
            value,
            datetime,
        ):
            return value

        if isinstance(
            value,
            date,
        ):
            return datetime.combine(
                value,
                time.min,
            )

        raw = str(value).strip()

        parsed = parse_datetime(raw)

        if parsed:
            return parsed

        parsed_date = parse_date(raw)

        if parsed_date:
            return datetime.combine(
                parsed_date,
                time.min,
            )

        formats = [
            "%Y%m%d%H%M",
            "%Y%m%d%H%M%S",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %H:%M",
            "%Y/%m/%d %H:%M:%S",
            "%Y/%m/%d %H:%M",
            "%d/%m/%Y %H:%M:%S",
            "%d/%m/%Y %H:%M",
        ]

        for fmt in formats:
            try:
                return datetime.strptime(
                    raw,
                    fmt,
                )
            except ValueError:
                pass

        return None

    @classmethod
    def parse_attendance_date(
        cls,
        value: Any,
    ) -> date | None:
        if value in (
            None,
            "",
        ):
            return None

        if isinstance(
            value,
            datetime,
        ):
            return value.date()

        if isinstance(
            value,
            date,
        ):
            return value

        raw = str(value).strip()

        parsed = parse_date(raw)

        if parsed:
            return parsed

        for fmt in (
            "%Y/%m/%d",
            "%Y-%m-%d",
            "%d/%m/%Y",
            "%d-%m-%Y",
        ):
            try:
                return datetime.strptime(
                    raw,
                    fmt,
                ).date()
            except ValueError:
                pass

        return None

    @classmethod
    def parse_attendance_time(
        cls,
        value: Any,
    ) -> time | None:
        if value in (
            None,
            "",
        ):
            return None

        if isinstance(
            value,
            datetime,
        ):
            return value.time()

        if isinstance(
            value,
            time,
        ):
            return value

        raw = str(value).strip()

        for fmt in (
            "%H:%M:%S",
            "%H:%M",
        ):
            try:
                return datetime.strptime(
                    raw,
                    fmt,
                ).time()
            except ValueError:
                pass

        return None

    @classmethod
    def normalize(
        cls,
        row: dict[str, Any],
        *,
        mapping: dict[
            str,
            list[str] | str,
        ] | None = None,
    ) -> dict[str, Any]:
        active_mapping = {
            **cls.DEFAULT_MAPPING,
            **(
                mapping
                or {}
            ),
        }

        normalized: dict[str, Any] = {
            "_row_number": row.get(
                "_row_number",
            ),
            "_source_type": row.get(
                "_source_type",
            ),
            "raw_payload": {
                key: value
                for key, value in row.items()
                if not key.startswith("_")
            },
        }

        for (
            target,
            aliases,
        ) in active_mapping.items():
            alias_list = (
                aliases
                if isinstance(
                    aliases,
                    list,
                )
                else [aliases]
            )

            normalized[target] = (
                cls.pick_value(
                    row,
                    alias_list,
                )
            )

        normalized["employee_code"] = (
            cls.normalize_text(
                normalized.get(
                    "employee_code",
                )
            ).upper()
        )

        normalized["employee_name"] = (
            cls.normalize_text(
                normalized.get(
                    "employee_name",
                )
            )
        )

        normalized["department"] = (
            cls.normalize_text(
                normalized.get(
                    "department",
                )
            )
        )

        normalized["log_time"] = (
            cls.parse_log_time(
                normalized.get(
                    "log_time",
                )
            )
        )

        normalized["log_type"] = (
            cls.normalize_text(
                normalized.get(
                    "log_type",
                )
                or "unknown"
            ).lower()
        )

        normalized["attendance_date"] = (
            cls.parse_attendance_date(
                normalized.get(
                    "attendance_date",
                )
            )
        )

        normalized["check_in"] = (
            cls.parse_attendance_time(
                normalized.get(
                    "check_in",
                )
            )
        )

        normalized["check_out"] = (
            cls.parse_attendance_time(
                normalized.get(
                    "check_out",
                )
            )
        )

        # Build log_time automatically
        if (
            normalized["log_time"] is None
            and normalized["attendance_date"]
        ):
            if normalized["check_in"]:
                normalized["log_time"] = datetime.combine(
                    normalized["attendance_date"],
                    normalized["check_in"],
                )
                normalized["log_type"] = "in"

            elif normalized["check_out"]:
                normalized["log_time"] = datetime.combine(
                    normalized["attendance_date"],
                    normalized["check_out"],
                )
                normalized["log_type"] = "out"

        normalized["log_time"] = (
            cls.ensure_aware(
                normalized.get(
                    "log_time",
                )
            )
        )
        
        normalized["shift"] = (
            cls.normalize_text(
                normalized.get(
                    "shift",
                )
            )
        )        

        normalized["device_code"] = (
            cls.normalize_text(
                normalized.get(
                    "device_code",
                )
            )
        )

        normalized["external_id"] = (
            cls.normalize_text(
                normalized.get(
                    "external_id",
                )
            )
        )

        normalized["remark"] = (
            cls.normalize_text(
                normalized.get(
                    "remark",
                )
            )
        )

        return normalized