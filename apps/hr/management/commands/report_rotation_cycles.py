"""
Laporan kalkulasi siklus roster untuk satu tahun ke depan.

Dipisah dari seed supaya bisa dijalankan atas dokumen mana pun, bukan
cuma data uji: yang dibaca adalah `SiteRotation` yang tersimpan, jadi
angka yang keluar di sini persis angka yang dipakai form dan API.

Perhitungan dipotong tepat 365 hari sejak Start Date. Siklus yang belum
genap di batas itu **tidak dibuang** melainkan dihitung sebagian — kalau
dibuang, rekap tahunan pegawai berpola panjang akan tampak jauh lebih
kecil dari kenyataannya.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.core.management.base import BaseCommand

from apps.hr.models import (
    RotationPeriodType,
    SiteRotation,
)


HORIZON_DAYS = 365


def overlap_days(
    *,
    start: date,
    end: date,
    window_start: date,
    window_end: date,
) -> int:
    """Jumlah hari sebuah rentang yang jatuh di dalam jendela."""
    first = max(start, window_start)
    last = min(end, window_end)

    if last < first:
        return 0

    return (last - first).days + 1


class Command(BaseCommand):
    help = (
        "Tabel periode + rekap tahunan untuk dokumen roster. "
        "Bawaannya semua dokumen pegawai ROS* hasil "
        "seed_site_rotation_demo."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--employee",
            dest="employees",
            action="append",
            default=None,
            help=(
                "Nomor pegawai. Boleh diulang. Kosong = semua pegawai "
                "yang nomornya berawalan ROS."
            ),
        )

        parser.add_argument(
            "--horizon",
            type=int,
            default=HORIZON_DAYS,
            help=f"Panjang jendela dalam hari. Bawaan {HORIZON_DAYS}.",
        )

    def handle(self, *args, **options):
        rotations = (
            SiteRotation.objects
            .filter(is_deleted=False)
            .select_related("employee")
            .order_by("employee__employee_number")
        )

        if options["employees"]:
            rotations = rotations.filter(
                employee__employee_number__in=options["employees"],
            )
        else:
            rotations = rotations.filter(
                employee__employee_number__startswith="ROS",
            )

        if not rotations.exists():
            self.stdout.write(
                self.style.WARNING(
                    "Tidak ada dokumen roster yang cocok. Jalankan "
                    "seed_site_rotation_demo lebih dulu.",
                ),
            )

            return

        horizon = options["horizon"]

        for rotation in rotations:
            self.report(rotation=rotation, horizon=horizon)

    def report(self, *, rotation: SiteRotation, horizon: int) -> None:
        employee = rotation.employee

        window_start_bound = rotation.start_date
        window_end_bound = window_start_bound + timedelta(days=horizon - 1)

        self.stdout.write("")
        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"{employee.employee_number} — {employee.full_name}  "
                f"[{rotation.cycle_work_days} on / "
                f"{rotation.cycle_off_days} off / "
                f"{rotation.cycle_travel_days} travel]  "
                f"siklus {rotation.cycle_length} hari",
            ),
        )
        self.stdout.write(
            f"Jendela: {window_start_bound} s/d {window_end_bound} "
            f"({horizon} hari)",
        )
        self.stdout.write("")

        header = (
            f"{'#':>3}  {'Direction':<10} {'Mulai':<12} {'Selesai':<12}"
            f" {'Hari':>5} {'Dlm thn':>8}  {'Jendela travel':<28}"
        )

        self.stdout.write(header)
        self.stdout.write("-" * len(header))

        periods = (
            rotation.periods
            .filter(is_deleted=False)
            .order_by("start_date", "sequence")
            .select_related("rotation")
        )

        work_days = 0
        off_days = 0
        travel_days = 0

        cycles = 0
        partial = None

        for period in periods:
            inside = overlap_days(
                start=period.start_date,
                end=period.end_date,
                window_start=window_start_bound,
                window_end=window_end_bound,
            )

            if period.period_type == RotationPeriodType.WORK:
                label = "On Site"
                work_days += inside

                if inside:
                    cycles += 1
            else:
                label = "Off"
                off_days += inside

            full = period.day_count or 0

            if 0 < inside < full:
                partial = (period.sequence, inside, full)

            window_start = period.travel_window_start
            window_end = period.travel_window_end

            if window_start is None:
                travel_text = "-"
            else:
                span = overlap_days(
                    start=window_start,
                    end=window_end,
                    window_start=window_start_bound,
                    window_end=window_end_bound,
                )

                travel_days += span

                travel_text = (
                    f"{window_start} → {window_end} ({span}h)"
                )

            self.stdout.write(
                f"{period.sequence:>3}  {label:<10} "
                f"{str(period.start_date):<12} "
                f"{str(period.end_date):<12} "
                f"{full:>5} {inside:>8}  {travel_text:<28}",
            )

        self.stdout.write("")
        self.stdout.write(
            "Rekap 1 tahun  "
            f"kerja {work_days} hari · "
            f"off {off_days} hari · "
            f"travel {travel_days} hari · "
            f"siklus {cycles}",
        )

        total = work_days + off_days + travel_days

        self.stdout.write(
            f"               total terhitung {total} hari "
            f"dari {horizon} hari jendela "
            f"(sisa {horizon - total} hari di luar dokumen)",
        )

        if partial:
            sequence, inside, full = partial

            self.stdout.write(
                self.style.WARNING(
                    f"               periode #{sequence} terpotong "
                    f"batas tahun: {inside} dari {full} hari masuk "
                    "hitungan",
                ),
            )
