"""
Membuang fixture transaksi Finance dari sebuah tenant.

Kering secara bawaan:

    python manage.py tenant_command reset_finance_data --schema=demo
    python manage.py tenant_command reset_finance_data --schema=demo \
        --execute
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.core.services.finance_reset import (
    FinanceResetAborted,
    FinanceResetService,
)
from apps.core.services.finance_reset_demo import (
    DEMO_FINANCE_RESET_BASELINE,
    DEMO_FINANCE_RESET_SPEC,
)


class Command(BaseCommand):
    help = (
        "Membuang fixture transaksi Finance (Journal, JournalLine, "
        "dimensi baris, AccountingEvent) beserta pengajuan alur yang "
        "masih hidup untuknya. Master/konfigurasi Finance tidak "
        "disentuh. Bawaannya mode kering."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Benar-benar menghapus. Tanpa ini hanya melaporkan.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Menyatakan mode kering secara eksplisit (sudah bawaan).",
        )
        parser.add_argument(
            "--ignore-baseline",
            action="store_true",
            help=(
                "Teruskan walau rencana berbeda dari baseline discovery. "
                "Hanya kalau selisihnya sudah dijelaskan."
            ),
        )

    # ------------------------------------------------------------------

    def handle(self, *args, **options):
        execute = options["execute"]

        if execute and options["dry_run"]:
            raise CommandError(
                "--execute dan --dry-run tidak bisa dipakai bersamaan.",
            )

        spec = DEMO_FINANCE_RESET_SPEC

        self.stdout.write("Reset fixture transaksi Finance")
        self.stdout.write(
            f"  Mode: {'EKSEKUSI (menghapus)' if execute else 'KERING'}",
        )
        self.stdout.write("")

        report = FinanceResetService.plan(spec=spec)

        self._print_notes(report)
        self._print_cycle_breaks(report)
        self._print_plan(report)

        drift = self._drift(report)

        self._print_baseline(
            drift,
            already_reset=self._is_already_reset(report),
        )

        if report.is_blocked:
            self._print_blockers(report)

            raise CommandError(
                "Preflight gagal. Tidak ada baris yang berubah.",
            )

        if drift and not options["ignore_baseline"]:
            self.stdout.write(
                self.style.WARNING(
                    "\n  Rencana berbeda dari baseline discovery. "
                    "Jelaskan selisihnya dulu.",
                ),
            )

            if execute:
                raise CommandError(
                    "Eksekusi dihentikan karena selisih baseline.",
                )

        if not execute:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\n  Mode kering. {report.planned_total} baris AKAN "
                    f"dihapus, {len(report.cycle_breaks)} tautan "
                    f"pembalikan AKAN diputus. Tidak ada yang berubah.",
                ),
            )

            return

        self._run(spec=spec)

    # ------------------------------------------------------------------

    def _run(self, *, spec):
        try:
            result = FinanceResetService.execute(spec=spec)
        except FinanceResetAborted as exc:
            for blocker in exc.blockers:
                self.stdout.write(self.style.ERROR(f"  ! {blocker}"))

            raise CommandError(
                "Reset dibatalkan. Transaksi di-rollback — tautan "
                "pembalikan kembali seperti semula.",
            ) from exc

        self.stdout.write("\n  Terhapus:")

        for label, count in result.deleted.items():
            self.stdout.write(f"    {label:<34} {count:>6}")

        self.stdout.write(
            self.style.SUCCESS(
                f"\n  Selesai: {result.deleted_total} baris dibuang.",
            ),
        )

    def _print_notes(self, report):
        if not report.notes:
            return

        self.stdout.write("  Preflight:")

        for note in report.notes:
            self.stdout.write(f"    - {note}")

        self.stdout.write("")

    def _print_cycle_breaks(self, report):
        self.stdout.write(
            "  Pemutusan siklus PROTECT "
            f"({len(report.cycle_breaks)} baris, kolom `reversed_by`):",
        )

        if not report.cycle_breaks:
            self.stdout.write("    (tidak ada)")
        else:
            for item in report.cycle_breaks:
                self.stdout.write(f"    * {item}")

            self.stdout.write(
                "    UPDATE ini BUKAN baris terhapus dan tidak ikut "
                "dihitung di bawah.",
            )
            self.stdout.write(
                "    Seluruhnya satu transaction.atomic() dengan "
                "penghapusannya.",
            )

        self.stdout.write("")

    def _print_plan(self, report):
        self.stdout.write("  Rencana penghapusan per model:")

        for label, count in report.planned.items():
            self.stdout.write(f"    {label:<34} {count:>6}")

        self.stdout.write(f"    {'TOTAL':<34} {report.planned_total:>6}")

    @staticmethod
    def _is_already_reset(report) -> bool:
        """
        Keadaan sesudah reset berhasil: tidak ada lagi yang tersisa.

        Ini bukan penyimpangan. Rencana yang seluruhnya nol berarti
        sasarannya sudah bersih, dan menuntut operator "menjelaskan
        selisihnya" di sini melatih orang untuk mengabaikan peringatan
        baseline — justru peringatan yang harus didengar ketika
        angkanya bukan nol.

        Syaratnya sempit dengan sengaja: **setiap** label harus nol.
        Satu baris tersisa dengan jumlah yang tidak sesuai baseline
        tetap dihitung sebagai selisih dan tetap menahan --execute.
        """
        return all(
            report.planned.get(label, 0) == 0
            for label in DEMO_FINANCE_RESET_BASELINE
        )

    def _drift(self, report):
        if self._is_already_reset(report):
            return {}

        drift = {}

        for label, expected in DEMO_FINANCE_RESET_BASELINE.items():
            actual = report.planned.get(label, 0)

            if actual != expected:
                drift[label] = (expected, actual)

        return drift

    def _print_baseline(self, drift, *, already_reset=False):
        self.stdout.write("")

        if already_reset:
            self.stdout.write(
                self.style.SUCCESS(
                    "  Baseline discovery: sudah direset — seluruh "
                    "sasaran nol. Keadaan idempoten yang sah.",
                ),
            )

            return

        if not drift:
            self.stdout.write(
                self.style.SUCCESS(
                    "  Baseline discovery: COCOK pada seluruh model.",
                ),
            )

            return

        self.stdout.write(
            self.style.WARNING("  Baseline discovery: SELISIH"),
        )

        for label, (expected, actual) in drift.items():
            self.stdout.write(
                self.style.WARNING(
                    f"    {label:<34} discovery={expected:<5} "
                    f"sekarang={actual}",
                ),
            )

    def _print_blockers(self, report):
        self.stdout.write("")
        self.stdout.write(
            self.style.ERROR(
                f"  PREFLIGHT GAGAL — {len(report.blockers)} temuan:",
            ),
        )

        for blocker in report.blockers:
            self.stdout.write(self.style.ERROR(f"    ! {blocker}"))
