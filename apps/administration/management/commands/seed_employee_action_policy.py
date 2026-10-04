from django.core.management.base import BaseCommand

from apps.administration.seeds.reference.employee_action_policy import seed


class Command(BaseCommand):
    help = (
        "Seed aturan pengusul Employee Action bawaan — gaji dan promosi "
        "oleh Kepala Departemen, transfer oleh Atasan Langsung, "
        "pengunduran diri oleh pegawainya sendiri, perpanjangan kontrak "
        "dan perubahan jenis kepegawaian oleh HR-ADMIN. Aman diulang, "
        "dan tidak menimpa baris yang sudah disunting."
    )

    def handle(self, *args, **options):
        result = seed(log=self.stdout.write)

        self.stdout.write(
            self.style.SUCCESS(
                f"Employee Action policy: {result['created']} aturan "
                f"baru, {result['updated']} diperbarui."
            )
        )

        for note in result.get("skipped", []):
            self.stdout.write(
                self.style.WARNING(
                    f"  ! {note} — jalankan seed_security_roles dulu, "
                    "lalu ulangi perintah ini."
                )
            )
