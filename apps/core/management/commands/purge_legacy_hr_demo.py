"""
Buang kelompok pegawai non-kanonik dari tenant peragaan — DEMO-1D.

    python manage.py purge_legacy_hr_demo --tenant=demo [--target=legacy-hr-demo|trl] --dry-run
    python manage.py purge_legacy_hr_demo --tenant=demo [--target=…] --apply --rehearse
    python manage.py purge_legacy_hr_demo --tenant=demo [--target=…] --apply

* `--target=legacy-hr-demo` (bawaan) — pemeran HR-DEMO BOD/HO/SGA/LOK.
* `--target=trl` — dataset trial TRL01–TRL06 + master eksklusifnya.

* `--dry-run` — cakupan + preflight di transaksi `READ ONLY`.
* `--apply --rehearse` — seluruh pembuangan + pemeriksaan lalu **rollback**.
* `--apply` — pembuangan nyata, semua atau tidak sama sekali.

Sesudah pembuangan, di transaksi yang sama: pemeriksaan yatim atas seluruh
kolom FK ke pegawai/akun yang dibuang, dan pembandingan sidik jari data
terlindung. Bagian yang **boleh** berubah hanya yang memang memuat baris
sasaran (dihitung ulang tanpa baris sasaran dan harus identik); bagian lain
berubah = rollback. Detail cakupan: `apps/core/services/demo_erp/legacy_cleanup.py`.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.db.models import Q
from django_tenants.utils import schema_context

from apps.core.services.demo_erp import legacy_cleanup
from apps.core.services.demo_erp.guards import (
    DemoGuardError,
    diff_snapshots,
    enforce_read_only_transaction,
    fingerprint,
    protected_snapshot,
    resolve_tenant,
    verify_active_schema,
)


class Rehearsal(Exception):
    """Dilempar untuk me-rollback gladi — bukan kegagalan."""


_CAST = frozenset({
    "cast.employee", "cast.organization", "cast.employment", "cast.payroll_assignment",
    "cast.attendance", "cast.attendance_log", "cast.leave", "cast.attendance_permission",
    "cast.overtime",
})

#: Bagian sidik jari yang memuat baris sasaran — berubah memang disengaja,
#: per sasaran. Selebihnya berubah = rollback.
EXPECTED_CHANGED = {
    "legacy-hr-demo": _CAST | {
        "rbac.user.existing", "rbac.role_assignment.existing",
        "rbac.role_authority.existing", "payroll.period.other", "payroll.run.other",
    },
    "trl": _CAST | {"payroll.overtime_group", "payroll.policy"},
}


def residual_snapshot(scope) -> dict:
    """
    Bagian `EXPECTED_CHANGED` tanpa baris sasaran. Harus identik sebelum
    dan sesudah — membuktikan yang tersisa (TRL, akun lain, run lain) tidak
    ikut tersentuh.
    """
    from apps.core.services.demo_erp.guards import protected_querysets

    excluded = {
        "employee": Q(pk__in=scope.employee_ids),
        "employee_of": Q(employee_id__in=scope.employee_ids),
        "user": Q(pk__in=scope.user_ids),
        "user_of": Q(user_id__in=scope.user_ids),
        "authority_of": Q(assignment__user_id__in=scope.user_ids),
        "run": Q(pk__in=scope.run_ids),
        "period": Q(pk__in=scope.period_ids),
        "overtime_group": Q(pk__in=scope.master_ids.get("payroll.OvertimeGroup", [])),
        "policy": Q(pk__in=scope.master_ids.get("payroll.PayrollPolicy", [])),
    }
    how = {
        "cast.employee": "employee", "rbac.user.existing": "user",
        "rbac.role_assignment.existing": "user_of", "rbac.role_authority.existing": "authority_of",
        "payroll.run.other": "run", "payroll.period.other": "period",
        "payroll.overtime_group": "overtime_group", "payroll.policy": "policy",
    }
    querysets = protected_querysets()

    return {
        name: fingerprint(querysets[name].exclude(excluded[how.get(name, "employee_of")]))
        for name in sorted(EXPECTED_CHANGED[scope.target.key])
    }


def travel_day_snapshot():
    """`RosterTravelDay` di luar `updated_by` (yang disetujui menjadi NULL)."""
    from apps.administration.models import RosterTravelDay
    from apps.core.services.demo_erp.guards import EXCLUDED_DIGEST_COLUMNS
    import hashlib
    import json

    columns = [
        f.attname for f in RosterTravelDay._meta.concrete_fields
        if f.attname not in EXCLUDED_DIGEST_COLUMNS | {"updated_by_id"}
    ]
    rows = list(RosterTravelDay._base_manager.order_by("pk").values_list(*columns))

    return len(rows), hashlib.sha256(json.dumps(rows, default=str, sort_keys=True).encode()).hexdigest()


class Command(BaseCommand):
    help = "Buang pemeran HR-DEMO lama (BOD/HO/SGA/LOK) beserta data milik eksklusifnya."

    def add_arguments(self, parser):
        parser.add_argument("--tenant", help="Nama schema tenant. Wajib.")
        mode = parser.add_mutually_exclusive_group()
        mode.add_argument("--dry-run", action="store_true")
        mode.add_argument("--apply", action="store_true")
        parser.add_argument("--rehearse", action="store_true", help="Dengan --apply: rollback di akhir.")
        parser.add_argument(
            "--target", choices=sorted(legacy_cleanup.TARGETS), default=legacy_cleanup.LEGACY_HR_DEMO.key,
        )

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
        except legacy_cleanup.LegacyCleanupRefused as exc:
            raise CommandError(str(exc)) from exc

        if options["apply"]:
            self.stdout.write(self.style.SUCCESS("Pembuangan di-commit."))

    def _run(self, options):
        write = self.stdout.write
        target = legacy_cleanup.TARGETS[options["target"]]
        scope = legacy_cleanup.build_scope(target)
        expected = EXPECTED_CHANGED[target.key]

        write(f"Sasaran         : {target.key}")
        write(f"Pegawai sasaran : {len(scope.found_numbers)} dari {len(target.numbers)} disetujui")
        write(f"  {', '.join(scope.found_numbers)}")
        write(f"Akun            : {len(scope.user_ids)}")
        write(f"Run payroll     : {scope.run_ids}  periode: {scope.period_ids}")
        write(f"Instance alur   : {len(scope.instance_ids)}  setup roster: {scope.setup_request_ids}")
        write(f"Avatar          : {scope.avatar_file_ids}")
        write(f"Master eksklusif: {scope.master_ids}")

        problems = legacy_cleanup.preflight(scope)
        write(f"Preflight       : {'OK' if not problems else f'{len(problems)} BLOCKER'}")
        for problem in problems:
            write(f"  - {problem}")

        if options["dry_run"] or problems:
            if problems and options["apply"]:
                raise legacy_cleanup.LegacyCleanupRefused("Preflight menolak; tidak ada yang ditulis.")
            return

        before = protected_snapshot()
        residual_before = residual_snapshot(scope)
        travel_before = travel_day_snapshot()

        write("Pembuangan:")
        legacy_cleanup.execute(log=write, target=target)

        orphans = legacy_cleanup.orphan_check(scope)
        after = protected_snapshot()
        residual_after = residual_snapshot(scope)
        travel_after = travel_day_snapshot()

        changed = diff_snapshots(before, after)
        unexpected = sorted(set(changed) - expected)
        residual_changed = diff_snapshots(residual_before, residual_after)

        write(f"Yatim           : {'0' if not orphans else orphans}")
        write(f"Sidik jari berubah (disengaja) : {sorted(set(changed) & expected)}")
        write(f"Sidik jari berubah (TAK TERDUGA): {unexpected or 'tidak ada'}")
        write(f"Sisa non-sasaran berubah       : {residual_changed or 'tidak ada'}")
        write(f"RosterTravelDay tanpa updated_by: {'identik' if travel_before == travel_after else 'BERUBAH'} {travel_after[0]} baris")

        if orphans or unexpected or residual_changed or travel_before != travel_after:
            raise CommandError("Pemeriksaan pasca-pembuangan gagal — seluruh transaksi di-rollback.")
