from django.core.management.base import BaseCommand

from apps.accounts.seeds import seed


class Command(BaseCommand):
    help = (
        "Isi izin per model ke role bawaan lalu tugaskan role dasarnya. "
        "Jalankan ini SEBELUM menyalakan ENFORCE_MODEL_PERMISSIONS. "
        "Aman diulang — izin ditambahkan, tidak pernah dicabut."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--assign",
            default="",
            help=(
                "Username atau email yang ikut diberi SYSTEM-ADMIN, "
                "dipisah koma. Superuser sudah otomatis."
            ),
        )

    def handle(self, *args, **options):
        assign = [
            value.strip()
            for value in str(options["assign"]).split(",")
            if value.strip()
        ]

        self.stdout.write("Mengisi izin role:")

        result = seed(assign=assign, log=self.stdout.write)

        self.stdout.write(
            self.style.SUCCESS(
                f"\nSelesai: {result['roles']} role "
                f"({result['created']} baru), "
                f"{result['granted']} izin ditambahkan, "
                f"{result['assigned_admin']} akun jadi SYSTEM-ADMIN, "
                f"{result['assigned_employee']} akun diberi role dasar."
            )
        )

        for message in result["warnings"]:
            self.stdout.write(self.style.WARNING(f"! {message}"))
