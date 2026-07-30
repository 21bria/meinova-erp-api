from apps.administration.models import Currency

from .base import seed_reference


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
                "is_base": is_base,
            }
            for code, name, symbol, decimals, is_base in CURRENCIES
        ],
    )