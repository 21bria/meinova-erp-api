"""
Membangun dokumen HR peragaan manajemen (HR-DEMO-3).

    python manage.py tenant_command seed_hr_demo_documents \
        --schema=demo --dry-run
    python manage.py tenant_command seed_hr_demo_documents \
        --schema=demo --apply

**Tidak ada mode bawaan yang menulis.** `--dry-run` dan `--apply` harus
disebut, dan tidak boleh bersamaan.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from apps.hr.seeds.hr_demo_documents import build
from apps.hr.seeds.hr_demo_documents_apply import run


DEFAULT_ACTOR = "demo.hradmin"


class Command(BaseCommand):
    help = (
        "Membangun dokumen Cuti, Izin Kehadiran, dan Lembur peragaan "
        "yang menjelaskan pengecualian presensi HR-DEMO-2, plus "
        "konfigurasi kanonik perlakuan izin dan tingkat lembur. Aman "
        "diulang."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Laporkan rencananya, jangan tulis apa pun.",
        )

        parser.add_argument(
            "--apply",
            action="store_true",
            help="Jalankan rencananya.",
        )

        parser.add_argument(
            "--actor",
            default=DEFAULT_ACTOR,
            help=(
                "Username yang bertindak sebagai HR: mencatat cuti, "
                "membatalkan catatan, dan mencatat lembur."
            ),
        )

    # ------------------------------------------------------------------

    def handle(self, *args, **options):
        dry_run = options["dry_run"]
        apply_mode = options["apply"]

        if dry_run == apply_mode:
            raise CommandError(
                "Sebutkan tepat satu mode: --dry-run atau --apply.",
            )

        schema = connection.schema_name

        if schema == "public":
            raise CommandError(
                "Schema `public` tidak memuat data bisnis tenant.",
            )

        plan = build(schema=schema)

        self._report(plan, schema)

        if plan.is_blocked:
            raise CommandError(
                "Rencana terhalang. Tidak ada dokumen yang dibuat.",
            )

        if dry_run:
            self.stdout.write(
                self.style.SUCCESS(
                    "\n  Mode kering. Tidak ada yang berubah.",
                ),
            )

            return

        actor = self._actor(options["actor"])

        self.stdout.write("\n  Menjalankan:")

        with transaction.atomic():
            result = run(plan=plan, log=self.stdout.write, hr_user=actor)

        self.stdout.write(
            self.style.SUCCESS(
                f"\n  Selesai: {len(result['leave'])} cuti, "
                f"{len(result['permission'])} izin, "
                f"{len(result['overtime'])} lembur.",
            ),
        )

    # ------------------------------------------------------------------

    def _actor(self, username: str):
        username = (username or "").strip()

        if not username:
            return None

        from django.contrib.auth import get_user_model

        user = get_user_model().objects.filter(username=username).first()

        if user is None:
            raise CommandError(
                f"Pengguna '{username}' tidak ada di tenant ini.",
            )

        self.stdout.write(f"  Aktor HR: {user.username}")

        return user

    # ------------------------------------------------------------------

    def _report(self, plan, schema: str):
        self.stdout.write(f"Dokumen HR peragaan — schema `{schema}`")
        self.stdout.write(f"  Jendela: {plan.start} s/d {plan.end}")
        self.stdout.write("")

        self.stdout.write("  Konfigurasi:")

        rules_before = plan.config.get("permission_rules_before") or []

        self.stdout.write(
            f"    aturan izin payroll : {len(rules_before)} -> "
            f"{len(plan.config.get('permission_rules_after') or [])}",
        )

        group = plan.config.get("overtime_group") or {}

        self.stdout.write(
            f"    kelompok lembur     : {group.get('code')} "
            f"basis {group.get('tier_basis_before')!r} -> "
            f"{group.get('tier_basis_after')!r}, "
            f"tingkat {len(group.get('tiers_before') or [])} -> "
            f"{len(group.get('tiers_after') or [])}",
        )

        assignments = plan.config.get("overtime_assignments") or {}

        unset = sum(1 for value in assignments.values() if value is None)

        self.stdout.write(
            f"    penempatan kelompok : {len(assignments)} pegawai, "
            f"{unset} belum berkelompok",
        )
        self.stdout.write("")

        self.stdout.write(f"  Cuti ({len(plan.leave)}):")

        for row in plan.leave:
            balance = (
                f"saldo {row['balance_before']} -> {row['balance_expected']}"
                if row["balance_before"] is not None
                else "tanpa saldo"
            )

            self.stdout.write(
                f"    {row['key']:<3} {row['employee']:<7} "
                f"{row['type']:<7} {row['start']}..{row['end']} "
                f"{str(row['days']):>4}h -> {row['target']:<10} {balance}",
            )
            self.stdout.write(f"          {row['story']}")

        self.stdout.write("")
        self.stdout.write(f"  Izin Kehadiran ({len(plan.permission)}):")

        for row in plan.permission:
            before = row["before"]
            after = row["expected"]

            self.stdout.write(
                f"    {row['key']:<4} {row['employee']:<7} {row['date']} "
                f"{row['type']:<14} "
                f"telat {before['late_minutes']}→dimaafkan "
                f"{after['excused_late_minutes']}, "
                f"cepat {before['early_leave_minutes']}→dimaafkan "
                f"{after['excused_early_leave_minutes']}, "
                f"izin {after['permission_minutes']}m, "
                f"{before['permission_state']!r}→{after['permission_state']!r}",
            )
            self.stdout.write(f"          {row['story']}")

        self.stdout.write("")
        self.stdout.write(f"  Lembur ({len(plan.overtime)}):")

        for row in plan.overtime:
            self.stdout.write(
                f"    {row['key']:<4} {row['employee']:<7} {row['date']} "
                f"{row['minutes']:>4}m ({row['hours']}h) "
                f"{row['status']:<10} paid={str(row['is_paid']):<5} "
                f"bukti={row['evidence_minutes']}m "
                f"dibaca_payroll={row['counted_by_payroll']}",
            )
            self.stdout.write(f"          {row['story']}")

        self.stdout.write("")

        for note in plan.notes:
            self.stdout.write(self.style.WARNING(f"  - {note}"))

        if plan.blockers:
            self.stdout.write("")
            self.stdout.write(
                self.style.ERROR(f"  TERHALANG — {len(plan.blockers)}:"),
            )

            for blocker in plan.blockers:
                self.stdout.write(self.style.ERROR(f"    ! {blocker}"))
