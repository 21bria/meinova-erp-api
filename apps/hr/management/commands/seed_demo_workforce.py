from django.core.management.base import BaseCommand

from apps.hr.seeds.demo_workforce import seed


class Command(BaseCommand):
    help = (
        "Seed tenaga kerja data uji: kantor pusat Jakarta + site Sagea, "
        "lengkap dengan garis pelaporan, crew roster, dan dokumen "
        "rosternya. Aman diulang."
    )

    def handle(self, *args, **options):
        result = seed()

        self.stdout.write(
            self.style.SUCCESS(
                "Demo workforce selesai di "
                f"{result['company']}: "
                f"{result['employees']} pegawai "
                f"({result['ho']} HO, {result['site']} site), "
                f"{result['crews']} crew, "
                f"{result['rotations']} dokumen roster."
            )
        )

        if not result["office_calendar"]:
            self.stdout.write(
                self.style.WARNING(
                    "Kalender kantor belum ada — jalankan "
                    "seed_administration --only=calendar, kalau tidak "
                    "cuti pegawai HO dihitung tujuh hari seminggu."
                )
            )
