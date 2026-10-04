from django.core.management.base import BaseCommand

from apps.workflow.seeds.demo_site_travel import run


class Command(BaseCommand):
    help = (
        "Data uji alur persetujuan: Travel Request site, Cuti site "
        "(enam meja), dan Cuti kantor pusat (tiga meja). Susunan "
        "orangnya diambil dari `seed_demo_workforce`, tidak dibentuk "
        "ulang di sini. Aman diulang."
    )

    def handle(self, *args, **options):
        self.stdout.write(
            self.style.MIGRATE_HEADING("Data uji alur persetujuan")
        )

        results = run(log=self.stdout.write)

        self.stdout.write("")

        failed = 0

        for key, result in results.items():
            if not result.get("ok"):
                failed += 1

                self.stdout.write(
                    self.style.WARNING(f"  {key:14} gagal disiapkan")
                )

                continue

            self.stdout.write(
                f"  {key:14} {result['number']:16} "
                f"{result['steps']} meja → {result['status']}"
            )

        style = self.style.WARNING if failed else self.style.SUCCESS

        self.stdout.write(
            style(f"\nSelesai: {len(results) - failed}/{len(results)} skenario.")
        )
