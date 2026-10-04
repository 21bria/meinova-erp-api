from django.core.management.base import BaseCommand

from apps.administration.seeds.reference.attendance_policy import seed


class Command(BaseCommand):
    help = (
        "Seed aturan kehadiran bawaan — satu aturan global tanpa "
        "toleransi, dengan ambang lembur 30 menit. Sengaja sedikit: "
        "berapa menit keterlambatan boleh dimaafkan adalah kebijakan "
        "perusahaan, bukan angka yang bisa ditebak seed. Aman diulang, "
        "dan tidak menimpa baris yang sudah disunting."
    )

    def handle(self, *args, **options):
        result = seed(log=self.stdout.write)

        self.stdout.write(
            self.style.SUCCESS(
                f"Attendance policy: {result['created']} aturan baru."
            )
        )
