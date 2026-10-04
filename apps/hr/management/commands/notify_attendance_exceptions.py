"""
Mengabarkan pengecualian presensi ke pegawai dan atasan langsungnya.

Perintah, bukan signal saat barisnya ditulis — dan itu disengaja. Satu
import fingerprint menulis ratusan baris sekaligus; mengirim surat di
dalam jalur tulis berarti satu berkas absensi menahan importnya sambil
menembak ratusan email, dan yang gagal di tengah meninggalkan separuh
orang diberi tahu.

Dijalankan berkala (harian). Aman diulang: `dedup_key` memuat id baris
presensinya, jadi satu baris menghasilkan tepat satu surat berapa kali
pun perintahnya dijalankan.

**Hari ini tidak ikut** kalau rentangnya tidak disebut. Alasannya sama
dengan `close_attendance`: tap pulang lazim baru masuk sore atau malam,
dan pengecualian yang dihitung dari baris setengah jadi akan menagih
orang yang belum pulang.

    tenant_command notify_attendance_exceptions --schema=demo
    tenant_command notify_attendance_exceptions --start=2026-08-01 --dry-run
"""

from datetime import date, timedelta

from django.core.management.base import BaseCommand

from apps.hr.api.attendance.obligation import AttendanceObligationService
from apps.hr.models import EmployeeAttendance


class Command(BaseCommand):
    help = (
        "Mengirim pemberitahuan untuk baris presensi yang menandai "
        "kewajiban cuti dan belum diselesaikan."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--start",
            type=date.fromisoformat,
            default=None,
            help="Tanggal awal (YYYY-MM-DD). Bawaan 7 hari ke belakang.",
        )

        parser.add_argument(
            "--until",
            type=date.fromisoformat,
            default=None,
            help="Tanggal akhir. Bawaan kemarin.",
        )

        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Tampilkan yang akan dikirim tanpa mengirim apa pun.",
        )

    def handle(self, *args, **options):
        until = options["until"] or (date.today() - timedelta(days=1))
        start = options["start"] or (until - timedelta(days=6))

        if start > until:
            self.stderr.write(
                self.style.ERROR("--start tidak boleh setelah --until."),
            )

            return

        rows = (
            EmployeeAttendance.objects
            .filter(
                is_deleted=False,
                work_date__gte=start,
                work_date__lte=until,
                leave_required_days__gt=0,
                # Yang sudah dibebaskan atau sudah ditinjau tidak perlu
                # dikabarkan lagi — pemberitahuan yang datang setelah
                # keputusannya diambil cuma membuat orang mengira
                # keputusannya tidak tersimpan.
                leave_required_waived=False,
                review_decision="",
                leave__isnull=True,
            )
            .select_related("employee", "leave")
            .order_by("work_date", "employee__employee_number")
        )

        sent = 0
        skipped = 0

        for attendance in rows:
            if options["dry_run"]:
                self.stdout.write(
                    f"  {attendance.work_date} "
                    f"{attendance.employee.employee_number} "
                    f"{attendance.leave_required_effective} hari "
                    f"({attendance.leave_required_reason})",
                )

                sent += 1

                continue

            if AttendanceObligationService.notify_exception(attendance):
                sent += 1
            else:
                # Policy-nya mematikan seluruh kanal. Dihitung terpisah
                # supaya "tidak ada yang dikirim" bisa dibedakan dari
                # "tidak ada yang perlu dikirim".
                skipped += 1

        prefix = "[DRY RUN] " if options["dry_run"] else ""

        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}Pengecualian presensi {start} s/d {until}: "
                f"{sent} dikabarkan, {skipped} dilewati policy.",
            ),
        )
