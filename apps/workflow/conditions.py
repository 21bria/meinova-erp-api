"""
Penilai `WorkflowStep.condition`.

Sengaja kecil dan bisa divalidasi, bukan ekspresi bebas: alur approval
dikonfigurasi lewat layar setting oleh orang HR, dan sesuatu yang bisa
mengeksekusi kode sembarang di sana adalah lubang keamanan sekaligus
sumber galat yang tidak bisa dijelaskan.

Bentuknya tiga:

    {"field": "total_days", "op": "gte", "value": 5}
    {"all": [ <kondisi>, <kondisi> ]}
    {"any": [ <kondisi>, <kondisi> ]}
    {"not": <kondisi>}

Dinilai terhadap `WorkflowInstance.context` — cuplikan nilai dokumen
yang dibekukan saat pengajuan, bukan dokumen hidupnya. Kalau tidak,
menyunting dokumen di tengah alur bisa membuat step yang sudah
diputuskan jadi "seharusnya tidak pernah ada".
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any

from django.core.exceptions import ValidationError


logger = logging.getLogger(__name__)


OPERATORS = (
    "eq",
    "ne",
    "gt",
    "gte",
    "lt",
    "lte",
    "in",
    "not_in",
    "contains",
    "is_null",
    "is_not_null",
    "is_true",
    "is_false",
)

# Operator yang memang tidak membaca `value` — dipisah supaya validasi
# tidak menuntut kolom yang tidak dipakai.
UNARY_OPERATORS = ("is_null", "is_not_null", "is_true", "is_false")


def _read(context: dict, path: str):
    """Membaca nilai dari konteks, menembus titik (`employee.grade`)."""
    current: Any = context

    for part in str(path).split("."):
        if isinstance(current, dict):
            current = current.get(part)
        else:
            current = getattr(current, part, None)

        if current is None:
            return None

    return current


def _numeric(value):
    """
    Menyamakan angka yang datang sebagai string dari JSON.

    `total_days` disimpan Decimal dan dicuplik ke context sebagai
    string; tanpa penyamaan ini, `"5.0" >= 5` melempar TypeError dan
    seluruh pengajuan gagal karena satu syarat step.
    """
    if isinstance(value, bool):
        return None

    if isinstance(value, (int, float, Decimal)):
        return Decimal(str(value))

    if isinstance(value, str):
        try:
            return Decimal(value.strip())
        except (InvalidOperation, ValueError):
            return None

    return None


def _compare(left, op: str, right) -> bool:
    if op == "is_null":
        return left is None

    if op == "is_not_null":
        return left is not None

    if op == "is_true":
        return bool(left) is True

    if op == "is_false":
        return bool(left) is False

    if op == "in":
        return left in (right or [])

    if op == "not_in":
        return left not in (right or [])

    if op == "contains":
        if left is None:
            return False

        return str(right).lower() in str(left).lower()

    if op == "eq":
        return left == right or (
            _numeric(left) is not None
            and _numeric(left) == _numeric(right)
        )

    if op == "ne":
        return not _compare(left, "eq", right)

    left_number = _numeric(left)
    right_number = _numeric(right)

    if left_number is None or right_number is None:
        # Perbandingan besar-kecil terhadap sesuatu yang bukan angka
        # tidak punya jawaban yang benar. Dilaporkan sebagai tidak
        # terpenuhi, dan dicatat — diam-diam menganggapnya benar akan
        # menambah step yang tidak diminta siapa pun.
        logger.warning(
            "Kondisi workflow membandingkan nilai non-numerik: "
            "%r %s %r",
            left,
            op,
            right,
        )

        return False

    if op == "gt":
        return left_number > right_number

    if op == "gte":
        return left_number >= right_number

    if op == "lt":
        return left_number < right_number

    if op == "lte":
        return left_number <= right_number

    return False


def evaluate(condition: dict | None, context: dict | None) -> bool:
    """
    Apakah syaratnya terpenuhi. Kosong = selalu ya.

    Kondisi yang tidak bisa dinilai (bentuknya salah, operatornya tidak
    dikenal) dianggap **terpenuhi**, bukan gagal: step approval yang
    hilang gara-gara salah ketik konfigurasi jauh lebih berbahaya
    daripada step tambahan yang seharusnya dilewati. Kejadiannya dicatat
    di log.
    """
    if not condition:
        return True

    context = context or {}

    try:
        if "all" in condition:
            return all(
                evaluate(child, context)
                for child in condition["all"]
            )

        if "any" in condition:
            return any(
                evaluate(child, context)
                for child in condition["any"]
            )

        if "not" in condition:
            return not evaluate(condition["not"], context)

        op = condition.get("op", "eq")

        if op not in OPERATORS:
            raise ValueError(f"Operator '{op}' tidak dikenal.")

        return _compare(
            _read(context, condition["field"]),
            op,
            condition.get("value"),
        )

    except Exception as error:  # noqa: BLE001 - sengaja menangkap semua
        logger.warning(
            "Kondisi workflow tidak bisa dinilai (%s): %r — "
            "step dijalankan.",
            error,
            condition,
        )

        return True


def validate(condition: dict | None) -> None:
    """
    Memeriksa bentuk kondisi saat dikonfigurasi, bukan saat dipakai.

    Dipanggil dari serializer step supaya salah ketik ketahuan di layar
    tempat kondisinya ditulis — bukan berbulan-bulan kemudian, di log,
    saat ada yang bertanya kenapa dokumennya lewat begitu saja.
    """
    if not condition:
        return

    if not isinstance(condition, dict):
        raise ValidationError(
            "Kondisi harus berupa objek JSON.",
        )

    for group in ("all", "any"):
        if group in condition:
            children = condition[group]

            if not isinstance(children, list) or not children:
                raise ValidationError(
                    f"'{group}' harus berisi daftar kondisi dan tidak "
                    "boleh kosong.",
                )

            for child in children:
                validate(child)

            return

    if "not" in condition:
        validate(condition["not"])

        return

    if "field" not in condition:
        raise ValidationError(
            "Kondisi wajib menyebut 'field', atau memakai "
            "'all'/'any'/'not'.",
        )

    op = condition.get("op", "eq")

    if op not in OPERATORS:
        raise ValidationError(
            f"Operator '{op}' tidak dikenal. Pilihannya: "
            f"{', '.join(OPERATORS)}.",
        )

    if op not in UNARY_OPERATORS and "value" not in condition:
        raise ValidationError(
            f"Operator '{op}' butuh 'value'.",
        )

    if op in ("in", "not_in") and not isinstance(
        condition.get("value"), list
    ):
        raise ValidationError(
            f"Operator '{op}' butuh 'value' berupa daftar.",
        )
