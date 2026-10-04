"""
Pemeran Organization Scope tenant peragaan: dua BOD dan dua GM.

Dipisahkan dari `seed_demo_employees` karena yang itu terkunci ke satu
company — lihat docstring `apps/hr/seeds/demo_org_scope.py`.

Butuh `seed_demo_organization` lebih dulu (jabatan GM peragaan ada di
sana) dan `seed_security_roles` (role `EMPLOYEE` ikut dipegang).
"""

from django.core.management.base import BaseCommand

from apps.hr.seeds import demo_org_scope


class Command(BaseCommand):
    help = (
        "Seed 2 BOD + 2 GM/Executive peragaan beserta Organization "
        "Scope-nya (role BOD / EXECUTIVE). "
        "Contoh: tenant_command seed_demo_org_scope --schema=demo"
    )

    def handle(self, *args, **options):
        result = demo_org_scope.seed(log=self.stdout.write)

        self.stdout.write(
            self.style.MIGRATE_HEADING("\nOrganization Scope peragaan")
        )

        for label, value in [
            ("Pemeran", result["people"]),
            ("Role cakupan", result["roles"]),
            ("Company peragaan", result["companies"]),
            ("Baris cakupan per orang", result["extra_rows"]),
        ]:
            self.stdout.write(f"  {label:<26}{value:>3}")

        for warning in result["warnings"]:
            self.stdout.write(self.style.WARNING(f"  ! {warning}"))

        self.stdout.write(
            self.style.SUCCESS(
                "\nSelesai. Akun: demo.bod1 / demo.bod2 / demo.gmho / "
                "demo.gmsite (password dari DEMO_PASSWORD)."
            )
        )
