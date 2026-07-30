# python manage.py tenant_command seed_payroll --schema=demo
from django.core.management.base import BaseCommand

from apps.payroll.seeds import (
    seed_payroll_group,
    seed_salary_grade,
    seed_salary_level,
    seed_tax_status,
    seed_overtime_group,
    seed_allowance_template,
    seed_deduction_template,
)


class Command(BaseCommand):
    help = "Seed Payroll Master"

    def handle(self, *args, **kwargs):
        seed_payroll_group()
        seed_salary_grade()
        seed_salary_level()
        seed_tax_status()
        seed_overtime_group()
        seed_allowance_template()
        seed_deduction_template()

        self.stdout.write(
            self.style.SUCCESS(
                "Payroll master seeded successfully."
            )
        )