from datetime import date

from django.core.management.base import BaseCommand

from apps.hr.api.leave.entitlement import LeaveBalanceGenerator


class Command(BaseCommand):
    help = (
        "Menerbitkan LeaveBalance dari Leave Policy. Aman diulang — "
        "kolom `adjustment` dan `used` tidak pernah disentuh."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--year",
            type=int,
            default=date.today().year,
            help="Tahun periode cuti. Bawaan tahun berjalan.",
        )

        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Tampilkan hasil hitungnya tanpa menulis apa pun.",
        )

        parser.add_argument(
            "--verbose-rows",
            action="store_true",
            help="Cetak satu baris per pegawai beserta alasannya.",
        )

    def handle(self, *args, **options):
        result = LeaveBalanceGenerator.run(
            year=options["year"],
            dry_run=options["dry_run"],
        )

        if options["verbose_rows"]:
            for row in result["details"]:
                self.stdout.write(
                    "  %-10s %-8s %6s hari  %s" % (
                        row["employee"],
                        row["leave_type"],
                        row["days"],
                        row["reason"],
                    )
                )

        prefix = "[DRY RUN] " if options["dry_run"] else ""

        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}Leave balance {result['year']}: "
                f"{result['created']} dibuat, "
                f"{result['updated']} diperbarui, "
                f"{result['skipped']} dilewati (tanpa policy)."
            )
        )

        # Disebut eksplisit, bukan dibiarkan terbaca sebagai nol biasa.
        # Perintah ini dijalankan orang yang justru sedang bertanya
        # "kenapa jatahnya tidak keluar", dan jawabannya — tahun itu
        # dipegang sistem lama — tidak ada di angka mana pun di atas.
        if result.get("from_opening"):
            self.stdout.write(
                self.style.WARNING(
                    f"{prefix}{result['from_opening']} pasangan "
                    f"pegawai x jenis cuti sengaja nol: tahun "
                    f"{result['year']} dipegang sistem lama menurut "
                    f"Leave Go-Live."
                )
            )
            self.stdout.write(
                "  Saldonya datang dari Leave Opening Balance yang "
                "sudah di-post, bukan dari perintah ini."
            )

        # Alasan kedua sebuah pasangan tidak menghasilkan baris, dan ia
        # bukan kelalaian: cuti menikah/melahirkan/duka memang tidak
        # punya saldo. Disebut supaya "kok cuma segini yang dibuat"
        # punya jawaban di tempat orang membacanya.
        if result.get("non_balance"):
            self.stdout.write(
                f"{prefix}{result['non_balance']} pasangan dilewati "
                f"karena policy-nya bukan cuti bersaldo — haknya "
                f"diperiksa saat pengajuan."
            )
