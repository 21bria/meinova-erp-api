from apps.payroll.models import (
    SalaryGrade,
    SalaryLevel,
)


SALARY_LEVELS = [
    ("A", "A1", 1),
    ("A", "A2", 2),
    ("A", "A3", 3),

    ("B", "B1", 1),
    ("B", "B2", 2),
    ("B", "B3", 3),

    ("C", "C1", 1),
    ("C", "C2", 2),

    ("D", "D1", 1),
]


def seed_salary_level() -> None:
    for grade_code, code, sequence in SALARY_LEVELS:

        grade = SalaryGrade.objects.get(
            code=grade_code,
        )

        SalaryLevel.objects.update_or_create(
            salary_grade=grade,
            code=code,
            defaults={
                "name": code,
                "sequence": sequence,
                "is_active": True,
            },
        )