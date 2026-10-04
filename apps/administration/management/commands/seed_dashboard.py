# python manage.py tenant_command seed_dashboard --schema=demo

from django.core.management.base import BaseCommand
from django.db import connection

from apps.administration.services.dashboard.seeder import DashboardSeeder


class Command(BaseCommand):
    help = "Seed dashboard master data and default workspace"

    def handle(self, *args, **options):
        tenant = getattr(connection, "tenant", None)

        if tenant is None:
            self.stdout.write(
                self.style.ERROR(
                    "Run using tenant_command.\n"
                    "Example:\n"
                    "python manage.py tenant_command seed_dashboard --schema=demo"
                )
            )
            return

        widgets = DashboardSeeder.seed_widgets()
        apps = DashboardSeeder.seed_favorite_apps()

        # Pintasan (Favorite Menus) tidak diseed lagi: katalognya tabel
        # `Menu` dan susunan bawaannya diturunkan saat dibaca. Jalankan
        # `tenant_command seed_menus` supaya ada yang bisa dipilih.
        self.stdout.write(
            self.style.SUCCESS(
                f"Dashboard seeded successfully.\n"
                f"Tenant  : {tenant.schema_name}\n"
                f"Widgets : {widgets}\n"
                f"Apps    : {apps}"
            )
        )