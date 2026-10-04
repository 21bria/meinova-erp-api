from apps.payroll.models import TaxStatus


TAX_STATUSES = [
    ("TK/0", "Tidak Kawin 0"),
    ("TK/1", "Tidak Kawin 1"),
    ("TK/2", "Tidak Kawin 2"),
    ("TK/3", "Tidak Kawin 3"),
    ("K/0", "Kawin 0"),
    ("K/1", "Kawin 1"),
    ("K/2", "Kawin 2"),
    ("K/3", "Kawin 3"),
]


def seed_tax_status() -> None:
    for code, name in TAX_STATUSES:
        TaxStatus.objects.update_or_create(
            code=code,
            defaults={
                "name": name,
                "is_active": True,
            },
        )