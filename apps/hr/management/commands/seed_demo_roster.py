from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from apps.hr.seeds.demo_roster import run


def _parse(value: str):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise CommandError(
            f"Tanggal harus berformat YYYY-MM-DD, bukan '{value}'.",
        ) from exc


class Command(BaseCommand):
    help = (
        "Seed data uji modul roster: satu dokumen setup massal per site, "
        "rencana yang sudah dibaselinekan, satu penyesuaian yang sudah "
        "diterapkan, dan ledger rotation credit-nya. Butuh "
        "seed_roster_policy + seed_demo_workforce lebih dulu. Aman "
        "diulang."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--employees",
            type=int,
            default=0,
            help=(
                "Berapa pegawai yang disetup. 0 (bawaan) = semua "
                "pegawai site itu."
            ),
        )
        parser.add_argument(
            "--as-of",
            dest="as_of",
            type=_parse,
            default=None,
            help=(
                "Tanggal jangkar dokumen (YYYY-MM-DD). Jadwal berangkat "
                "dari blok yang sedang dijalani pada tanggal ini. "
                "Bawaan: tanggal 1 bulan berjalan."
            ),
        )
        parser.add_argument(
            "--only-roster-employees",
            dest="only_roster_employees",
            action="store_true",
            help=(
                "Hanya setup pegawai yang sudah dinyatakan roster "
                "(punya Roster Policy atau Roster Crew). Tanpa ini, "
                "pegawai kantor yang berkantor di site ikut tersetup."
            ),
        )
        parser.add_argument(
            "--stagger-days",
            dest="stagger_days",
            type=int,
            default=3,
            help=(
                "Jarak jangkar antar pegawai, supaya crew tidak "
                "serentak. Dilipat ke dalam satu putaran policy."
            ),
        )

    def handle(self, *args, **options):
        result = run(
            log=self.stdout.write,
            employees=options["employees"],
            as_of=options["as_of"],
            stagger_days=options["stagger_days"],
            only_roster_employees=options["only_roster_employees"],
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"Roster data uji: {result['lines']} baris setup, "
                f"{result['plans']} rencana, "
                f"{result['adjustments']} penyesuaian, "
                f"{result['credits']} transaksi kredit."
            )
        )

        for note in result["skipped"]:
            self.stdout.write(self.style.WARNING(f"  ! {note}"))
