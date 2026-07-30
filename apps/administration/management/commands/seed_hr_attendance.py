from django.core.management.base import BaseCommand

from apps.administration.seeds.reference.hr_attendance import seed


class Command(BaseCommand):
    help = "Seed HR Attendance master data."

    def handle(self, *args, **options):
        result = seed()

        self.stdout.write(
            self.style.SUCCESS(
                "HR Attendance seed completed: "
                f"{result['shift_groups']} shift groups, "
                f"{result['shifts']} shifts, "
                f"{result['work_schedules']} work schedules, "
                f"{result['work_schedule_days']} schedule days."
            )
        )