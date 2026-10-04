from __future__ import annotations

from typing import Type

from .base import BaseImportParser
from .csv import CSVImportParser


PARSER_REGISTRY: dict[
    str,
    Type[BaseImportParser],
] = {
    "csv": CSVImportParser,
}


def register_parser(
    parser_class: Type[BaseImportParser],
) -> Type[BaseImportParser]:
    source_type = str(
        getattr(
            parser_class,
            "source_type",
            "",
        )
        or "",
    ).strip().lower()

    if not source_type:
        raise ValueError(
            f"{parser_class.__name__} harus menentukan "
            f"atribut 'source_type'."
        )

    PARSER_REGISTRY[source_type] = parser_class

    return parser_class


def get_parser_class(
    source_type: str,
) -> Type[BaseImportParser]:
    normalized = str(
        source_type or "",
    ).strip().lower()

    try:
        return PARSER_REGISTRY[normalized]
    except KeyError as exc:
        raise ValueError(
            f"Unsupported import source type: {source_type}"
        ) from exc


def supported_source_types() -> list[str]:
    return sorted(PARSER_REGISTRY)
