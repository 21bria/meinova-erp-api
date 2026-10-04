# python manage.py tenant_command migrate_attendance_import_profiles --schema=demo
#
# Menyalin AttendanceImportProfile lama ke ImportProfile generik.
# Aman dijalankan berulang: pencocokan lewat (module, code).
# Profile lama sengaja TIDAK dihapus supaya endpoint import attendance
# versi lama tetap bisa dipakai selama masa transisi.

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.hr.models import AttendanceImportProfile
from apps.imports.models import ImportProfile


MODULE = "hr/attendance"


class Command(BaseCommand):
    help = (
        "Copy AttendanceImportProfile rows into the generic "
        "ImportProfile table."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Tampilkan rencana tanpa menulis apa pun.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        dry_run = options.get("dry_run", False)

        sources = AttendanceImportProfile.objects.filter(
            is_deleted=False,
        ).select_related(
            "company",
            "branch",
            "location",
        )

        created_count = 0
        updated_count = 0

        for source in sources:
            payload = {
                "module": MODULE,
                "code": source.code,
                "name": source.name,
                "description": source.description or "",
                "source_type": "csv",
                "company": source.company,
                "branch": source.branch,
                "location": source.location,
                "delimiter": source.delimiter,
                "encoding": source.encoding,
                "mapping": source.mapping or {},
                "value_mapping": source.value_mapping or {},
                "datetime_formats": source.datetime_formats or [],
                "defaults": source.defaults or {},
                "is_active": source.is_active,
            }

            exists = ImportProfile.objects.filter(
                module=MODULE,
                code=source.code,
                is_deleted=False,
            ).exists()

            if dry_run:
                self.stdout.write(
                    f"  {'~' if exists else '+'} {source.code} "
                    f"- {source.name}"
                )

                continue

            _profile, created = ImportProfile.objects.update_or_create(
                module=MODULE,
                code=source.code,
                defaults=payload,
            )

            if created:
                created_count += 1
            else:
                updated_count += 1

            self.stdout.write(
                f"  {'+' if created else '~'} {source.code} "
                f"- {source.name}"
            )

        if dry_run:
            self.stdout.write(
                self.style.WARNING(
                    f"Dry run: {sources.count()} profile akan disalin.",
                )
            )

            return

        self.stdout.write(
            self.style.SUCCESS(
                f"Selesai ({created_count} dibuat, "
                f"{updated_count} diperbarui)."
            )
        )
