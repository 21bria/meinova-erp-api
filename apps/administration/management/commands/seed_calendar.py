# python manage.py tenant_command seed_calendar --schema=demo
from django.core.management.base import BaseCommand

from apps.administration.seeds.calendar import seed


class Command(BaseCommand):
    help = (
        "Seed fiscal years, posting periods, "
        "work calendars, and holidays."
    )

    def handle(self, *args, **options):
        result = seed()

        self.stdout.write(
            self.style.SUCCESS(
                "Calendar seed completed: "
                f"{result['companies']} companies, "
                f"{result['work_calendars']} work calendars, "
                f"{result['holidays']} holidays."
            )
        )