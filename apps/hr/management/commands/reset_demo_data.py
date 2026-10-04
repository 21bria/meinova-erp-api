from django.core.management.base import BaseCommand

from apps.hr.seeds.demo_reset import run


class Command(BaseCommand):
    help = (
        "Membuang seluruh data uji (pegawai HO*/SGA*, dokumen, dan akun "
        "demo.*) supaya bisa dibangun ulang dari nol. Master organisasi "
        "dan definisi alur tidak disentuh."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--keep-accounts",
            action="store_true",
            help=(
                "Pertahankan akun demo.*. Role yang menempel padanya "
                "ikut tertinggal — pakai hanya kalau memang mau "
                "menyimpan login yang sudah dipakai menguji."
            ),
        )

    def handle(self, *args, **options):
        self.stdout.write("Reset data uji")

        counts = run(
            log=self.stdout.write,
            keep_accounts=options["keep_accounts"],
        )

        total = sum(counts.values())

        if not total:
            self.stdout.write(
                self.style.WARNING("  Tidak ada data uji yang perlu dibuang.")
            )

            return

        self.stdout.write(
            self.style.SUCCESS(f"\nSelesai: {total} baris dibuang.")
        )
