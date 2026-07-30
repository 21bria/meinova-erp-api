from apps.payroll.models import SalaryGrade


SALARY_GRADES = [
    {"code": "A", "name": "Grade A"},
    {"code": "B", "name": "Grade B"},
    {"code": "C", "name": "Grade C"},
    {"code": "D", "name": "Grade D"},
]


def seed_salary_grade() -> None:
    for row in SALARY_GRADES:
        SalaryGrade.objects.update_or_create(
            code=row["code"],
            defaults={
                "name": row["name"],
                "is_active": True,
            },
        )