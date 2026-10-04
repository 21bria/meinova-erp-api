"""
Membangun ulang presensi peragaan manajemen (HR-DEMO-2).

    python manage.py tenant_command seed_hr_demo_attendance \
        --schema=demo --dry-run
    python manage.py tenant_command seed_hr_demo_attendance \
        --schema=demo --apply

**Tidak ada mode bawaan yang menulis.** `--dry-run` dan `--apply` harus
disebut, dan tidak boleh bersamaan. Perintah data peragaan yang menulis
kalau modenya lupa disebut adalah perintah yang cepat atau lambat
dijalankan orang yang mengira ia cuma melihat-lihat.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from apps.hr.seeds.hr_demo_attendance import (
    WINDOW_END,
    WINDOW_START,
    build,
)
from apps.hr.seeds.hr_demo_attendance_apply import run


# Aktor bawaan: admin HR kantor pusat. Bukan `admin` superuser —
# yang mau diperagakan koreksi presensi oleh orang yang memang
# pekerjaannya, bukan oleh akun yang bisa melakukan apa saja.
DEFAULT_ACTOR = "demo.hradmin"


def _parse(value: str):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise CommandError(
            f"Tanggal harus berformat YYYY-MM-DD, bukan '{value}'.",
        ) from exc


class Command(BaseCommand):
    help = (
        "Membangun ulang presensi peragaan manajemen di jendela "
        "HR-DEMO-2: bukti mesin lewat jalur import kanonik, rekap "
        "deterministik untuk sisa hari terjadwal, mangkir lewat "
        "penutup hari bercakupan, dan satu koreksi tangan. Hanya baris "
        "milik peragaan yang dibongkar. Aman diulang."
    )

    def add_arguments(self, parser):
        parser.add_argument("--start", type=_parse, default=WINDOW_START)
        parser.add_argument("--end", type=_parse, default=WINDOW_END)

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
                "Username yang tercatat sebagai pembuat/penyunting "
                "baris. Koreksi tangan tanpa nama penyuntingnya adalah "
                "koreksi yang tidak bisa dipertanggungjawabkan siapa "
                "pun. Kosongkan dengan --actor '' kalau memang tidak "
                "ada."
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
                "Schema `public` tidak memuat data bisnis tenant. "
                "Jalankan lewat `tenant_command ... --schema=<tenant>`.",
            )

        plan = build(
            start=options["start"],
            end=options["end"],
            schema=schema,
        )

        self._report(plan, schema)

        if plan.is_blocked:
            raise CommandError(
                "Rencana terhalang. Tidak ada baris yang disentuh.",
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
            result = run(plan=plan, log=self.stdout.write, user=actor)

        self.stdout.write(
            self.style.SUCCESS(
                f"\n  Selesai: {result['imported']['created']} baris dari "
                f"bukti mesin, {result['filled']['created']} rekap, "
                f"{result['closed']['absent']} mangkir, "
                f"{result['closed']['leave']} cuti.",
            ),
        )

    # ------------------------------------------------------------------

    def _actor(self, username: str):
        username = (username or "").strip()

        if not username:
            self.stdout.write(
                self.style.WARNING(
                    "  Tanpa aktor — baris tidak akan menyebut siapa "
                    "yang membuatnya.",
                ),
            )

            return None

        from django.contrib.auth import get_user_model

        user = get_user_model().objects.filter(username=username).first()

        if user is None:
            raise CommandError(
                f"Pengguna '{username}' tidak ada di tenant ini. "
                f"Sebutkan --actor yang benar, atau --actor '' kalau "
                f"memang tidak ada.",
            )

        self.stdout.write(f"  Aktor: {user.username}")

        return user

    # ------------------------------------------------------------------

    def _report(self, plan, schema: str):
        self.stdout.write(f"Presensi peragaan — schema `{schema}`")
        self.stdout.write(f"  Jendela: {plan.start} s/d {plan.end}")
        self.stdout.write("")

        self.stdout.write(
            f"  Rombongan kanonik      : {len(plan.cast)}",
        )
        self.stdout.write(
            f"  Peserta presensi       : {len(plan.participants)}",
        )
        self.stdout.write(
            f"  Hari kerja terjadwal   : {sum(plan.schedule.values())}",
        )
        self.stdout.write("")

        self.stdout.write("  Yang dibongkar:")

        for prefix, count in sorted(plan.remove_attendance_by_prefix.items()):
            self.stdout.write(f"    {prefix:<12} {count:>6}")

        self.stdout.write(
            f"    {'TOTAL':<12} {plan.remove_attendance:>6} baris presensi",
        )
        self.stdout.write(
            f"    {'tap mentah':<12} {plan.remove_logs:>6}",
        )
        self.stdout.write("")

        origins = Counter(day.origin for day in plan.days)
        bands = Counter(day.band for day in plan.days)
        statuses = Counter(day.status for day in plan.days)
        shifts = Counter(day.shift_code for day in plan.days)

        self.stdout.write("  Yang dibangun:")
        self.stdout.write(
            f"    bukti mesin (import) : {origins.get('import', 0)}",
        )
        self.stdout.write(
            f"    rekap deterministik  : {origins.get('seed', 0)}",
        )
        self.stdout.write(
            f"    dibiarkan kosong     : {len(plan.untapped)} "
            f"(jadi mangkir lewat penutup hari)",
        )
        self.stdout.write(
            f"    TOTAL baris presensi : {len(plan.days) + len(plan.untapped)}",
        )
        self.stdout.write("")

        self.stdout.write(
            f"  HO {bands.get('HO', 0)} / Site {bands.get('SITE', 0)}",
        )

        self.stdout.write(
            "  Status: "
            + ", ".join(
                f"{name} {count}" for name, count in sorted(statuses.items())
            ),
        )

        self.stdout.write(
            "  Shift: "
            + ", ".join(
                f"{code or '-'} {count}"
                for code, count in sorted(shifts.items())
            ),
        )

        self.stdout.write(
            f"  Lintas tengah malam: "
            f"{sum(1 for day in plan.days if day.crosses_midnight)}",
        )
        self.stdout.write("")

        self.stdout.write("  Hari yang dikecualikan jadwal:")

        for label, count in plan.exclusions.items():
            self.stdout.write(f"    {label:<26} {count:>6}")

        self.stdout.write("")

        for note in plan.notes:
            self.stdout.write(self.style.WARNING(f"  - {note}"))

        if plan.foreign_rows:
            self.stdout.write("")
            self.stdout.write(
                self.style.ERROR(
                    f"  {len(plan.foreign_rows)} baris berprovenance asing "
                    f"di dalam cakupan — dipertahankan:",
                ),
            )

            for row in plan.foreign_rows[:20]:
                self.stdout.write(self.style.ERROR(f"    {row}"))

        if plan.blockers:
            self.stdout.write("")
            self.stdout.write(
                self.style.ERROR(f"  TERHALANG — {len(plan.blockers)}:"),
            )

            for blocker in plan.blockers:
                self.stdout.write(self.style.ERROR(f"    ! {blocker}"))
