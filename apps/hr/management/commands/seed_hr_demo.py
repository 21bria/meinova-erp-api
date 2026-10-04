"""
Tenant peragaan HR — perencana dan (nanti) pelaksana berjangkar.

    python manage.py tenant_command seed_hr_demo --schema=demo \
        --anchor 2026-09-25 --dry-run

Bawaannya **tidak menulis apa pun**, dan tidak ada mode "kering kalau
lupa": tanpa `--dry-run` atau `--apply` perintah berhenti dan
mengeluh. Itu disengaja — perintah yang default-nya menulis adalah
perintah yang suatu hari dijalankan di tenant yang salah.

Fase yang sudah bisa dijalankan baru **1 (fondasi)**. Fase berikutnya
punya gerbang persetujuannya sendiri.
"""

from __future__ import annotations

from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import connection


def _parse(value: str):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise CommandError(
            f"Jangkar harus berformat YYYY-MM-DD, bukan '{value}'.",
        ) from exc


class Command(BaseCommand):
    help = (
        "Merencanakan (dan dengan --apply, membangun) fondasi tenant "
        "peragaan HR untuk jendela dua bulan yang berakhir di jangkar."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--anchor",
            type=_parse,
            required=True,
            help=(
                "Tanggal rujukan (YYYY-MM-DD). Jendela = dua bulan ke "
                "belakang sampai tanggal ini."
            ),
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Laporkan rencananya. Tidak ada baris yang berubah.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Jalankan rencananya.",
        )
        parser.add_argument(
            "--reset",
            action="store_true",
            help=(
                "Izinkan pembuangan baris. Tanpa ini, langkah yang "
                "perlu membuang data berhenti dan melapor."
            ),
        )
        parser.add_argument(
            "--phase",
            type=int,
            default=1,
            help="Fase yang dijalankan. Baru 1 yang tersedia.",
        )
        parser.add_argument(
            "--decisions-approved",
            action="store_true",
            help=(
                "Keputusan yang tercantum di bagian KEPUTUSAN sudah "
                "disetujui. Tanpa ini --apply berhenti dan melapor."
            ),
        )
        parser.add_argument(
            "--set-ho-tolerance",
            action="store_true",
            help=(
                "Ikut menyetel toleransi keterlambatan kantor pusat. "
                "Dipisah karena akibatnya menimpa sejarah begitu "
                "presensi dihitung ulang — lihat catatan di "
                "hr_demo_apply.set_ho_tolerance()."
            ),
        )

    # ------------------------------------------------------------------

    def handle(self, *args, **options):
        from apps.hr.seeds.hr_demo import build

        schema = connection.schema_name

        if schema == "public":
            raise CommandError(
                "Perintah ini milik tenant. Jalankan lewat "
                "tenant_command --schema=<tenant>.",
            )

        dry = options["dry_run"]
        apply_ = options["apply"]

        if dry and apply_:
            raise CommandError(
                "--dry-run dan --apply tidak bisa dipakai bersamaan.",
            )

        if not dry and not apply_:
            raise CommandError(
                "Sebutkan --dry-run atau --apply. Tidak ada bawaan yang "
                "menulis.",
            )

        if options["phase"] != 1:
            raise CommandError(
                f"Fase {options['phase']} belum tersedia. Fase 1 "
                "(fondasi) dulu, dan tiap fase punya gerbangnya "
                "sendiri.",
            )

        plan = build(anchor=options["anchor"], schema=schema)

        self._render(plan, dry=dry, reset=options["reset"])

        if not plan.safe:
            raise CommandError(
                "Rencana TERHALANG. Tidak ada yang dijalankan.",
            )

        if dry:
            return

        if not options["decisions_approved"]:
            raise CommandError(
                "Eksekusi fase 1 menunggu keputusan yang tercantum di "
                "bagian KEPUTUSAN. Ulangi dengan "
                "--decisions-approved setelah keputusannya disetujui.",
            )

        self._apply(plan, options)

    # ------------------------------------------------------------------

    def _apply(self, plan, options):
        from django.core.management import call_command

        from apps.hr.seeds import hr_demo_apply as steps

        write = self.stdout.write

        write("")
        write("  MENJALANKAN FASE 1")

        write("")
        write("  1 · penempatan LOK006")
        lok006 = steps.fix_lok006_placement(log=write)

        write("  2 · shift yang dipensiunkan")
        shifts = steps.repoint_retired_shifts(log=write)

        write("  3 · lini TRL (nonaktif, tidak dihapus)")
        trial = steps.deactivate_trial_lineage(log=write)

        write("  4 · hari libur operasional site")
        holiday = steps.create_site_holiday(log=write)

        # Rencana roster lahir selagi orangnya masih tercatat bekerja,
        # lalu tanggal berhentinya dicatat — urutan yang sama dengan
        # yang terjadi di lapangan. Lihat catatan di hr_demo_apply.
        write("  4b · dokumen setup roster yang tinggal bangkai")
        purged = steps.purge_orphan_roster_setup(log=write)

        write("  5 · keanggotaan roster (LOK005 aktif, pegawai kantor dilepas)")
        membership = steps.normalize_roster_membership(log=write)

        write("  5b · LOK005 — melepas tanggal berhenti sementara")
        released = steps.clear_termination(log=write)

        # `try/finally`, dan itu bukan kehati-hatian berlebihan:
        # pembangunan roster berada di transaksinya sendiri, jadi
        # kegagalannya membatalkan rosternya tapi **tidak** membatalkan
        # pelepasan di langkah 5. Tanpa `finally`, satu kegagalan
        # meninggalkan pegawai yang tanggal berhentinya hilang — dan
        # itu tidak terbaca sebagai akibat dari perintah ini.
        try:
            write("  6 · membangun ulang roster site")
            call_command(
                "seed_demo_roster",
                as_of=plan.window_start,
                stagger_days=3,
                only_roster_employees=True,
                verbosity=1,
            )
        finally:
            write("  7 · LOK005 — mencatat tanggal berhenti baru")
            terminated = steps.set_future_termination(log=write)

        tolerance = {"changed": 0}

        if options["set_ho_tolerance"]:
            write("  8 · toleransi keterlambatan kantor pusat")
            tolerance = steps.set_ho_tolerance(log=write)

        write("")
        write("  RINGKASAN TULISAN")
        write(f"    LOK006 penempatan          {lok006.get('changed', 0)}")
        write(f"    kepegawaian shift dialihkan {shifts.get('changed', 0)}")
        write(f"    TRL dinonaktifkan           {trial.get('changed', 0)}")
        write(f"    hari libur site             {holiday.get('changed', 0)}")
        write(f"    setup bangkai dibuang       "
              f"{purged.get('requests', 0)} dok / {purged.get('lines', 0)} baris")
        write(f"    LOK005 diaktifkan           "
              f"{len(membership.get('reactivated', []))}")
        write(f"    pegawai kantor dilepas      "
              f"{len(membership.get('unrostered', []))}")
        write(f"    LOK005 dilepas/dicatat      "
              f"{released.get('changed', 0)}/{terminated.get('changed', 0)}")
        write(f"    toleransi kantor pusat      {tolerance.get('changed', 0)}")
        write("")
        write(self.style.SUCCESS("  FASE 1 SELESAI"))

    # ------------------------------------------------------------------

    def _render(self, plan, *, dry: bool, reset: bool):
        write = self.stdout.write

        write("=" * 66)
        write("RENCANA TENANT PERAGAAN HR — FASE 1 (FONDASI)")
        write("=" * 66)
        write(f"  Basis data : {connection.alias}")
        write(f"  Mode       : {'KERING' if dry else 'JALANKAN'}"
              f"   RESET: {'ya' if reset else 'tidak'}")

        for section in plan.sections:
            write("")
            write(f"  {section.title}")

            for line in section.lines:
                note = f"   ({line.note})" if line.note else ""

                write(f"    {line.label:<36} {line.value}{note}")

        if plan.destructive:
            write("")
            write("  YANG AKAN DIBUANG (hanya dengan --reset)")

            for label, count in plan.destructive:
                write(f"    {label:<36} {count}")

        if plan.decisions:
            write("")
            write("  KEPUTUSAN YANG DIBUTUHKAN")

            for index, item in enumerate(plan.decisions, start=1):
                write(f"    {index}. {item}")

        write("")

        if plan.blockers:
            write("  PENGHALANG")

            for item in plan.blockers:
                write(f"    - {item}")

            write("")
            write(self.style.ERROR("  HASIL: TERHALANG"))
        else:
            write(self.style.SUCCESS("  HASIL: AMAN DIJALANKAN"))

        write("=" * 66)
