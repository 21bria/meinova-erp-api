"""
Membuang dataset UAT dari sebuah tenant.

Kering secara bawaan. Menghapus baris butuh `--execute` yang diketik
sengaja — tidak ada mode "kering kalau lupa", yang ada mode "merusak
kalau diminta".

Dijalankan per tenant:

    python manage.py tenant_command cleanup_uat_dataset --schema=demo
    python manage.py tenant_command cleanup_uat_dataset --schema=demo \
        --execute
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.core.services.uat_cleanup import (
    UatCleanupAborted,
    UatCleanupService,
)
from apps.core.services.uat_cleanup_demo import (
    DEMO_AUDIT_BASELINE,
    DEMO_UAT_SPEC,
)


class Command(BaseCommand):
    help = (
        "Membuang dataset UAT (pegawai, payroll, presensi, cuti, lembur, "
        "catatan alur, dan master khusus UAT) dari tenant yang dipilih. "
        "Bawaannya mode kering: tidak ada baris yang dihapus tanpa "
        "--execute."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--execute",
            action="store_true",
            help=(
                "Benar-benar menghapus. Tanpa flag ini perintah hanya "
                "melaporkan rencananya."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "Eksplisit menyatakan mode kering. Sudah jadi bawaan; "
                "disediakan supaya skrip bisa menuliskannya terang-"
                "terangan."
            ),
        )
        parser.add_argument(
            "--only",
            action="append",
            default=None,
            metavar="LABEL",
            help=(
                "Batasi pekerjaan ke label model tertentu, misalnya "
                "administration.Notification. Dipakai untuk susulan "
                "terarah sesudah pembuangan utama selesai — baseline "
                "lalu dibandingkan hanya untuk label yang dipilih, "
                "supaya penjaganya tetap hidup dan bukan dimatikan "
                "dengan --ignore-baseline."
            ),
        )
        parser.add_argument(
            "--ignore-baseline",
            action="store_true",
            help=(
                "Teruskan walau jumlah rencana berbeda dari baseline "
                "audit. Hanya dipakai kalau selisihnya sudah dijelaskan."
            ),
        )

    # ------------------------------------------------------------------

    def handle(self, *args, **options):
        execute = options["execute"]

        if execute and options["dry_run"]:
            raise CommandError(
                "--execute dan --dry-run tidak bisa dipakai bersamaan.",
            )

        spec = DEMO_UAT_SPEC

        self.stdout.write("Pembuangan dataset UAT")
        self.stdout.write(
            f"  Mode: {'EKSEKUSI (menghapus)' if execute else 'KERING'}",
        )
        self.stdout.write("")

        report = UatCleanupService.plan(spec=spec)

        only = options.get("only")

        if only:
            unknown = sorted(set(only) - set(report.planned))

            if unknown:
                raise CommandError(
                    f"Label tidak dikenal: {unknown}. Pilih dari "
                    f"{sorted(report.planned)}.",
                )

            report = self._restrict(report=report, labels=set(only))

            self.stdout.write(
                self.style.WARNING(
                    f"  Dibatasi ke: {', '.join(sorted(only))}",
                ),
            )
            self.stdout.write("")

        self._print_provenance(report)
        self._print_plan(report)

        drift = self._baseline_drift(report)

        self._print_baseline(drift)

        if report.is_blocked:
            self._print_blockers(report)

            raise CommandError(
                "Preflight gagal. Tidak ada baris yang dihapus.",
            )

        if drift and not options["ignore_baseline"]:
            self.stdout.write(
                self.style.WARNING(
                    "\n  Rencana berbeda dari baseline audit. Jelaskan "
                    "selisihnya dulu; ulangi dengan --ignore-baseline "
                    "kalau selisih itu memang diharapkan.",
                ),
            )

            if execute:
                raise CommandError(
                    "Eksekusi dihentikan karena selisih baseline.",
                )

        if not execute:
            self.stdout.write(
                self.style.SUCCESS(
                    f"\n  Mode kering. {report.planned_total} baris "
                    f"AKAN dihapus. Tidak ada yang berubah.",
                ),
            )

            return

        self._run(spec=spec, report=report, labels=set(only) if only else None)

    # ------------------------------------------------------------------

    def _restrict(self, *, report, labels):
        """
        Persempit rencana ke label terpilih.

        Yang dibuang dari laporan hanya barisnya; blocker, catatan
        provenance, dan daftar run FINALIZED tetap utuh — mempersempit
        cakupan tidak boleh sekalian mempersempit pemeriksaannya.
        """

        report.planned = {
            label: count
            for label, count in report.planned.items()
            if label in labels
        }

        return report

    def _run(self, *, spec, report, labels=None):
        try:
            result = UatCleanupService.execute(spec=spec, labels=labels)
        except UatCleanupAborted as exc:
            for blocker in exc.blockers:
                self.stdout.write(self.style.ERROR(f"  ! {blocker}"))

            raise CommandError(
                "Pembuangan dibatalkan. Transaksi di-rollback, tidak "
                "ada baris yang hilang.",
            ) from exc

        self.stdout.write("\n  Terhapus:")

        for label, count in result.deleted.items():
            if count:
                self.stdout.write(f"    {label:<34} {count:>6}")

        self.stdout.write(
            self.style.SUCCESS(
                f"\n  Selesai: {result.deleted_total} baris dibuang.",
            ),
        )

    def _print_provenance(self, report):
        self.stdout.write("  Provenance & dependency:")

        for note in report.notes:
            self.stdout.write(f"    - {note}")

        if report.finalized_runs:
            self.stdout.write("")
            self.stdout.write(
                self.style.WARNING(
                    "    PENGECUALIAN PURGE UAT — run FINALIZED ikut "
                    "dibuang:",
                ),
            )

            for item in report.finalized_runs:
                self.stdout.write(self.style.WARNING(f"      * {item}"))

            self.stdout.write(
                "      Status, finalized_at, finalized_by, dan kunci "
                "periode TIDAK diubah.",
            )
            self.stdout.write(
                "      Tidak ada run Correction yang dibuat.",
            )

        self.stdout.write("")

    def _print_plan(self, report):
        self.stdout.write("  Rencana penghapusan per model:")

        for label, count in report.planned.items():
            style = self.style.SUCCESS if count else (lambda text: text)

            self.stdout.write(f"    {label:<34} {style(f'{count:>6}')}")

        self.stdout.write(
            f"    {'TOTAL':<34} {report.planned_total:>6}",
        )

    def _baseline_drift(self, report):
        """
        Bandingkan hanya label yang benar-benar dikerjakan.

        Pada jalan terbatas, label yang tidak dipilih memang tidak ada di
        rencana — menuduhnya "selisih" cuma melatih orang mengabaikan
        peringatan ini.
        """

        drift = {}

        for label, expected in DEMO_AUDIT_BASELINE.items():
            if label not in report.planned:
                continue

            actual = report.planned[label]

            if actual != expected:
                drift[label] = (expected, actual)

        return drift

    def _print_baseline(self, drift):
        self.stdout.write("")

        if not drift:
            self.stdout.write(
                self.style.SUCCESS(
                    "  Baseline audit: COCOK pada seluruh model.",
                ),
            )

            return

        self.stdout.write(
            self.style.WARNING("  Baseline audit: SELISIH ditemukan"),
        )

        for label, (expected, actual) in drift.items():
            self.stdout.write(
                self.style.WARNING(
                    f"    {label:<34} audit={expected:<6} "
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
