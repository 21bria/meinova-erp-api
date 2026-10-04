from django.core.management.base import BaseCommand

from apps.hr.seeds.demo_hr_records import run


class Command(BaseCommand):
    help = (
        "Seed isi widget dashboard HR: riwayat pendidikan, program "
        "pelatihan beserta pesertanya, lowongan terbuka, lembur, dan "
        "cuti tercatat. Butuh seed_demo_workforce lebih dulu. "
        "Aman diulang."
    )

    def handle(self, *args, **options):
        result = run(log=self.stdout.write)

        if not result:
            self.stdout.write(
                self.style.WARNING(
                    "Tidak ada yang ditulis — jalankan "
                    "seed_demo_workforce lebih dulu."
                )
            )
            return

        self.stdout.write(
            self.style.SUCCESS(
                f"Data uji dashboard HR: {result['educations']} pendidikan, "
                f"{result['trainings']} program pelatihan, "
                f"{result['vacancies']} lowongan, "
                f"{result['overtimes']} lembur, "
                f"{result['leaves']} cuti tercatat."
            )
        )
