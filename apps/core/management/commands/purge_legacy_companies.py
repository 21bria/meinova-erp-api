"""
Buang company peragaan lama MNI/MMR/MLS dari tenant peragaan — DEMO-1F.

    python manage.py purge_legacy_companies --tenant=demo --dry-run
    python manage.py purge_legacy_companies --tenant=demo --apply --rehearse
    python manage.py purge_legacy_companies --tenant=demo --apply

* `--dry-run` — cakupan + preflight di transaksi `READ ONLY`.
* `--apply --rehearse` — pembuangan + seluruh pemeriksaan lalu **rollback**.
* `--apply` — pembuangan nyata, semua atau tidak sama sekali.

Pemeriksaan di transaksi yang sama: jumlah baris per model (hanya cakupan
yang boleh berkurang), FK yatim (`SET CONSTRAINTS ALL IMMEDIATE`), sidik
jari logis dataset GRP/MMN/MIN (harus identik), sisa baris company lama
(harus nol), dan riwayat Finance (harus nol). Cakupan & urutan:
`apps/core/services/demo_erp/legacy_company_cleanup.py`.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django_tenants.utils import schema_context

from apps.core.services.demo_erp import legacy_company_cleanup as cleanup
from apps.core.services.demo_erp.guards import (
    DemoGuardError,
    enforce_read_only_transaction,
    resolve_tenant,
    verify_active_schema,
)


class Rehearsal(Exception):
    """Dilempar untuk me-rollback gladi — bukan kegagalan."""


class Command(BaseCommand):
    help = "Buang company peragaan lama MNI/MMR/MLS beserta konfigurasi milik eksklusifnya."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", help="Nama schema tenant. Wajib.")
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--dry-run", action="store_true")
        mode.add_argument("--apply", action="store_true")
        parser.add_argument("--rehearse", action="store_true", help="Dengan --apply: rollback di akhir.")

    def handle(self, *args, **options):
        if not options["dry_run"] and not options["apply"]:
            raise CommandError("Pilih tepat satu mode: --dry-run atau --apply.")

        if options["rehearse"] and not options["apply"]:
            raise CommandError("--rehearse hanya berarti bersama --apply.")

        try:
            tenant = resolve_tenant(options.get("tenant"))
        except DemoGuardError as exc:
            raise CommandError(str(exc)) from exc

        fresh_transaction = connection.get_autocommit()

        try:
            with schema_context(tenant.schema_name):
                with transaction.atomic():
                    if options["dry_run"] and fresh_transaction:
                        enforce_read_only_transaction()

                    verify_active_schema(tenant)
                    self._run(options)

                    if options["dry_run"]:
                        transaction.set_rollback(True)
                    elif options["rehearse"]:
                        raise Rehearsal
        except Rehearsal:
            self.stdout.write(self.style.WARNING("Gladi: seluruh transaksi di-rollback."))
            return
        except cleanup.LegacyCompanyCleanupRefused as exc:
            raise CommandError(str(exc)) from exc

        if options["apply"]:
            self.stdout.write(self.style.SUCCESS("Pembuangan di-commit."))

    def _run(self, options):
        from apps.core.services.demo_erp import verify

        write = self.stdout.write
        scope = cleanup.build_scope()

        write(f"Company lama   : {cleanup.LEGACY_COMPANY_CODES} → id {scope.company_ids}")
        write(f"Lokasi lama    : {scope.location_ids}")
        write("Cakupan (baris per model, urutan pembuangan):")
        for label, n in scope.count().items():
            write(f"   {label:40} {n}")

        problems = cleanup.preflight(scope)
        write(f"Preflight      : {'OK' if not problems else f'{len(problems)} BLOCKER'}")
        for problem in problems:
            write(f"  - {problem}")

        if options["dry_run"]:
            return

        if problems:
            raise cleanup.LegacyCompanyCleanupRefused("Preflight menolak; tidak ada yang ditulis.")

        logical_before = verify.logical_digest()
        history_before = verify.finance_history_counts()

        write("Pembuangan:")
        cleanup.execute(log=write)

        logical_after = verify.logical_digest()
        history_after = verify.finance_history_counts()
        remaining = cleanup.remaining_legacy()

        write(f"Sisa company lama     : {remaining}")
        write(f"Sidik jari logis      : {logical_before['overall']['sha256']} → {logical_after['overall']['sha256']}")
        write(f"Riwayat Finance       : {history_before} → {history_after}")

        failures = []
        if remaining != {"administration.Company": 0}:
            failures.append(f"sisa baris company lama {remaining}")
        if logical_before != logical_after:
            changed = [k for k in logical_after if logical_after[k] != logical_before.get(k)]
            failures.append(f"dataset kanonik berubah: {changed}")
        if history_after != history_before or any(history_after.values()):
            failures.append(f"riwayat Finance {history_after}")

        if failures:
            raise CommandError("Pemeriksaan pasca-pembuangan gagal — di-rollback: " + "; ".join(failures))
