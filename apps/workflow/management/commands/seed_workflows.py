from django.core.management.base import BaseCommand

from apps.workflow.seeds import seed


class Command(BaseCommand):
    help = (
        "Seed alur persetujuan bawaan (cuti, cuti Head Office, Travel "
        "Request). Aman diulang."
    )

    def handle(self, *args, **options):
        result = seed()

        self.stdout.write(
            self.style.SUCCESS(
                "Seed workflow selesai: "
                f"{result['roles']} role, "
                f"{result['definitions']} alur, "
                f"{result['steps']} step."
            )
        )

        for message in result["skipped"]:
            self.stdout.write(self.style.WARNING(f"Dilewati: {message}"))
