from apps.payroll.models import PayrollGroup


PAYROLL_GROUPS = [
    {
        "code": "MONTHLY",
        "name": "Monthly Payroll",
        "description": "Monthly payroll processing",
    },
    {
        "code": "WEEKLY",
        "name": "Weekly Payroll",
        "description": "Weekly payroll processing",
    },
    {
        "code": "DAILY",
        "name": "Daily Payroll",
        "description": "Daily payroll processing",
    },
]


def seed_payroll_group() -> None:
    for row in PAYROLL_GROUPS:
        PayrollGroup.objects.update_or_create(
            code=row["code"],
            defaults={
                "name": row["name"],
                "description": row["description"],
                "is_active": True,
            },
        )