from __future__ import annotations

import csv
from typing import Any

from .base import BaseAttendanceParser


class CSVAttendanceParser(
    BaseAttendanceParser,
):
    source_type = "csv"

    def parse(self) -> list[dict[str, Any]]:
        self.validate_file()

        encoding = self.options.get(
            "encoding",
            "utf-8-sig",
        )

        delimiter = self.options.get(
            "delimiter",
            ",",
        )

        rows: list[dict[str, Any]] = []

        with self.file_path.open(
            "r",
            encoding=encoding,
            newline="",
        ) as file:
            reader = csv.DictReader(
                file,
                delimiter=delimiter,
            )

            if not reader.fieldnames:
                raise ValueError(
                    "CSV file does not contain a header."
                )

            for row_number, raw in enumerate(
                reader,
                start=2,
            ):
                normalized = {
                    str(key).strip().lower():
                        value.strip()
                        if isinstance(value, str)
                        else value
                    for key, value in raw.items()
                    if key is not None
                }

                normalized["_row_number"] = row_number
                normalized["_source_type"] = self.source_type

                rows.append(normalized)

        return rows