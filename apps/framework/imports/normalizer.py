from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from django.utils.dateparse import (
    parse_date,
    parse_datetime,
)


BOOLEAN_TRUE = {
    "1",
    "true",
    "yes",
    "y",
    "ya",
    "on",
    "aktif",
    "active",
}

BOOLEAN_FALSE = {
    "0",
    "false",
    "no",
    "n",
    "tidak",
    "off",
    "nonaktif",
    "inactive",
}

DEFAULT_DATE_FORMATS = (
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
    "%m/%d/%Y",
    "%d %B %Y",
    "%d %b %Y",
    "%Y/%m/%d",
)


class ImportNormalizer:
    """
    Mengubah satu baris mentah hasil parser menjadi dict bertarget
    berdasarkan mapping `target -> alias(es)`.

    Mapping dari ImportProfile menimpa mapping bawaan importer,
    sehingga klien dengan header berbeda cukup mengubah profile
    tanpa menyentuh kode.
    """

    @staticmethod
    def clean_text(value: Any) -> str:
        if value is None:
            return ""

        return str(value).strip()

    @classmethod
    def merge_mapping(
        cls,
        *,
        base: dict[str, Any] | None,
        override: dict[str, Any] | None,
    ) -> dict[str, list[str]]:
        merged: dict[str, list[str]] = {}

        for source in (base or {}, override or {}):
            for target, aliases in source.items():
                if isinstance(aliases, str):
                    normalized_aliases = [aliases]
                elif isinstance(aliases, Iterable):
                    normalized_aliases = [
                        str(alias)
                        for alias in aliases
                    ]
                else:
                    continue

                merged[str(target)] = [
                    alias.strip().lower()
                    for alias in normalized_aliases
                    if str(alias).strip()
                ]

        return merged

    @classmethod
    def pick(
        cls,
        raw_row: dict[str, Any],
        aliases: list[str],
    ) -> Any:
        for alias in aliases:
            if alias in raw_row:
                value = raw_row[alias]

                if value is None:
                    continue

                if isinstance(value, str) and not value.strip():
                    continue

                return value

        return None

    @classmethod
    def translate(
        cls,
        value: Any,
        table: dict[str, Any] | None,
    ) -> Any:
        """
        Terjemahkan nilai file menjadi nilai sistem lewat satu tabel
        `{nilai_file: nilai_sistem}`. Pencocokan case-insensitive supaya
        'TK/0' dan 'tk/0' diperlakukan sama.
        """
        if not table:
            return value

        text = cls.clean_text(value)

        if not text:
            return value

        lowered = {
            str(key).strip().lower(): mapped
            for key, mapped in table.items()
        }

        return lowered.get(text.lower(), value)

    @classmethod
    def normalize(
        cls,
        raw_row: dict[str, Any],
        *,
        mapping: dict[str, Any] | None = None,
        defaults: dict[str, Any] | None = None,
        value_mapping: dict[str, Any] | None = None,
        date_fields: Iterable[str] | None = None,
        date_formats: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        resolved_mapping = cls.merge_mapping(
            base=mapping,
            override=None,
        )

        normalized: dict[str, Any] = {}

        for target, aliases in resolved_mapping.items():
            normalized[target] = cls.pick(
                raw_row,
                aliases,
            )

        for key, value in (defaults or {}).items():
            if normalized.get(key) in (None, ""):
                normalized[key] = value

        for target, table in (value_mapping or {}).items():
            if not isinstance(table, dict):
                continue

            normalized[target] = cls.translate(
                normalized.get(target),
                table,
            )

        # Tanggal diseragamkan ke ISO di sini supaya format khas satu
        # klien (mis. M/D/YYYY) cukup diatur lewat `datetime_formats`
        # pada ImportProfile, dan tahap berikutnya tidak perlu menebak.
        # Nilai yang gagal diparse dibiarkan apa adanya agar tetap
        # dilaporkan sebagai error oleh validate().
        for target in (date_fields or ()):
            raw_value = normalized.get(target)

            if raw_value in (None, ""):
                continue

            parsed = cls.to_date(
                raw_value,
                formats=date_formats,
            )

            if parsed is not None:
                normalized[target] = parsed.isoformat()

        normalized["_row_number"] = raw_row.get("_row_number")
        normalized["_source_type"] = raw_row.get("_source_type")

        # Simpan baris asli supaya bisa ditampilkan di laporan error.
        normalized["raw_payload"] = {
            key: value
            for key, value in raw_row.items()
            if not str(key).startswith("_")
        }

        return normalized

    # ------------------------------------------------------------------
    # Konversi nilai
    # ------------------------------------------------------------------

    @classmethod
    def to_text(cls, value: Any) -> str:
        return cls.clean_text(value)

    @classmethod
    def to_boolean(
        cls,
        value: Any,
        *,
        default: bool = False,
    ) -> bool:
        if isinstance(value, bool):
            return value

        text = cls.clean_text(value).lower()

        if text in BOOLEAN_TRUE:
            return True

        if text in BOOLEAN_FALSE:
            return False

        return default

    @classmethod
    def to_integer(cls, value: Any) -> int | None:
        text = cls.clean_text(value).replace(",", "")

        if not text:
            return None

        try:
            return int(float(text))
        except (TypeError, ValueError):
            return None

    @classmethod
    def to_decimal(cls, value: Any) -> Decimal | None:
        text = cls.clean_text(value)

        if not text:
            return None

        # Dukung format Indonesia: 1.234,56
        if "," in text and "." in text:
            text = text.replace(".", "").replace(",", ".")
        elif "," in text:
            text = text.replace(",", ".")

        try:
            return Decimal(text)
        except (InvalidOperation, TypeError, ValueError):
            return None

    @classmethod
    def to_date(
        cls,
        value: Any,
        *,
        formats: Iterable[str] | None = None,
    ) -> date | None:
        if isinstance(value, datetime):
            return value.date()

        if isinstance(value, date):
            return value

        text = cls.clean_text(value)

        if not text:
            return None

        # `parse_date`/`parse_datetime` melempar ValueError untuk teks
        # yang **bentuknya** benar tapi tanggalnya mustahil —
        # "2026-13-45", "31/04/2026". Tanpa ditangkap, satu sel salah
        # ketik di tengah file menjatuhkan seluruh preview jadi 500,
        # dan pesannya ("month must be in 1..12") tidak menyebut baris
        # maupun kolomnya. Yang benar: nilainya dianggap tidak terbaca,
        # lalu importer melaporkannya sebagai error baris — di sana
        # nomor barisnya ikut.
        for parser in (parse_date, parse_datetime):
            try:
                parsed = parser(text)
            except ValueError:
                return None

            if parsed is not None:
                return (
                    parsed.date()
                    if isinstance(parsed, datetime)
                    else parsed
                )

        for date_format in (
            *(formats or ()),
            *DEFAULT_DATE_FORMATS,
        ):
            try:
                return datetime.strptime(
                    text,
                    date_format,
                ).date()
            except (TypeError, ValueError):
                continue

        return None
