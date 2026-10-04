from django.core.management.base import BaseCommand

from apps.administration.seeds.demo.organization import DATASET, seed


class Command(BaseCommand):
    help = (
        "Seed struktur organisasi tenant peragaan: 3 company fiktif "
        "(Meinova Nusantara / Mineral Resources / Logistik Samudra) "
        "beserta lokasi, division, department, section, position, dan "
        "cost center-nya. Butuh seed_administration lebih dulu "
        "(geography + organization-reference + hr-reference). "
        "Aman diulang."
    )

    def handle(self, *args, **options):
        seed()

        self.stdout.write(
            self.style.SUCCESS(
                f"{DATASET.name}: "
                f"{len(DATASET.companies)} company, "
                f"{len(DATASET.locations)} location, "
                f"{len(DATASET.departments)} department, "
                f"{len(DATASET.sections)} section, "
                f"{len(DATASET.positions)} position."
            )
        )
