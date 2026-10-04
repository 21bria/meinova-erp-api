"""
Menyeed template email bawaan untuk satu tenant.

    python manage.py tenant_command seed_notification_templates --schema=demo

Aman diulang. Template yang sudah disunting orang dilewati, kecuali
`--overwrite`.
"""

from django.core.management.base import BaseCommand

from apps.notifications.seeds.templates import run


class Command(BaseCommand):
    help = "Menyeed template email bawaan dari registry event notifikasi."

    def add_arguments(self, parser):
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help=(
                "Timpa juga template yang sudah disunting orang. "
                "Dipakai kalau kalimat bawaannya diperbaiki dan tenant "
                "memang ingin kembali ke bawaan."
            ),
        )

    def handle(self, *args, **options):
        stats = run(overwrite=options["overwrite"])

        self.stdout.write(
            self.style.SUCCESS(
                f"Template notifikasi: {stats['created']} dibuat, "
                f"{stats['updated']} diperbarui, "
                f"{stats['skipped_edited']} dilewati karena sudah disunting.",
            ),
        )

        if stats["skipped_edited"] and not options["overwrite"]:
            self.stdout.write(
                "  Pakai --overwrite kalau memang ingin mengembalikannya "
                "ke kalimat bawaan.",
            )
