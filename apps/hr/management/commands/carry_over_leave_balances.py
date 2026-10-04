"""
Memindahkan sisa cuti antar tahun, dan menghanguskan yang lewat.

Dijalankan manual — lihat alasannya di docstring
`apps/hr/api/leave/carry_over.py`. Urutan yang benar untuk pergantian
tahun:

    tenant_command generate_leave_balances --year=2027 --schema=demo
    tenant_command carry_over_leave_balances --year=2027 --schema=demo

Yang kedua butuh baris saldo tahun tujuan sudah ada; kalau belum, ia
melaporkannya sebagai `skipped_no_target` alih-alih membuat baris tanpa
menghitung jatahnya.
"""

from django.core.management.base import BaseCommand

from apps.hr.api.leave.carry_over import LeaveCarryOverService


class Command(BaseCommand):
    help = (
        "Memindahkan sisa cuti tahun lalu ke tahun berjalan, dan/atau "
        "menghanguskan sisa bawaan yang sudah lewat tanggalnya."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--year",
            type=int,
            default=None,
            help=(
                "Tahun tujuan. Sisa tahun sebelumnya yang dipindahkan. "
                "Dikosongkan = tahun berjalan."
            ),
        )

        parser.add_argument(
            "--expire",
            action="store_true",
            help=(
                "Jalankan penghangusan saja, tanpa memindahkan apa pun. "
                "Ini yang dijalankan berkala; pemindahan cuma sekali "
                "setahun."
            ),
        )

        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Tampilkan yang akan terjadi tanpa menulis apa pun.",
        )

        parser.add_argument(
            "--verbose-rows",
            action="store_true",
            help="Cetak rincian per baris.",
        )

    def handle(self, *args, **options):
        from django.utils import timezone

        dry_run = options["dry_run"]
        verbose = options["verbose_rows"]

        if dry_run:
            self.stdout.write(
                self.style.WARNING("DRY RUN — tidak ada yang ditulis."),
            )

        if not options["expire"]:
            year = options["year"] or timezone.localdate().year

            result = LeaveCarryOverService.carry_over(
                year=year,
                dry_run=dry_run,
            )

            self._report(f"Pemindahan ke {year}", result, verbose=verbose)

            if result["skipped_no_target"]:
                self.stdout.write(
                    self.style.ERROR(
                        f"  {result['skipped_no_target']} baris tidak punya "
                        f"saldo tujuan di {year}. Jalankan "
                        f"`generate_leave_balances --year={year}` dulu, "
                        "lalu ulangi perintah ini.",
                    ),
                )

        expired = LeaveCarryOverService.expire(dry_run=dry_run)

        self._report("Penghangusan", expired, verbose=verbose)

    def _report(self, title, result, *, verbose):
        self.stdout.write(self.style.MIGRATE_HEADING(f"\n{title}"))

        for key, value in result.items():
            if key == "details":
                continue

            self.stdout.write(f"  {key}: {value}")

        if not verbose:
            return

        for row in result.get("details", []):
            self.stdout.write(f"    {row}")
