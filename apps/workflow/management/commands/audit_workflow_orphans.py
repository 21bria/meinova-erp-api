"""
Memeriksa — dan kalau diminta, membuang — pengajuan alur yatim.

Kering secara bawaan. Baris hanya dihapus kalau `--fix` diketik
sengaja, dan `--fix` pun menolak menyentuh apa pun selain yang sudah
dilaporkan sebagai yatim.

    python manage.py tenant_command audit_workflow_orphans --schema=demo
    python manage.py tenant_command audit_workflow_orphans --schema=demo --fix

Dipakai sekali untuk membersihkan yatim yang sudah telanjur ada, lalu
sebagai pemeriksa rutin: reset data uji yang benar membuang pengajuan
**sebelum** dokumennya, jadi laporan yang bersih adalah bukti bahwa
urutannya masih benar.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction

from apps.workflow.services.orphans import (
    HARD,
    SOFT,
    UNKNOWN,
    duplicates,
    scan,
)


class Command(BaseCommand):
    help = (
        "Melaporkan pengajuan alur yang dokumennya hilang (hard) atau "
        "bertanda terhapus (soft). Dengan --fix, membuang pengajuan "
        "hard beserta keputusan approval-nya."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--fix",
            action="store_true",
            help=(
                "Buang pengajuan yatim HARD beserta approval-nya. "
                "Yatim SOFT tidak disentuh — dokumennya masih ada dan "
                "keputusannya milik orang."
            ),
        )
        parser.add_argument(
            "--include-soft",
            action="store_true",
            help=(
                "Ikut membuang yatim SOFT. Hanya dipakai kalau sudah "
                "diputuskan bahwa dokumen bertanda terhapus itu memang "
                "tidak akan dipulihkan."
            ),
        )

    def handle(self, *args, **options):
        schema = connection.schema_name

        if schema == "public":
            raise CommandError(
                "Perintah ini milik tenant. Jalankan lewat "
                "tenant_command --schema=<tenant>.",
            )

        self.stdout.write(f"Audit pengajuan alur — schema {schema}")

        rows = scan()

        hard = [row for row in rows if row.kind == HARD]
        soft = [row for row in rows if row.kind == SOFT]
        unknown = [row for row in rows if row.kind == UNKNOWN]
        dupes = duplicates(rows)

        self.stdout.write(f"  Pengajuan diperiksa      : {len(rows)}")
        self.stdout.write(f"  Yatim HARD               : {len(hard)}")
        self.stdout.write(f"  Yatim SOFT               : {len(soft)}")
        self.stdout.write(f"  Jenis tidak terdaftar    : {len(unknown)}")
        self.stdout.write(f"  Dokumen berpengajuan >1  : {len(dupes)}")

        for label, group in (("HARD", hard), ("SOFT", soft), ("TAK DIKENAL", unknown)):
            if not group:
                continue

            self.stdout.write("")
            self.stdout.write(f"  {label}")

            for row in group:
                self.stdout.write(
                    f"    #{row.instance_id:<5} {row.document_type:<24} "
                    f"obj={row.object_id:<6} {row.status:<10} "
                    f"{row.document_number or '(tanpa nomor)'}",
                )
                self.stdout.write(f"          {row.note}")

        if dupes:
            self.stdout.write("")
            self.stdout.write("  DUPLIKAT")

            for (module, document_type, object_id), ids in dupes.items():
                self.stdout.write(
                    f"    {module}/{document_type} obj={object_id} → "
                    f"pengajuan {ids}",
                )

        if not options["fix"]:
            self.stdout.write("")

            if hard or (soft and options["include_soft"]):
                self.stdout.write(
                    self.style.WARNING(
                        "  Mode kering. Ulangi dengan --fix untuk "
                        "membuang yang HARD.",
                    ),
                )
            else:
                self.stdout.write(self.style.SUCCESS("  Bersih."))

            return

        targets = list(hard)

        if options["include_soft"]:
            targets += soft

        if not targets:
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("  Tidak ada yang dibuang."))

            return

        # Yang dibuang **hanya** id yang barusan dilaporkan. Bukan
        # queryset yang dihitung ulang: di antara laporan dan
        # penghapusan bisa ada dokumen yang baru diajukan, dan filter
        # yang dijalankan dua kali tidak pernah menjamin himpunan yang
        # sama.
        instance_ids = [row.instance_id for row in targets]

        from apps.workflow.models import WorkflowApproval, WorkflowInstance

        with transaction.atomic():
            approvals = WorkflowApproval.objects.filter(
                instance_id__in=instance_ids,
            )

            approval_count = approvals.count()

            approvals.delete()

            instances = WorkflowInstance.objects.filter(pk__in=instance_ids)

            instance_count = instances.count()

            instances.delete()

        self.stdout.write("")
        self.stdout.write(
            self.style.SUCCESS(
                f"  Dibuang: {instance_count} pengajuan, "
                f"{approval_count} keputusan approval.",
            ),
        )
