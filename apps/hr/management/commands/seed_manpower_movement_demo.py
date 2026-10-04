"""
Menyiapkan tenant peragaan untuk layar Manpower Movement.

Lihat `apps/hr/seeds/demo_manpower_movement.py` untuk alasannya —
ringkasnya: tenant peragaan tidak punya satu pun pergerakan, jadi lima
dari enam kartu laporannya berdiri nol dan tidak bisa dibedakan dari
layar yang gagal memuat.

    tenant_command seed_manpower_movement_demo --schema=demo

Aman diulang.
"""

from django.core.management.base import BaseCommand

from apps.hr.seeds import demo_manpower_movement


class Command(BaseCommand):
    help = (
        "Terbitkan dua kepergian dan dua mutasi peragaan lewat "
        "Employee Action, berlaku di bulan berjalan, supaya layar "
        "Manpower Movement punya isi. Aman diulang. Contoh: "
        "tenant_command seed_manpower_movement_demo --schema=demo"
    )

    def handle(self, *args, **options):
        result = demo_manpower_movement.seed(log=self.stdout.write)

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"\nManpower Movement peragaan — as of {result['as_of']}"
            )
        )

        self.stdout.write(
            f"  {'Dokumen diterapkan':<26}{len(result['applied']):>3}"
        )

        for item in result["applied"]:
            self.stdout.write(
                f"    {item['number']:<8}{item['label']:<34}"
                f"{item['effective_date'].isoformat()}"
            )

        for note in result["skipped"]:
            self.stdout.write(self.style.WARNING(f"  ! {note}"))
