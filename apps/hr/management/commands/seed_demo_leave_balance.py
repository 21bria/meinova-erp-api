"""
Membangun ulang saldo cuti tenant peragaan dari sumbernya.

    # samakan saja (aman diulang, tidak membuang apa pun)
    tenant_command seed_demo_leave_balance --schema=demo

    # bersihkan dulu, lalu bentuk ulang dari nol
    tenant_command seed_demo_leave_balance --reset --schema=demo

Yang disentuh cuma pegawai bernomor awalan data uji (`HO`, `SGA`,
`LOK`) — batas yang sama dengan `reset_demo_data`. Catatan cuti,
LeaveType, dan Leave Policy tidak pernah disentuh: kartu saldo dibentuk
ulang **dari** ketiganya.
"""

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.hr.seeds.demo_leave_balance import run


class Command(BaseCommand):
    help = (
        "Bentuk ulang saldo cuti tenant peragaan: go-live, dokumen "
        "saldo awal, kartu saldo, dan pemakaiannya. Aman diulang."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--year",
            type=int,
            default=None,
            help="Tahun saldo. Bawaan tahun berjalan.",
        )

        parser.add_argument(
            "--reset",
            action="store_true",
            dest="do_reset",
            help=(
                "Buang dulu seluruh kartu saldo dan dokumen saldo awal "
                "pegawai data uji, lalu bentuk ulang. Catatan cuti "
                "tidak disentuh — `used` dijumlah ulang dari sana."
            ),
        )

        parser.add_argument(
            "--force",
            action="store_true",
            help=(
                "Lanjutkan --reset walau ada kartu yang membawa "
                "adjustment / carried_over bukan nol."
            ),
        )

        parser.add_argument(
            "--quiet-rows",
            action="store_true",
            dest="quiet_rows",
            help="Jangan cetak tabel saldo akhirnya.",
        )

    def handle(self, *args, **options):
        year = options["year"] or timezone.localdate().year

        try:
            result = run(
                year=year,
                do_reset=options["do_reset"],
                force=options["force"],
                log=self.stdout.write,
            )
        except RuntimeError as error:
            raise CommandError(str(error)) from error

        note = result.get("note")

        if note:
            self.stdout.write(
                self.style.WARNING(f"Tidak ada yang ditulis: {note}."),
            )

            return

        rows = result["rows"]

        if not options["quiet_rows"]:
            self.stdout.write("")
            self.stdout.write(
                "  %-8s %-24s %-8s %6s %6s %6s"
                % ("NOMOR", "PEGAWAI", "CUTI", "AWAL", "PAKAI", "SISA")
            )

            for row in rows:
                self.stdout.write(
                    "  %-8s %-24s %-8s %6s %6s %6s"
                    % (
                        row["employee_number"],
                        row["employee"][:24],
                        row["leave_type"],
                        row["opening"],
                        row["used"],
                        row["remaining"],
                    )
                )

        if result["unlisted"]:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    f"{len(result['unlisted'])} pegawai dilewati — "
                    f"belum punya angka saldo awal di seed: "
                    f"{', '.join(result['unlisted'])}."
                ),
            )

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"Saldo cuti data uji {result['year']} siap: "
                f"{len(rows)} kartu, go-live "
                f"{result['go_live_date']}."
            ),
        )
