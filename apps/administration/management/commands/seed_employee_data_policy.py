from django.core.management.base import BaseCommand

from apps.administration.seeds.reference.employee_data_policy import seed


class Command(BaseCommand):
    help = (
        "Seed aturan kerahasiaan data pegawai bawaan — riwayat gaji dan "
        "riwayat pengunduran diri/terminasi hanya untuk yang "
        "bersangkutan, atasan langsung, dan HR Manager. Aman diulang, "
        "dan tidak menimpa baris yang sudah disunting."
    )

    def handle(self, *args, **options):
        result = seed(log=self.stdout.write)

        self.stdout.write(
            self.style.SUCCESS(
                f"Employee data policy: {result['created']} aturan "
                f"baru, {result['updated']} diperbarui."
            )
        )
