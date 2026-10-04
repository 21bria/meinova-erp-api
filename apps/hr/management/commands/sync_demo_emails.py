"""
Selaraskan email akun peragaan yang sudah ada dengan daftarnya.

Tidak membentuk akun, pegawai, maupun role. Lihat docstring
`apps/hr/seeds/demo_account_emails.py` untuk alasan perintah ini
berdiri sendiri di luar seed pembentuk akun.
"""

from django.core.management.base import BaseCommand

from apps.hr.seeds import demo_account_emails


class Command(BaseCommand):
    help = (
        "Perbarui email akun peragaan (`demo.*`) yang sudah ada agar "
        "cocok dengan DEMO_EMAILS. Tidak membuat akun baru dan tidak "
        "menyentuh akun sistem. "
        "Contoh: tenant_command sync_demo_emails --schema=demo"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            dest="dry_run",
            help="Tampilkan yang akan berubah tanpa menulis apa pun.",
        )

    def handle(self, *args, **options):
        dry_run = options["dry_run"]

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                "Email akun peragaan"
                + (" — DRY RUN, tidak ada yang ditulis" if dry_run else "")
            )
        )

        result = demo_account_emails.run(
            log=self.stdout.write,
            dry_run=dry_run,
        )

        if not result["changed"]:
            self.stdout.write("  (semua akun sudah sesuai)")

        self.stdout.write(
            f"\n  Akun demo   {result['total']:>3}"
            f"\n  Diperbarui  {result['changed']:>3}"
            f"\n  Sudah sesuai{result['unchanged']:>4}"
        )

        # Keadaan akhir dicetak utuh, bukan cuma yang berubah: yang mau
        # dipastikan bukan "berapa yang tersentuh" melainkan "tidak ada
        # satu pun akun peragaan yang tertinggal di domain buntu", dan
        # daftar perubahan saja tidak menjawab itu.
        self.stdout.write(
            self.style.MIGRATE_HEADING("\nPemetaan akhir")
        )

        for username, email in sorted(result["mapping"].items()):
            self.stdout.write(f"  {username:<20} {email}")

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    "\nDRY RUN — jalankan ulang tanpa --dry-run untuk "
                    "menuliskannya."
                )
            )

            return

        self.stdout.write(self.style.SUCCESS("\nSelesai."))
