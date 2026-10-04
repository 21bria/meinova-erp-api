from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from apps.hr.seeds.demo_attendance import run


def _parse(value: str):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise CommandError(
            f"Tanggal harus berformat YYYY-MM-DD, bukan '{value}'.",
        ) from exc


class Command(BaseCommand):
    help = (
        "Seed presensi data uji untuk pegawai HO*/SGA*: bulan berjalan "
        "sampai hari ini. Kantor 10:00–18:00 mengikuti WorkCalendar, "
        "site 07:00–17:00 mengikuti baris roster yang benar-benar "
        "dijadwalkan. Jam masuk/pulangnya bervariasi tapi deterministik "
        "— dijalankan ulang menghasilkan angka yang sama. Aman diulang."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--until",
            type=_parse,
            default=None,
            help=(
                "Hari terakhir yang diisi (YYYY-MM-DD). "
                "Bawaan: hari ini."
            ),
        )

        parser.add_argument(
            "--start",
            type=_parse,
            default=None,
            help=(
                "Hari pertama yang diisi (YYYY-MM-DD). "
                "Bawaan: tanggal 1 di bulan `--until`."
            ),
        )

    def handle(self, *args, **options):
        result = run(
            log=self.stdout.write,
            until=options["until"],
            start=options["start"],
        )

        if result["removed"]:
            self.stdout.write(
                f"  ({result['removed']} baris seed lama dibuang)",
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Presensi data uji {result['start']} s/d {result['until']}: "
                f"{result['created']} baris untuk "
                f"{result['employees']} pegawai."
            )
        )

        if result["untapped"]:
            self.stdout.write(
                f"  {result['untapped']} hari terjadwal sengaja dibiarkan "
                f"tanpa catatan — jalankan `close_attendance` untuk "
                f"menutupnya jadi Absent/Leave."
            )

        if result.get("no_schedule"):
            self.stdout.write(
                self.style.WARNING(
                    f"  {result['no_schedule']} hari terjadwal tanpa "
                    "shift — masternya belum menyebut jam kerjanya. "
                    "Jalankan `seed_shift_calendar_demo` lebih dulu."
                )
            )

        for note in result["skipped"]:
            self.stdout.write(self.style.WARNING(f"  ! {note}"))
