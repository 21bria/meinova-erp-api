"""
Dataset peragaan Meinova ERP (GRP/MMN/MIN, EMP001–EMP040).

    python manage.py seed_demo_erp --tenant=demo --source=<xlsx> --dry-run [--reset] [--json=<berkas>]
    NOTIFICATION_EMAIL_ENABLED=False python manage.py seed_demo_erp --tenant=demo --source=<xlsx> --apply --rehearse
    NOTIFICATION_EMAIL_ENABLED=False python manage.py seed_demo_erp --tenant=demo --source=<xlsx> --apply

* `--dry-run` — perencana di dalam transaksi PostgreSQL `READ ONLY`.
* `--apply --rehearse` — seluruh penerapan dijalankan lalu **di-rollback**:
  membuktikan service kanonik menerima datanya tanpa meninggalkan apa pun.
* `--apply` — baseline DEMO-1B: berhenti di run payroll REVIEW. Tidak ada
  finalize, PAYROLL_POSTED, AccountingEvent, atau jurnal.

Penerapan menolak jalan kalau rencana punya blocker, kalau surel notifikasi
proses ini aktif, atau kalau sidik jari data terlindung berubah — yang
terakhir me-rollback seluruh transaksi.
"""

from __future__ import annotations

import json
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django_tenants.utils import schema_context

from apps.core.services.demo_erp import constants
from apps.core.services.demo_erp.guards import (
    DemoGuardError,
    diff_snapshots,
    enforce_read_only_transaction,
    protected_snapshot,
    resolve_tenant,
    verify_active_schema,
)
from apps.core.services.demo_erp.planner import build_plan
from apps.core.services.demo_erp.report import render
from apps.core.services.demo_erp.workbook import WorkbookError, load_workbook
from apps.core.services.demo_password import demo_password


class Rehearsal(Exception):
    """Dilempar untuk me-rollback gladi — bukan kegagalan."""


