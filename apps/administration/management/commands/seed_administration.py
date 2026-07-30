# python manage.py tenant_command seed_administration --only=hr-reference --schema=demo
# python manage.py tenant_command seed_administration --only=geography --schema=demo
# python manage.py tenant_command seed_administration --only=organization-reference --schema=demo
# python manage.py tenant_command seed_administration --only=organization --schema=demo
# python manage.py tenant_command seed_administration --only=bank --schema=demo
# python manage.py tenant_command seed_administration --only=bank-branch --schema=demo

# python manage.py tenant_command seed_administration --only=numbering --schema=demo
# python manage.py tenant_command seed_administration --only=currency --schema=demo

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.administration.seeds.reference.hr import seed_hr_reference
from apps.administration.seeds.geography import seed_geography

from apps.administration.seeds.bank import seed_bank
from apps.administration.seeds.bank_branch import seed_bank_branch

from apps.administration.seeds.reference.organization import seed_organization_reference
from apps.administration.seeds.organization import seed_organization
from apps.administration.seeds.numbering import seed_numbering
from apps.administration.seeds.currency import seed_currency


SEEDERS = {
    "hr-reference": seed_hr_reference,
    "geography": seed_geography,

    "organization-reference": seed_organization_reference,
    "organization": seed_organization,
    
    "bank": seed_bank,
    "bank-branch": seed_bank_branch,
    "bank-branch": seed_bank_branch,

    "numbering": seed_numbering,
    "currency": seed_currency,

}

class Command(BaseCommand):
    help = "Seed administration data by domain"

    def add_arguments(self, parser):
        parser.add_argument(
            "--only",
            choices=sorted(SEEDERS),
            help="Run only one seed domain.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        only = options.get("only")

        if only:
            seeder = SEEDERS.get(only)

            if seeder is None:
                raise CommandError(f"Unknown seed domain: {only}")

            seeder()
            self.stdout.write(
                self.style.SUCCESS(
                    f"{only.upper()} data seeded successfully."
                )
            )
            return

        for name, seeder in SEEDERS.items():
            seeder()
            self.stdout.write(
                self.style.SUCCESS(
                    f"{name.upper()} data seeded successfully."
                )
            )

        self.stdout.write(
            self.style.SUCCESS(
                "All administration data seeded successfully."
            )
        )