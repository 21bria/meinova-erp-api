"""
Penilai syarat kebijakan akuntansi.

**Tata bahasanya sama persis dengan `WorkflowStep.condition` dan
`visible_when` di schema UI** — `{field, op, value}` digabung
`all`/`any`/`not`. Itu disengaja: orang keuangan yang pernah menulis
syarat sebuah step approval tidak perlu mempelajari dialek kedua, dan
pemeriksaan bentuknya dipinjam langsung dari sana lewat
`workflow.conditions.validate`, jadi tata bahasanya hanya punya satu
definisi di seluruh sistem.

**Yang dibalik: arah kegagalannya.**

Di workflow, syarat yang tidak bisa dinilai dianggap **terpenuhi**, dan
itu benar di sana — step approval yang hilang gara-gara salah ketik
jauh lebih berbahaya daripada step tambahan yang seharusnya dilewati.

Di sini kebalikannya, dan alasannya lebih keras: aturan yang cocok
karena salah ketik akan **membukukan uang ke akun yang salah**, dan
tidak ada satu pun angka yang terlihat janggal sesudahnya. Jurnalnya
seimbang, periodenya benar, jumlahnya benar — cuma akunnya bukan yang
dimaksud siapa pun. Kesalahan semacam itu ditemukan berbulan-bulan
kemudian oleh auditor, bukan oleh operatornya.

Jadi di berkas ini: **kunci yang tidak ada berarti tidak cocok.**
Aturan yang tidak pernah cocok menghasilkan kejadian ber-status
`SKIPPED` yang terdaftar di layar dan menyebut dirinya; aturan yang
cocok karena kelalaian tidak menghasilkan apa pun yang bisa dilihat.
"""

from __future__ import annotations

import logging
from decimal import Decimal, InvalidOperation
from typing import Any

from apps.workflow.conditions import UNARY_OPERATORS, validate  # noqa: F401


logger = logging.getLogger(__name__)


# Penanda "kunci ini tidak ada di konteks". Bukan `None`: `None` adalah
# nilai yang sah dan harus bisa dibandingkan dengan `is_null`.
MISSING = object()


def read(context: Any, path: str):
    """
    Membaca nilai dari konteks, menembus titik (`employer.bpjs_health`).

    Mengembalikan `MISSING` kalau salah satu ruasnya tidak ada — bukan
    `None`. Bedanya menentukan: komponen gaji yang nilainya memang nol
    dan komponen gaji yang tidak dikirim sama sekali adalah dua keadaan
    yang berbeda, dan yang kedua tidak boleh diam-diam dibukukan
    sebagai yang pertama.
    """
    current = context

    for part in str(path).split("."):
        if isinstance(current, dict):
            if part not in current:
                return MISSING

            current = current[part]

            continue

        if not hasattr(current, part):
            return MISSING

        current = getattr(current, part)

    return current


def _numeric(value):
    if isinstance(value, Decimal):
        return value

    if isinstance(value, bool):
        return None

    if isinstance(value, (int, float)):
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
        return left is True or left == 1

    if op == "is_false":
        return left is False or left == 0

    if op == "in":
        return left in right if isinstance(right, (list, tuple, set)) else False

    if op == "not_in":
        return (
            left not in right
            if isinstance(right, (list, tuple, set))
            else False
        )

    if op == "contains":
        try:
            return str(right) in str(left)
        except TypeError:
            return False

    if op == "eq":
        return _equal(left, right)

    if op == "ne":
        return not _equal(left, right)

    left_num = _numeric(left)
    right_num = _numeric(right)

    if left_num is None or right_num is None:
        # Perbandingan besar-kecil atas nilai yang bukan angka.
        # **Tidak cocok**, dan dicatat: syarat "jumlah > 1000" yang
        # nilainya ternyata teks adalah konfigurasi yang salah, dan
        # menganggapnya cocok berarti menerbitkan jurnal karenanya.
        logger.warning(
            "Syarat kebijakan akuntansi membandingkan nilai non-angka "
            "(%r %s %r) — dianggap tidak cocok.",
            left, op, right,
        )

        return False

    if op == "gt":
        return left_num > right_num

    if op == "gte":
        return left_num >= right_num

    if op == "lt":
        return left_num < right_num

    if op == "lte":
        return left_num <= right_num

    return False


def _equal(left, right) -> bool:
    """
    Kesetaraan yang mengenal angka berbeda tipe.

    `Decimal("0")` dari payload JSON dan `0` yang diketik di layar
    syarat adalah nilai yang sama bagi orang yang menulisnya, dan
    membedakannya membuat syarat yang terlihat benar tidak pernah
    cocok.
    """
    if left == right:
        return True

    left_num = _numeric(left)
    right_num = _numeric(right)

    if left_num is not None and right_num is not None:
        return left_num == right_num

    if isinstance(left, str) and isinstance(right, str):
        return left.strip().casefold() == right.strip().casefold()

    return False


def evaluate(condition: dict | None, context: dict | None) -> bool:
    """
    Menilai satu syarat terhadap konteks.

    Kosong = **selalu cocok**. Itu satu-satunya keadaan yang longgar di
    sini, dan ia dinyatakan sengaja: aturan tanpa syarat memang berarti
    "berlaku untuk semua baris", dan itulah bentuk aturan penutup di
    hampir setiap kebijakan.
    """
    if not condition:
        return True

    if not isinstance(condition, dict):
        logger.warning(
            "Syarat kebijakan akuntansi bukan objek (%r) — tidak cocok.",
            condition,
        )

        return False

    if "all" in condition:
        return all(
            evaluate(item, context) for item in condition.get("all") or []
        )

    if "any" in condition:
        return any(
            evaluate(item, context) for item in condition.get("any") or []
        )

    if "not" in condition:
        return not evaluate(condition.get("not"), context)

    field = condition.get("field")
    op = str(condition.get("op") or "eq")

    if not field:
        logger.warning("Syarat tanpa `field` (%r) — tidak cocok.", condition)

        return False

    value = read(context or {}, field)

    if value is MISSING:
        # **Inti berkas ini.** Kunci yang tidak ada berarti tidak cocok,
        # termasuk untuk `is_null`: "tidak dikirim" dan "dikirim
        # bernilai kosong" adalah dua hal berbeda, dan kebijakan yang
        # ingin menangkap yang pertama harus menyebutnya sendiri.
        return False

    return _compare(value, op, condition.get("value"))
