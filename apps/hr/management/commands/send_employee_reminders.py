"""
Jalankan pengingat kepegawaian sekarang, tanpa menunggu penjadwal.

Dipakai untuk dua hal: mencobanya saat menyiapkan tenant baru, dan
menyusulkan pengingat pada hari ketika worker-nya mati. Aman diulang —
dedup ada di `NotificationService.push`, bukan di sini.
    python manage.py tenant_command send_employee_reminders --schema=demo
    python manage.py tenant_command send_employee_reminders --schema=demo --dry-run
"""

from django.core.management.base import BaseCommand

from apps.hr.api.dashboard.reminder_notifier import EmployeeReminderNotifier
from apps.hr.models import EmployeeReminderPolicy


class Command(BaseCommand):
    help = "Kirim pengingat tanggal kepegawaian ke notifikasi dalam aplikasi."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Hitung saja, tanpa menulis satu baris pun.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        policy = EmployeeReminderPolicy.resolve()

        if not policy.notify_hr and not policy.notify_employee:
            self.stdout.write(
                self.style.WARNING(
                    "Tidak ada penerima: notify_hr dan notify_employee "
                    "dua-duanya mati di Reminder Policy."
                )
            )

            return

        stats = EmployeeReminderNotifier.run(dry_run=dry_run)

        prefix = "[dry-run] " if dry_run else ""

        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}"
                f"{stats['written']} notifikasi untuk "
                f"{stats['recipients']} penerima HR, "
                f"{stats['self_written']} ke pegawainya sendiri."
            )
        )

        if stats["skipped_no_account"]:
            self.stdout.write(
                f"  {stats['skipped_no_account']} pegawai dilewati "
                f"karena belum punya akun."
            )
