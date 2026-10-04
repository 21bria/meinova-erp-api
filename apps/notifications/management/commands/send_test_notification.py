"""
Memicu satu event notifikasi untuk memeriksa jalurnya.

    python manage.py tenant_command send_test_notification \\
        --event=hr.contract_end --schema=demo

Ini yang dipakai memastikan setelan SMTP sebuah tenant benar-benar
bekerja **sebelum** ada pengingat sungguhan yang bergantung padanya.
Tanpa perintah ini, satu-satunya cara mengetahui SMTP-nya salah setel
adalah menunggu pengingat harian jam enam pagi lalu tidak ada yang
datang — dan itu kegagalan yang tidak melapor.

Mengirim **sinkron** (`send_now`), bukan lewat antrean: yang sedang
diperiksa justru apakah SMTP-nya jalan, dan task yang mengantre lalu
gagal di worker tidak memperlihatkan pesannya di sini.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.notifications.dispatcher import notify
from apps.notifications.registry import all_events, find_event


class Command(BaseCommand):
    help = "Memicu satu event notifikasi sebagai uji coba."

    def add_arguments(self, parser):
        parser.add_argument("--event", required=True)

        parser.add_argument(
            "--employee",
            default=None,
            help=(
                "Nomor pegawai yang jadi subjek. Menentukan penerima "
                "bertipe Pegawai Bersangkutan dan penyaringan cakupan "
                "data untuk penerima bertipe role."
            ),
        )

        parser.add_argument(
            "--dedup",
            default="",
            help=(
                "Kunci dedup. Dikosongkan = tidak didedup, jadi perintah "
                "ini bisa dijalankan berkali-kali."
            ),
        )

    def handle(self, *args, **options):
        code = options["event"]

        if find_event(code) is None:
            available = "\n  ".join(item.code for item in all_events())

            raise CommandError(
                f"Event '{code}' tidak terdaftar. Yang tersedia:\n  {available}",
            )

        employee = None

        if options["employee"]:
            from apps.hr.models import Employee

            employee = (
                Employee.objects
                .select_related("user", "organization")
                .filter(employee_number=options["employee"], is_deleted=False)
                .first()
            )

            if employee is None:
                raise CommandError(
                    f"Pegawai {options['employee']} tidak ditemukan.",
                )

        spec = find_event(code)

        result = notify(
            event=code,
            # Contoh nilai dari registry — yang diuji jalur kirimnya,
            # bukan datanya.
            context=spec.sample_context(),
            subject_employee=employee,
            module=spec.module,
            dedup_key=options["dedup"],
            send_now=True,
        )

        data = result.as_dict()

        self.stdout.write(self.style.MIGRATE_HEADING(f"\nEvent: {code}"))

        for key in ("created", "sent", "skipped", "duplicates", "queued"):
            self.stdout.write(f"  {key}: {data[key]}")

        if data["reasons"]:
            self.stdout.write(
                self.style.WARNING("\nYang tidak menerima, dan sebabnya:"),
            )

            for reason in data["reasons"]:
                self.stdout.write(f"  - {reason}")

        if not data["created"]:
            self.stdout.write(
                self.style.ERROR(
                    "\nTidak ada satu penerima pun. Periksa Notification "
                    "Rules untuk event ini, dan pastikan pemegang role-nya "
                    "punya akun aktif.",
                ),
            )

            return

        self.stdout.write(
            self.style.SUCCESS(
                "\nSelesai. Rincian per penerima ada di layar "
                "Notification Log.",
            ),
        )
