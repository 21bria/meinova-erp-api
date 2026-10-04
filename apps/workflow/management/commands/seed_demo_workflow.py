from django.core.management.base import BaseCommand

from apps.workflow.seeds.demo_workflow import run


class Command(BaseCommand):
    help = (
        "Data uji alur cuti Head Office: akun, garis pelaporan, role, "
        "lalu tiga pengajuan yang dijalankan sampai selesai. Aman "
        "diulang."
    )

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("Data uji workflow"))

        result = run(log=self.stdout.write)

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Selesai: {result['created']} pengajuan dibuat, "
                f"{result.get('people', 0)} akun disiapkan."
            )
        )