class Command(BaseCommand):
    help = (
        "Rencana dan penerapan baseline dataset peragaan Meinova ERP dari "
        "workbook blueprint. Tenant wajib disebut; public ditolak."
    )

    def add_arguments(self, parser):
        parser.add_argument("--tenant", help="Nama schema tenant. Wajib.")
        parser.add_argument("--source", help="Berkas .xlsx blueprint. Wajib.")
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--dry-run", action="store_true", help="Rencana saja (READ ONLY).")
        mode.add_argument("--apply", action="store_true", help="Terapkan baseline.")
        parser.add_argument(
            "--rehearse",
            action="store_true",
            help="Dengan --apply: jalankan seluruhnya lalu rollback.",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help="Rencanakan pembongkaran dataset ini (hanya baris miliknya).",
        )
        parser.add_argument(
            "--full-reset",
            action="store_true",
            help=(
                "Dengan --apply --reset: pegawai, akun, penugasan, roster, dan data pribadi "
                "EMP001–EMP040 ikut dibuang lalu dibangun ulang dari sumber."
            ),
        )
        parser.add_argument("--json", help="Tulis rencana/hasil lengkap sebagai JSON ke berkas ini.")

    # ------------------------------------------------------------------

    def handle(self, *args, **options):
        if not options["dry_run"] and not options["apply"]:
            raise CommandError("Pilih tepat satu mode: --dry-run atau --apply.")

        if options["apply"] and not constants.APPLY_ENABLED:
            raise CommandError("--apply belum diaktifkan. Butuh persetujuan eksplisit.")

        if options["rehearse"] and not options["apply"]:
            raise CommandError("--rehearse hanya berarti bersama --apply.")

        if options["full_reset"] and not (options["apply"] and options["reset"]):
            raise CommandError("--full-reset hanya berarti bersama --apply --reset.")

        if options["apply"]:
            # Akun peragaan dibentuk dengan password ini; berhenti sebelum
            # menulis apa pun kalau belum disetel.
            demo_password()

        if options["apply"] and getattr(settings, "NOTIFICATION_EMAIL_ENABLED", True):
            raise CommandError(
                "Penerapan menjalankan alur approval yang mengantrekan surel. Jalankan dengan "
                "NOTIFICATION_EMAIL_ENABLED=False (akun demoerp.* juga dimatikan surelnya)."
            )

        try:
            tenant = resolve_tenant(options.get("tenant"))
        except DemoGuardError as exc:
            raise CommandError(str(exc)) from exc

        if not options.get("source"):
            raise CommandError("--source wajib disebut.")

        try:
            workbook = load_workbook(options["source"])
        except WorkbookError as exc:
            raise CommandError(f"Workbook ditolak: {exc}") from exc

        if options["apply"]:
            return self.apply(tenant, workbook, options)

        return self.dry_run(tenant, workbook, options)

    # ------------------------------------------------------------------

    def dry_run(self, tenant, workbook, options):
        # Dari CLI koneksi selalu autocommit, jadi `atomic()` di bawah
        # membuka transaksi baru dan bisa dikunci READ ONLY sebelum kueri
        # pertama. Dipanggil dari dalam transaksi lain (test), PostgreSQL
        # menolak SET TRANSACTION sesudah ada kueri; di sana penjaganya
        # tinggal pembandingan sidik jari + rollback.
        fresh_transaction = connection.get_autocommit()

        with schema_context(tenant.schema_name):
            with transaction.atomic():
                if fresh_transaction:
                    enforce_read_only_transaction()

                self._verify_schema(tenant)
                before = protected_snapshot()
                plan = build_plan(workbook, tenant=tenant.schema_name, reset=options["reset"])
                after = protected_snapshot()

                transaction.set_rollback(True)

        changed = diff_snapshots(before, after)

        if changed:
            raise CommandError("Data terlindung berubah selama perencanaan: " + ", ".join(changed))

        digest = plan.digest()

        for line in render(plan, digest=digest):
            self.stdout.write(line)

        self.stdout.write(
            "Penjaga tulis : "
            + (
                "PostgreSQL SET TRANSACTION READ ONLY + sidik jari sebelum/sesudah"
                if fresh_transaction
                else "sidik jari sebelum/sesudah + rollback (transaksi luar)"
            )
        )

        self._write_json(options, {**plan.as_dict(), "plan_sha256": digest})

        if plan.blockers:
            raise CommandError(f"Rencana punya {len(plan.blockers)} blocker.")

        self.stdout.write(
            self.style.SUCCESS(
                f"Rencana bersih: 0 blocker, {len(plan.decisions)} keputusan menunggu, "
                f"{len(plan.warnings)} peringatan. Tidak ada yang ditulis."
            )
        )

    # ------------------------------------------------------------------

    def apply(self, tenant, workbook, options):
        from apps.core.services.demo_erp import apply as executor
        from apps.core.services.demo_erp import reset as resetter
        from apps.core.services.demo_erp import verify

        rehearse = options["rehearse"]
        report: dict = {}

        try:
            with schema_context(tenant.schema_name):
                with transaction.atomic():
                    self._verify_schema(tenant)

                    plan = build_plan(workbook, tenant=tenant.schema_name, reset=options["reset"])

                    if plan.blockers:
                        raise CommandError(
                            "PRECHECK gagal — rencana punya blocker:\n  - "
                            + "\n  - ".join(plan.blockers)
                        )

                    history_before = verify.finance_history_counts()
                    before = protected_snapshot()
                    logical_before = verify.logical_digest()
                    reset_counts = None

                    if options["reset"]:
                        self.stdout.write("-- fase reset (hanya baris milik dataset)")

                        from apps.core.services.demo_erp.legacy_cleanup import LegacyCleanupRefused

                        try:
                            if options["full_reset"]:
                                reset_counts = resetter.execute_full(log=self.stdout.write)
                            else:
                                reset_counts = resetter.execute(log=self.stdout.write)
                        except (resetter.ResetRefused, LegacyCleanupRefused) as exc:
                            raise CommandError(str(exc)) from exc

                    result = executor.run(workbook, log=self.stdout.write)

                    after = protected_snapshot()
                    changed = diff_snapshots(before, after)

                    if changed:
                        raise CommandError(
                            "Data terlindung berubah — seluruh penerapan di-rollback: "
                            + ", ".join(changed)
                        )

                    history_after = verify.finance_history_counts()

                    if history_after != history_before:
                        raise CommandError(
                            "Riwayat Finance berubah (kejadian/jurnal) — di-rollback: "
                            f"{history_before} → {history_after}"
                        )

                    companies = verify.company_set()

                    if companies != sorted(constants.OWNED_COMPANY_CODES):
                        raise CommandError(
                            f"Himpunan company sesudah penerapan {companies} ≠ "
                            f"{sorted(constants.OWNED_COMPANY_CODES)} — di-rollback."
                        )

                    runs = verify.payroll_runs()

                    if any(run["status"] == "finalized" for run in runs):
                        raise CommandError("Ada run FINALIZED — di-rollback.")

                    owned_ids = [e.pk for e in executor.owned_employees()]

                    report = {
                        "mode": "rehearsal (rollback)" if rehearse else "apply (commit)",
                        "reset": reset_counts,
                        "logical_before": logical_before,
                        "logical_after": verify.logical_digest(),
                        "population": verify.population(),
                        "companies": companies,
                        "completeness": verify.employee_completeness(),
                        "legacy_references": verify.legacy_references(),
                        "payroll_reconciliation": verify.reconcile_payroll(),
                        "plan_before_sha256": plan.digest(),
                        "phases": result.phases,
                        "documents": result.documents,
                        "unsupported": result.unsupported,
                        "notes": result.notes,
                        "finance_history_before": history_before,
                        "finance_history_after": history_after,
                        "payroll_runs": runs,
                        "payroll_lines": verify.payroll_lines(),
                        "finance_readiness": verify.finance_readiness(),
                        "finance_configuration": verify.finance_configuration(),
                        "attendance_breakdown": verify.attendance_status_breakdown(
                            owned_ids, executor.ATTENDANCE_START, executor.ATTENDANCE_END,
                        ),
                        "attendance_2026_08": verify.attendance_summary(
                            owned_ids, executor.ATTENDANCE_START, executor.date(2026, 8, 31),
                        ),
                        "attendance_2026_09": verify.attendance_summary(
                            owned_ids, executor.date(2026, 9, 1), executor.ATTENDANCE_END,
                        ),
                        "protected_before": {k: vars(v) for k, v in sorted(before.items())},
                        "protected_after": {k: vars(v) for k, v in sorted(after.items())},
                        "protected_changed": changed,
                    }

                    if rehearse:
                        raise Rehearsal()
        except Rehearsal:
            self.stdout.write(self.style.WARNING("Gladi selesai — seluruh tulisan di-rollback."))

        self._write_json(options, report)
        self._summarise(report)

    # ------------------------------------------------------------------

    def _verify_schema(self, tenant):
        try:
            verify_active_schema(tenant)
        except DemoGuardError as exc:
            raise CommandError(str(exc)) from exc

    def _write_json(self, options, payload):
        if options.get("json"):
            Path(options["json"]).write_text(json.dumps(payload, default=str, indent=2, sort_keys=True))
            self.stdout.write(f"JSON: {options['json']}")

    def _summarise(self, report):
        self.stdout.write(f"Mode: {report.get('mode')}")

        for run in report.get("payroll_runs", []):
            self.stdout.write(
                f"  run {run['document_number']} {run['company']} {run['period']} "
                f"status={run['status']} pegawai={run['employees']} net={run['total_net']}"
            )

        for entry in report.get("finance_readiness", []):
            self.stdout.write(
                f"  finance {entry['company']} {entry['period']}: ready={entry.get('ready')} "
                f"policy={entry.get('policy')} lines={entry.get('draft_lines')} "
                f"{entry.get('error', '')}"
            )

        for entry in report.get("payroll_reconciliation", []):
            self.stdout.write(
                f"  rekonsiliasi {entry['run']} {entry['company']} {entry['period']}: "
                f"baris={entry['lines']} tanpa-mata-uang={entry['lines_without_currency']} "
                f"ok={entry['reconciled']} {entry['problems'][:3]}"
            )

        if report.get("population"):
            self.stdout.write(f"  populasi pegawai: {report['population']}")

        if "companies" in report:
            self.stdout.write(f"  company: {report['companies']}  rujukan lama: {report.get('legacy_references')}")

        if report.get("completeness"):
            self.stdout.write(f"  kelengkapan (KOSONG per kolom): {report['completeness']}")

        for key in ("logical_before", "logical_after"):
            if report.get(key):
                self.stdout.write(f"  {key}: {report[key]['overall']['sha256']}")

        self.stdout.write(f"  riwayat Finance sesudah: {report.get('finance_history_after')}")
        self.stdout.write(f"  data terlindung berubah: {report.get('protected_changed')}")
        self.stdout.write(f"  tidak didukung: {report.get('unsupported')}")
