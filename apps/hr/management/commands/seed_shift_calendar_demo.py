"""
`tenant_command seed_shift_calendar_demo --schema=demo`

Menempelkan rencana shift ke roster yang **sudah** ada. Tidak
menerbitkan roster, tidak menyentuh satu baris `RotationPeriod` pun.
"""

from datetime import datetime

from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = (
        "Rencana shift mingguan + satu penyesuaian untuk pegawai roster "
        "data uji, plus konfigurasi Feature Applicability BOARD/"
        "MANAGEMENT. Aman diulang."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--start",
            help=(
                "Tanggal mulai rentang rencana (YYYY-MM-DD). Bawaan: "
                "tanggal 1 bulan berjalan."
            ),
        )
        parser.add_argument(
            "--weeks",
            type=int,
            default=16,
            help="Panjang rentang rencana dalam minggu. Bawaan 16.",
        )
        parser.add_argument(
            "--employees",
            type=int,
            default=0,
            help="Batasi jumlah pegawai roster; 0 = semua.",
        )

    def handle(self, *args, **options):
        from apps.hr.seeds import demo_shift_calendar

        start = None

        if options.get("start"):
            start = datetime.strptime(options["start"], "%Y-%m-%d").date()

        result = demo_shift_calendar.run(
            log=self.stdout.write,
            start=start,
            weeks=options["weeks"],
            employees=options["employees"],
        )

        if result.get("removed"):
            self.stdout.write(
                f"\n  ({result['removed']} penugasan seed lama dibuang)",
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"\n{result['assignments']} blok shift untuk "
                f"{result['employees']} pegawai roster, "
                f"{result['overrides']} penyesuaian, "
                f"{result['shifts']} shift master."
            )
        )

        if result.get("rest_days"):
            self.stdout.write(
                f"  Recovery: {result['rest_days']} hari disisipkan "
                f"(jeda minimum {result['min_rest_hours']} jam)",
            )

        if result.get("override"):
            self.stdout.write(f"  Penyesuaian: {result['override']}")

        for note in result["notes"]:
            self.stdout.write(self.style.WARNING(f"  ! {note}"))
