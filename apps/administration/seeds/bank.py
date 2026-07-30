from apps.administration.models import Bank

from .base import seed_reference


BANKS = [
    ("BCA", "Bank Central Asia"),
    ("MANDIRI", "Bank Mandiri"),
    ("BNI", "Bank Negara Indonesia"),
    ("BRI", "Bank Rakyat Indonesia"),
    ("CIMB", "CIMB Niaga"),
    ("PERMATA", "Bank Permata"),
    ("OCBC", "OCBC Indonesia"),
    ("DANAMON", "Bank Danamon"),
    ("BTN", "Bank Tabungan Negara"),
]


def seed_bank() -> None:
    seed_reference(
        Bank,
        [
            {
                "code": code,
                "name": name,
            }
            for code, name in BANKS
        ],
    )