from django.core.management.base import BaseCommand

from apps.hr.seeds.roster_reset import run


class Command(BaseCommand):
    help = (
        "Mengosongkan data transaksi roster — dokumen setup, rencana "
        "roster, periode, rencana shift, kredit rotasi, pengajuan alur, "
        "dan notifikasinya — supaya entry bisa dicoba ulang dari nol. "
        "Pegawai, Roster Policy beserta rotasi shift-nya, master Shift, "
        "definisi alur, template notifikasi, dan presensi TIDAK "
        "disentuh."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--all",
            action="store_true",
            help=(
                "Ikut membuang pengajuan alur dan notifikasi modul lain "
                "(cuti, employee action). Tanpa ini hanya milik roster "
                "yang dibuang."
            ),
        )
        parser.add_argument(
            "--keep-notifications",
            action="store_true",
            help=(
                "Pertahankan isi bel dan log pengiriman. Dipakai kalau "
                "notifikasi lama masih mau dibaca sesudah datanya "
                "dikosongkan."
            ),
        )
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Jalankan tanpa bertanya. Wajib untuk pemakaian skrip.",
        )

    def handle(self, *args, **options):
        scope = "all" if options["all"] else "roster"

        self.stdout.write("Reset data roster")
        self.stdout.write(
            f"  Cakupan alur & notifikasi: "
            f"{'SELURUH modul' if scope == 'all' else 'roster saja'}",
        )

        if not options["yes"]:
            # Perintah ini menghapus permanen, dan satu-satunya jalan
            # kembali adalah backup yang mungkin belum dibuat siapa pun.
            self.stdout.write(
                self.style.WARNING(
                    "  Data dihapus PERMANEN (hard delete). Ulangi "
                    "dengan --yes kalau memang itu yang dimaksud.",
                ),
            )

            return

        counts = run(
            log=self.stdout.write,
            scope=scope,
            keep_notifications=options["keep_notifications"],
        )

        reopened = counts.pop("dokumen dikembalikan", 0)
        total = sum(counts.values())

        if not total:
            self.stdout.write(
                self.style.WARNING("  Tidak ada data roster yang perlu dibuang."),
            )

            return

        if reopened:
            self.stdout.write(
                f"\n  {reopened} dokumen yang alurnya belum selesai "
                f"dikembalikan ke draft.",
            )

        self.stdout.write(
            self.style.SUCCESS(f"\nSelesai: {total} baris dibuang."),
        )
