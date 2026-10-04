"""
Membuat (atau memulihkan) akun superadmin sebuah tenant.

Akun superuser di sistem ini **milik tenant**, bukan global: `accounts`
ada di `TENANT_APPS`, jadi tabel penggunanya berdiri sendiri di tiap
schema. Konsekuensinya tenant yang baru dibuat tidak punya satu pun akun
yang bisa login, dan itu bukan keadaan yang berbunyi — layar login
membalas 401 yang tidak bisa dibedakan dari salah ketik password.

Aman diulang, dan itu memang kegunaan utamanya: menjalankan ulang
memulihkan password akun yang sudah ada. Password lama di-hash, jadi
tidak ada cara memeriksanya — satu-satunya jalan keluar dari "admin
tidak bisa login" adalah menyetelnya lagi.
"""

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction


User = get_user_model()


DEFAULT_USERNAME = "admin"
DEFAULT_EMAIL = "admin@meinova.example"

# Sengaja **tanpa** password bawaan: repositori ini publik, dan password
# yang tertulis di sini berarti setiap tenant yang disiapkan perintah ini
# bisa dimasuki siapa pun. `--password` wajib dioper — untuk tenant
# peragaan, `seed_demo` mengopernya dari `DEMO_PASSWORD`.


class Command(BaseCommand):
    help = (
        "Buat atau pulihkan akun superadmin untuk tenant yang dipilih. "
        "Aman diulang — menjalankan ulang menyetel ulang passwordnya. "
        "Contoh: tenant_command create_superadmin --schema=demo "
        "--password=<DEMO_PASSWORD>"
    )

    def add_arguments(self, parser):
        parser.add_argument("--username", default=DEFAULT_USERNAME)
        parser.add_argument("--email", default=DEFAULT_EMAIL)
        parser.add_argument("--password", required=True)
        parser.add_argument(
            "--first-name",
            default="System",
            dest="first_name",
        )
        parser.add_argument(
            "--last-name",
            default="Administrator",
            dest="last_name",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        username = options["username"]

        user = User.objects.filter(username=username).first()

        created = user is None

        if created:
            user = User(username=username)

        user.email = options["email"]
        user.first_name = options["first_name"]
        user.last_name = options["last_name"]
        user.is_staff = True
        user.is_superuser = True
        user.is_active = True
        user.set_password(options["password"])
        user.save()

        # Role SYSTEM-ADMIN diberikan kalau masternya sudah diseed.
        # Superuser sebenarnya tidak membutuhkannya — `ModelPermission`
        # dan `DataScopeService` sama-sama melewatinya — tapi tanpa satu
        # pun role, layar Roles memperlihatkan akun tertinggi sistem
        # sebagai akun tanpa peran, dan itu terbaca seperti data yang
        # belum selesai diisi.
        #
        # **Sengaja tanpa kewenangan data, dan itu bukan kelalaian.**
        # Akun ini superuser; WHERE-nya tidak pernah dibaca. Menuliskan
        # `unrestricted` di sini berarti menyimpulkan cakupan dari nama
        # role — dan kalau status superuser-nya dicabut besok, akun itu
        # diam-diam menyimpan akses se-tenant yang tidak pernah
        # diputuskan siapa pun. Tertutup adalah arah yang benar untuk
        # sesuatu yang memang tidak dipakai.
        try:
            from apps.accounts.models import Role

            role = Role.objects.filter(
                code="SYSTEM-ADMIN",
                is_deleted=False,
            ).first()

            if role is not None:
                user.roles.add(role)
        except Exception as error:  # pragma: no cover - master belum ada
            self.stdout.write(
                self.style.WARNING(
                    f"Role SYSTEM-ADMIN tidak dipasang: {error}"
                )
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Superadmin '{username}' "
                f"{'dibuat' if created else 'diperbarui'} "
                f"(password disetel ulang)."
            )
        )
