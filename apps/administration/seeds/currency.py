from apps.administration.models import Currency

from .base import seed_reference


# Kolomnya `is_base_currency`, dan sempat ditulis `is_base` di sini.
# `seed_reference` membuang kunci yang bukan field model — tanpa error,
# tanpa peringatan — jadi **tidak ada satu tenant pun yang punya mata
# uang dasar** sejak seed pertama. Gagalnya jauh dari sini: import
# payroll menjatuhkan currency yang kosong ke `is_base_currency`, dan
# yang tidak pernah ketemu berarti baris penempatan gajinya ditolak.
# Ketahuan lewat pemeriksaan Kesehatan Konfigurasi di dashboard.
CURRENCIES = [
    ("IDR", "Indonesian Rupiah", "Rp", 2, True),
    ("USD", "US Dollar", "$", 2, False),
    ("SGD", "Singapore Dollar", "S$", 2, False),
    ("AUD", "Australian Dollar", "A$", 2, False),
    ("EUR", "Euro", "€", 2, False),
    ("JPY", "Japanese Yen", "¥", 0, False),
    ("CNY", "Chinese Yuan", "¥", 2, False),
]


def seed_currency() -> None:
    seed_reference(
        Currency,
        [
            {
                "code": code,
                "name": name,
                "symbol": symbol,
                "decimal_places": decimals,
                "is_base_currency": is_base,
            }
            for code, name, symbol, decimals, is_base in CURRENCIES
        ],
    )