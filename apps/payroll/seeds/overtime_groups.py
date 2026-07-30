from apps.payroll.models import OvertimeGroup


OVERTIME_GROUPS = [
    {
        "code": "STANDARD",
        "name": "Standard",
    },
    {
        "code": "SHIFT",
        "name": "Shift",
    },
    {
        "code": "MANAGEMENT",
        "name": "Management",
    },
]


def seed_overtime_group() -> None:
    for row in OVERTIME_GROUPS:
        OvertimeGroup.objects.update_or_create(
            code=row["code"],
            defaults={
                "name": row["name"],
                "is_active": True,
            },
        )