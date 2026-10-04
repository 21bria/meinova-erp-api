"""
Menyambung jadwal roster yang mendekati ujung horizon-nya.

Kenapa perintah terjadwal, bukan generate sekali seumur hidup
------------------------------------------------------------
Roster tidak punya akhir — pegawai yang masih bekerja tahun depan tetap
punya siklus tahun depan. Tapi menggenerate sampai "selamanya" berarti
ribuan baris yang tidak akan pernah dibaca siapa pun, dan tiap
penyesuaian harus menghitung ulang semuanya.

Jalan tengahnya rolling horizon: tiap rencana menyimpan sampai kapan ia
berlaku (`horizon_end`), dan perintah ini menyambungnya begitu sisanya
tinggal beberapa minggu. Penyambungan **tidak menyentuh satu pun baris
yang sudah ada** — ia menempel halaman baru di bawah kalender, bukan
mencetak ulang kalendernya. Karena itu ia tidak butuh approval: tidak
ada keputusan yang dibatalkannya.

    python manage.py tenant_command extend_roster_horizon \\
        --schema=demo [--threshold-days=60] [--dry-run]

Sengaja **tidak** dijadwalkan otomatis: `django_celery_beat` masih
dikomentari di `SHARED_APPS`, dan menyalakannya adalah keputusan
tersendiri. Sampai itu terjadi, ini dijalankan cron sistem atau tangan.
"""

from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from apps.hr.api.roster.services import RosterGenerationService
from apps.hr.models import (
    ROSTER_LIVE_STATUSES,
    SiteRotation,
)


# Sisa jadwal yang dianggap "mendekati ujung". Dua bulan cukup untuk
# memesan tiket dan menyusun rotasi pengganti; di bawah itu orang mulai
# bertanya "jadwal saya bulan depan mana".
DEFAULT_THRESHOLD_DAYS = 60


class Command(BaseCommand):
    help = (
        "Menyambung jadwal roster yang horizon-nya tinggal sedikit. "
        "Aman diulang; tidak menyentuh baris yang sudah ada."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--threshold-days",
            type=int,
            default=DEFAULT_THRESHOLD_DAYS,
            help=(
                "Sambung kalau sisa jadwal kurang dari sekian hari "
                f"(bawaan {DEFAULT_THRESHOLD_DAYS})."
            ),
        )

        parser.add_argument(
            "--months",
            type=int,
            default=None,
            help=(
                "Panjang sambungan dalam bulan. Kosong = ikut "
                "rolling_horizon_months milik policy tiap rencana."
            ),
        )

        parser.add_argument(
            "--employee",
            default=None,
            help="Batasi ke satu nomor pegawai.",
        )

        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Tampilkan yang akan disambung tanpa menyimpan.",
        )

    def handle(self, *args, **options):
        threshold = options["threshold_days"]
        months = options["months"]
        dry_run = options["dry_run"]

        today = timezone.localdate()
        deadline = today + timedelta(days=threshold)

        plans = (
            SiteRotation.objects
            .filter(
                is_deleted=False,
                status__in=ROSTER_LIVE_STATUSES,
                effective_to__isnull=True,
                baseline_version__isnull=False,
                horizon_end__lt=deadline,
            )
            .select_related(
                "employee",
                "roster_policy",
                "current_version",
            )
            .order_by("employee__employee_number")
        )

        if options["employee"]:
            plans = plans.filter(
                employee__employee_number=options["employee"],
            )

        extended = 0
        skipped = 0
        failed = 0

        for plan in plans:
            label = (
                f"{plan.employee.employee_number} "
                f"({plan.document_number or f'#{plan.pk}'})"
            )

            if dry_run:
                self.stdout.write(
                    f"  {label}: horizon {plan.horizon_end} → akan "
                    "disambung."
                )

                extended += 1

                continue

            try:
                rows = RosterGenerationService.extend_horizon(
                    plan=plan,
                    months=months,
                )
            except Exception as error:  # noqa: BLE001
                failed += 1

                # Satu rencana yang gagal tidak boleh menghentikan
                # sisanya: yang lain tetap butuh jadwalnya disambung,
                # dan kegagalan di sini biasanya soal data satu orang.
                self.stdout.write(
                    self.style.ERROR(f"  {label}: {error}"),
                )

                continue

            if not rows:
                skipped += 1

                continue

            plan.refresh_from_db()

            extended += 1

            self.stdout.write(
                f"  {label}: +{len(rows)} segmen, horizon kini "
                f"{plan.horizon_end}."
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"{extended} rencana disambung"
                + (" (dry-run, tidak disimpan)" if dry_run else "")
                + f", {skipped} sudah cukup panjang, {failed} gagal."
            )
        )
