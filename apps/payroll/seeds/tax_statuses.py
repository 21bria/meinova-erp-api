from apps.payroll.models import TaxStatus


TAX_STATUSES = [
    ("TK0", "Tidak Kawin 0"),
    ("TK1", "Tidak Kawin 1"),
    ("TK2", "Tidak Kawin 2"),
    ("TK3", "Tidak Kawin 3"),
    ("K0", "Kawin 0"),
    ("K1", "Kawin 1"),
    ("K2", "Kawin 2"),
    ("K3", "Kawin 3"),
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