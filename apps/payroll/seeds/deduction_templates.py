from apps.payroll.models import DeductionTemplate


DEDUCTION_TEMPLATES = [
    {
        "code": "STANDARD",
        "name": "Standard Employee",
    },
    {
        "code": "OUTSOURCE",
        "name": "Outsource",
    },
]


def seed_deduction_template() -> None:
    for row in DEDUCTION_TEMPLATES:
        DeductionTemplate.objects.update_or_create(
            code=row["code"],
            defaults={
                "name": row["name"],
                "is_active": True,
            },
        )