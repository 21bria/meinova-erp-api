from __future__ import annotations

import re
import unicodedata

from apps.hr.models import Employee


# Gelar dan singkatan yang bukan bagian nama.
NAME_NOISE_TOKENS = {
    "AMD",
    "DRA",
    "DRS",
    "SKM",
    "SKOM",
    "SPD",
    "SPSI",
}

# Token sependek ini tidak dipakai membandingkan
# nama — inisial seperti "M" atau "A" cocok dengan
# terlalu banyak hal.
MIN_NAME_TOKEN_LENGTH = 3


class AttendanceEmployeeMatcher:
    @classmethod
    def find_employee(
        cls,
        employee_code: str | int | None,
    ) -> Employee | None:
        code = str(
            employee_code or "",
        ).strip()

        if not code:
            return None

        return (
            Employee.objects
            .filter(
                employee_number__iexact=code,
                is_active=True,
                is_deleted=False,
            )
            .first()
        )

    # ------------------------------------------------------------------
    # Verifikasi nama
    # ------------------------------------------------------------------

    @staticmethod
    def normalize_name(
        value: str | None,
    ) -> str:
        text = unicodedata.normalize(
            "NFKD",
            str(
                value or "",
            ),
        )

        text = "".join(
            character
            for character in text
            if not unicodedata.combining(
                character,
            )
        )

        text = re.sub(
            r"[^A-Za-z0-9]+",
            " ",
            text,
        )

        return " ".join(
            text.upper().split(),
        )

    @classmethod
    def name_tokens(
        cls,
        value: str | None,
    ) -> list[str]:
        return [
            token
            for token in cls.normalize_name(
                value,
            ).split()
            if (
                len(token)
                >= MIN_NAME_TOKEN_LENGTH
                and token
                not in NAME_NOISE_TOKENS
            )
        ]

    @classmethod
    def employee_name(
        cls,
        employee: Employee,
    ) -> str:
        return " ".join(
            part
            for part in [
                employee.first_name,
                employee.last_name,
            ]
            if part
        ).strip()

    @classmethod
    def names_match(
        cls,
        device_name: str | None,
        employee: Employee,
    ) -> bool:
        """
        Nama di mesin absensi jarang sama persis dengan
        master: sering disingkat, dipotong, atau tanpa
        gelar. Jadi perbandingannya longgar — dianggap
        orang yang sama kalau dua kata namanya cocok
        (per awalan kata), atau kata depannya cocok.
        Tujuannya menangkap nomor yang terpasang ke
        orang yang sama sekali lain, bukan menegakkan
        ejaan.

        Satu kata yang cocok saja tidak cukup kalau itu
        bukan kata depan: "Luluk Nur Faizah" dan "Endang
        Nursanti" sama-sama punya "Nur", tapi jelas dua
        orang berbeda.
        """
        device_tokens = cls.name_tokens(
            device_name,
        )

        # Mesin tidak mengirim nama — tidak ada yang
        # bisa diverifikasi, jangan halangi datanya.
        if not device_tokens:
            return True

        employee_tokens = cls.name_tokens(
            cls.employee_name(
                employee,
            ),
        )

        if not employee_tokens:
            return True

        matched = sum(
            1
            for device_token in device_tokens
            if any(
                cls.tokens_match(
                    device_token,
                    employee_token,
                )
                for employee_token
                in employee_tokens
            )
        )

        if matched >= 2:
            return True

        return (
            matched >= 1
            and cls.tokens_match(
                device_tokens[0],
                employee_tokens[0],
            )
        )

    @staticmethod
    def tokens_match(
        first: str,
        second: str,
    ) -> bool:
        return (
            first.startswith(second)
            or second.startswith(first)
        )