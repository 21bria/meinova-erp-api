from apps.payroll.models import AllowanceTemplate


ALLOWANCE_TEMPLATES = [
    {
        "code": "STANDARD",
        "name": "Standard Employee",
    },
    {
        "code": "STAFF",
        "name": "Staff",
    },
    {
        "code": "SUPERVISOR",
        "name": "Supervisor",
    },
]


def seed_allowance_template() -> None:
    for row in ALLOWANCE_TEMPLATES:
        AllowanceTemplate.objects.update_or_create(
            code=row["code"],
            defaults={
                "name": row["name"],
                "is_active": True,
            },
        )