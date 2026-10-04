from django.core.management.base import BaseCommand

from apps.hr.seeds.demo_attendance_policy import run


class Command(BaseCommand):
    help = (
        "Seed aturan kehadiran tenant peragaan: satu untuk kantor "
        "pusat (toleransi 1 menit, telat >2 jam = setengah hari cuti) "
        "dan satu untuk site (tanpa toleransi, tanpa ambang cuti). "
        "Butuh seed_demo_organization lebih dulu. Aman diulang."
    )

    def handle(self, *args, **options):
        result = run(log=self.stdout.write)

        self.stdout.write(
            self.style.SUCCESS(
                f"Attendance policy peragaan: {result['written']} baris."
            )
        )

        for note in result["skipped"]:
            self.stdout.write(self.style.WARNING(f"  ! {note}"))
