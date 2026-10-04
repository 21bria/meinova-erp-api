from django.core.management.base import BaseCommand

from apps.administration.seeds.reference.roster_policy import seed


class Command(BaseCommand):
    help = (
        "Seed kebijakan roster (pola siklus + hari perjalanan per POH) "
        "untuk satu site. Aman diulang."
    )

    def add_arguments(self, parser):
        # Site-nya bisa disebut, karena tenant klien menamai lokasinya
        # sendiri. Bawaannya site tenant peragaan.
        parser.add_argument("--company", default="MMR")
        parser.add_argument("--location", default="Sagea Mine")

    def handle(self, *args, **options):
        r = seed(
            company_code=options["company"],
            location_name=options["location"],
        )

        if r.get("skipped"):
            self.stdout.write(
                self.style.WARNING(
                    f"Company {r['skipped']} tidak ada — dilewati."
                )
            )
            return

        if r.get("retired"):
            self.stdout.write(
                self.style.WARNING(
                    f"{r['retired']} policy lama tanpa pola siklus "
                    "dinonaktifkan — policy tanpa pola tidak bisa "
                    "ditugaskan ke pegawai."
                )
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Roster policy selesai untuk {r['location']}: "
                f"{r['policies']} pola, "
                f"{r['travel_days']} pemetaan POH, "
                f"{r['urgent_purposes']} alasan mendadak."
            )
        )
