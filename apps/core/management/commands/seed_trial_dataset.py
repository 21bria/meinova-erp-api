"""
Penyemai dataset trial Fase 1.

Perintah ini tipis dengan sengaja: seluruh keputusan ada di
`TrialSeedService` dan presetnya, supaya jalur yang menulis ke tenant
bisa diuji tanpa melewati lapisan perintah.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from apps.core.services.trial_seed import TrialSeedAborted, TrialSeedService
from apps.core.services.trial_seed_demo import (
    DEMO_TRIAL_BASELINE,
    DEMO_TRIAL_SPEC,
)


class Command(BaseCommand):
    help = (
        "Menyemai fondasi dataset trial (master trial, enam pegawai, "
        "saldo awal cuti, rencana shift). Mode kering bawaan."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--execute",
            action="store_true",
            help="Benar-benar menulis. Tanpa ini, tidak ada yang berubah.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Eksplisit menyatakan mode kering (bawaan).",
        )
        parser.add_argument(
            "--ignore-baseline",
            action="store_true",
            help=(
                "Teruskan walau rencana berbeda dari baseline TRL-0B. "
                "Hanya untuk keadaan yang sudah dijelaskan."
            ),
        )

    def handle(self, *args, **options):
        execute = options["execute"]

        if execute and options["dry_run"]:
            raise CommandError(
                "--execute dan --dry-run tidak bisa dipakai bersamaan.",
            )

        spec = DEMO_TRIAL_SPEC

        self.stdout.write("Penyemaian dataset trial — Fase 1 (fondasi)")
        self.stdout.write(
            f"  Mode: {'EKSEKUSI (menulis)' if execute else 'KERING'}",
        )
        self.stdout.write("")

        report = TrialSeedService.plan(spec=spec)

        self._print_notes(report)

        if report.is_blocked:
            self._print_blockers(report)

            raise CommandError(
                "Preflight gagal. Tidak ada baris yang ditulis.",
            )

        self._print_canonical(report)
        self._print_plan(report)

        drift = self._drift(report)

        self._print_baseline(drift, already_seeded=report.already_seeded)

        if drift and not options["ignore_baseline"]:
            self.stdout.write(
                self.style.WARNING(
                    "\n  Rencana berbeda dari baseline TRL-0B. "
                    "Jelaskan selisihnya dulu.",
                ),
            )

            if execute:
                raise CommandError(
                    "Eksekusi dihentikan karena selisih baseline.",
                )

        if not execute:
            if report.already_seeded:
                self.stdout.write(
                    self.style.SUCCESS(
                        "\n  Mode kering. Trial sudah tersemai; tidak "
                        "ada yang akan dibuat.",
                    ),
                )
            else:
                self.stdout.write(
                    self.style.SUCCESS(
                        f"\n  Mode kering. {report.planned_total} baris "
                        "AKAN dibuat. Tidak ada yang berubah.",
                    ),
                )

            return

        self._run(spec=spec)

    # ------------------------------------------------------------------

    def _run(self, *, spec):
        try:
            report = TrialSeedService.execute(spec=spec)
        except TrialSeedAborted as exc:
            for blocker in exc.blockers:
                self.stdout.write(self.style.ERROR(f"    ! {blocker}"))

            raise CommandError(
                "Penyemaian dibatalkan. Seluruh perubahan dibatalkan.",
            ) from exc

        if report.already_seeded:
            self.stdout.write(
                self.style.SUCCESS(
                    "\n  Trial sudah tersemai. Tidak ada yang dibuat.",
                ),
            )

            return

        self.stdout.write("")
        self.stdout.write("  Dibuat:")

        for label, count in report.created.items():
            self.stdout.write(f"    {label:<34} {count:>6}")

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"  Selesai: {sum(report.created.values())} baris dibuat.",
            ),
        )
        self.stdout.write(f"  Manifest: {report.manifest_path}")

    def _print_notes(self, report):
        if not report.notes:
            return

        self.stdout.write("  Preflight:")

        for note in report.notes:
            self.stdout.write(f"    - {note}")

        self.stdout.write("")

    def _print_canonical(self, report):
        self.stdout.write("  Rujukan kanonik (dicari lewat kunci bisnis):")

        for label, pk in sorted(report.canonical.items()):
            self.stdout.write(f"    {label:<28} id={pk}")

        self.stdout.write("")

    def _print_plan(self, report):
        self.stdout.write("  Rencana pembuatan per model:")

        for label, count in report.planned.items():
            self.stdout.write(f"    {label:<34} {count:>6}")

        self.stdout.write(f"    {'TOTAL':<34} {report.planned_total:>6}")

    def _drift(self, report):
        if report.already_seeded:
            return {}

        drift = {}

        for label, expected in DEMO_TRIAL_BASELINE.items():
            actual = report.planned.get(label, 0)

            if actual != expected:
                drift[label] = (expected, actual)

        return drift

    def _print_baseline(self, drift, *, already_seeded=False):
        self.stdout.write("")

        if already_seeded:
            self.stdout.write(
                self.style.SUCCESS(
                    "  Baseline TRL-0B: sudah tersemai — keadaan "
                    "idempoten yang sah.",
                ),
            )

            return

        if not drift:
            self.stdout.write(
                self.style.SUCCESS(
                    "  Baseline TRL-0B: COCOK pada seluruh model.",
                ),
            )

            return

        self.stdout.write(self.style.WARNING("  Baseline TRL-0B: SELISIH"))

        for label, (expected, actual) in drift.items():
            self.stdout.write(
                self.style.WARNING(
                    f"    {label:<34} rancangan={expected:<5} "
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
