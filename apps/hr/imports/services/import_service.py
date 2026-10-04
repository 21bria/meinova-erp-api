from __future__ import annotations

from pathlib import Path
from typing import Any

from apps.hr.imports.parsers.registry import (
    get_parser_class,
)

from .attendance import AttendanceImportWriter
from .matcher import AttendanceEmployeeMatcher
from .normalizer import AttendanceImportNormalizer
from .validator import AttendanceImportValidator


class AttendanceImportService:
    @classmethod
    def preview(
        cls,
        *,
        source_type: str,
        file_path: str | Path,
        parser_options:
            dict[str, Any] | None = None,
        mapping:
            dict[str, list[str] | str]
            | None = None,
    ) -> dict[str, Any]:
        parser_class = get_parser_class(
            source_type,
        )

        parser = parser_class(
            file_path,
            options=parser_options,
        )

        raw_rows = parser.parse()

        results: list[dict[str, Any]] = []

        valid_count = 0
        invalid_count = 0
        unmatched_count = 0

        for raw_row in raw_rows:
            normalized = (
                AttendanceImportNormalizer
                .normalize(
                    raw_row,
                    mapping=mapping,
                )
            )

            errors = (
                AttendanceImportValidator
                .validate_row(
                    normalized,
                )
            )

            employee = None

            if not errors:
                employee = (
                    AttendanceEmployeeMatcher
                    .find_employee(
                        normalized.get(
                            "employee_code",
                        )
                    )
                )

                if employee is None:
                    errors.setdefault(
                        "employee_code",
                        [],
                    ).append(
                        "Employee not found.",
                    )

                    unmatched_count += 1

            is_valid = not errors

            if is_valid:
                valid_count += 1
            else:
                invalid_count += 1

            results.append({
                "row_number":
                    normalized.get(
                        "_row_number",
                    ),

                "source_type":
                    normalized.get(
                        "_source_type",
                    ),

                "employee_code":
                    normalized.get(
                        "employee_code",
                    ),

                "employee_id":
                    employee.id
                    if employee
                    else None,

                "employee_name":
                    employee.full_name
                    if employee
                    else None,

                "log_time":
                    normalized.get(
                        "log_time",
                    ),

                "log_type":
                    normalized.get(
                        "log_type",
                    ),

                "device_code":
                    normalized.get(
                        "device_code",
                    ),

                "external_id":
                    normalized.get(
                        "external_id",
                    ),

                "valid": is_valid,
                "errors": errors,
                "normalized":
                    normalized,
            })

        return {
            "source_type": source_type,
            "total_rows": len(raw_rows),
            "valid_rows": valid_count,
            "invalid_rows": invalid_count,
            "unmatched_rows":
                unmatched_count,
            "rows": results,
        }

    @classmethod
    def import_file(
        cls,
        *,
        source_type: str,
        file_path: str | Path,
        parser_options:
            dict[str, Any] | None = None,
        mapping:
            dict[str, list[str] | str]
            | None = None,
        user=None,
        skip_invalid: bool = True,
    ) -> dict[str, Any]:
        preview = cls.preview(
            source_type=source_type,
            file_path=file_path,
            parser_options=parser_options,
            mapping=mapping,
        )

        created_count = 0
        updated_count = 0
        duplicate_count = 0
        skipped_count = 0
        failed_count = 0

        imported_rows: list[
            dict[str, Any]
        ] = []

        error_rows: list[
            dict[str, Any]
        ] = []

        for item in preview["rows"]:
            if not item["valid"]:
                skipped_count += 1

                normalized = (
                    item.get(
                        "normalized",
                        {},
                    )
                    or {}
                )

                error_rows.append({
                    "row_number":
                        item.get(
                            "row_number",
                        ),

                    "employee_code":
                        item.get(
                            "employee_code",
                            "",
                        ),

                    "errors":
                        item.get(
                            "errors",
                            {},
                        ),

                    "raw_data":
                        normalized.get(
                            "raw_payload",
                            {},
                        ),
                })

                if skip_invalid:
                    continue

                raise ValueError(
                    f"Invalid attendance row "
                    f"{item.get('row_number')}: "
                    f"{item.get('errors')}"
                )

            employee = (
                AttendanceEmployeeMatcher
                .find_employee(
                    item.get(
                        "employee_code",
                    )
                )
            )

            if employee is None:
                skipped_count += 1

                error_rows.append({
                    "row_number":
                        item.get(
                            "row_number",
                        ),

                    "employee_code":
                        item.get(
                            "employee_code",
                            "",
                        ),

                    "errors": {
                        "employee_code": [
                            "Employee not found.",
                        ],
                    },

                    "raw_data":
                        (
                            item.get(
                                "normalized",
                                {},
                            )
                            or {}
                        ).get(
                            "raw_payload",
                            {},
                        ),
                })

                continue

            try:
                attendance, created = (
                    AttendanceImportWriter
                    .upsert(
                        employee=employee,
                        normalized=
                            item["normalized"],
                        user=user,
                    )
                )
            except Exception as exc:
                failed_count += 1

                error_rows.append({
                    "row_number":
                        item.get(
                            "row_number",
                        ),

                    "employee_code":
                        item.get(
                            "employee_code",
                            "",
                        ),

                    "errors": {
                        "attendance": [
                            str(exc),
                        ],
                    },

                    "raw_data":
                        (
                            item.get(
                                "normalized",
                                {},
                            )
                            or {}
                        ).get(
                            "raw_payload",
                            {},
                        ),
                })

                if skip_invalid:
                    continue

                raise

            if created:
                created_count += 1
            else:
                updated_count += 1

            imported_rows.append({
                "row_number":
                    item.get(
                        "row_number",
                    ),

                "attendance_id":
                    attendance.id,

                "employee_id":
                    employee.id,

                "created":
                    created,

                "duplicate":
                    False,
            })

        return {
            "source_type":
                source_type,

            "total_rows":
                preview["total_rows"],

            "valid_rows":
                preview["valid_rows"],

            "invalid_rows":
                preview["invalid_rows"],

            "created_rows":
                created_count,

            "updated_rows":
                updated_count,

            "duplicate_rows":
                duplicate_count,

            "skipped_rows":
                skipped_count,

            "failed_rows":
                failed_count,

            "error_rows":
                error_rows,

            "rows":
                imported_rows,
        }