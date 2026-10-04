from __future__ import annotations

from typing import Type

from .base import BaseAttendanceParser
from .csv import CSVAttendanceParser


PARSER_REGISTRY: dict[
    str,
    Type[BaseAttendanceParser],
] = {
    "csv": CSVAttendanceParser,
}


def get_parser_class(
    source_type: str,
) -> Type[BaseAttendanceParser]:
    normalized = str(
        source_type or "",
    ).strip().lower()

    try:
        return PARSER_REGISTRY[normalized]
    except KeyError as exc:
        raise ValueError(
            f"Unsupported attendance import type: "
            f"{source_type}"
        ) from exc