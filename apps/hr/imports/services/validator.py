from __future__ import annotations

from datetime import (
    date,
    datetime,
    time,
)
from typing import Any


class AttendanceImportValidator:
    @classmethod
    def validate_row(
        cls,
        row: dict[str, Any],
    ) -> dict[str, list[str]]:
        errors: dict[str, list[str]] = {}

        employee_code = str(
            row.get(
                "employee_code",
            )
            or "",
        ).strip()

        if not employee_code:
            errors.setdefault(
                "employee_code",
                [],
            ).append(
                "Employee code is required.",
            )

        log_time = row.get(
            "log_time",
        )

        attendance_date = row.get(
            "attendance_date",
        )

        check_in = row.get(
            "check_in",
        )

        check_out = row.get(
            "check_out",
        )

        is_single_log = (
            log_time is not None
        )

        is_summary = (
            attendance_date is not None
            and (
                check_in is not None
                or check_out is not None
            )
        )

        if (
            not is_single_log
            and not is_summary
        ):
            errors.setdefault(
                "attendance",
                [],
            ).append(
                (
                    "Either log time or attendance "
                    "date with check in/check out "
                    "is required."
                ),
            )

        if (
            log_time is not None
            and not isinstance(
                log_time,
                datetime,
            )
        ):
            errors.setdefault(
                "log_time",
                [],
            ).append(
                "Log time must be a valid datetime.",
            )

        if (
            attendance_date is not None
            and not isinstance(
                attendance_date,
                date,
            )
        ):
            errors.setdefault(
                "attendance_date",
                [],
            ).append(
                "Attendance date must be a valid date.",
            )

        if (
            check_in is not None
            and not isinstance(
                check_in,
                time,
            )
        ):
            errors.setdefault(
                "check_in",
                [],
            ).append(
                "Check in must be a valid time.",
            )

        if (
            check_out is not None
            and not isinstance(
                check_out,
                time,
            )
        ):
            errors.setdefault(
                "check_out",
                [],
            ).append(
                "Check out must be a valid time.",
            )

        if (
            check_in is not None
            and check_out is not None
            and check_out < check_in
        ):
            errors.setdefault(
                "check_out",
                [],
            ).append(
                (
                    "Check out cannot be earlier "
                    "than check in."
                ),
            )

        return errors

    @classmethod
    def is_valid(
        cls,
        row: dict[str, Any],
    ) -> bool:
        return not cls.validate_row(
            row,
        )