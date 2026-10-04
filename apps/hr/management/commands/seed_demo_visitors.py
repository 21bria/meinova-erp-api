from django.core.management.base import BaseCommand

from apps.hr.seeds.demo_visitors import run


class Command(BaseCommand):
    help = (
        "Seed data uji Visitor Management: 3 tamu luar plus empat "
        "dokumen kunjungan yang masing-masing berhenti di keadaan "
        "berbeda (selesai penuh, menunggu persetujuan, disetujui, "
        "draft). Butuh seed_demo_workforce + seed_workflows + "
        "seed_administration --only=hr-reference lebih dulu. "
        "Aman diulang."
    )

    def handle(self, *args, **options):
        result = run(log=self.stdout.write)

        if result["missing"]:
            self.stdout.write(
                self.style.WARNING(
                    "Pegawai data uji belum ada: "
                    + ", ".join(result["missing"])
                    + " — jalankan seed_demo_workforce dulu."
                )
            )

            return

        self.stdout.write(
            self.style.SUCCESS(
                f"\nVisitor data uji: {result['visitors']} tamu, "
                f"{result['requests']} kunjungan "
                f"({result['completed']} selesai, "
                f"{result['approved']} disetujui, "
                f"{result['submitted']} menunggu, "
                f"{result['drafts']} draft)."
            )
        )

        for note in result["skipped"]:
            self.stdout.write(self.style.WARNING(f"  ! {note}"))
