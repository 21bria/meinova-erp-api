"""
Menulis ulang kolom turunan pada `JournalLine`.

`posting_date`, `accounting_period`, dan `is_posted` disalin dari
kepala dokumen saat posting. Ketiganya **penyaring**, bukan angka —
tidak satu nilai debit atau kredit pun disimpan di luar barisnya
sendiri — tapi penyaring yang salah sama buruknya dengan angka yang
salah: baris yang bertanda belum diposting tidak ikut dijumlahkan
laporan mana pun, dan hilangnya tidak berbunyi.

Perintah ini yang membuat ketiganya benar-benar turunan: kalau ia bisa
dibangun ulang kapan saja dari `finance_journal`, maka `finance_journal`
tetap satu-satunya sumber kebenaran.
"""

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import F

from apps.finance.models import (
    LEDGER_JOURNAL_STATUSES,
    Journal,
    JournalLine,
)


class Command(BaseCommand):
    help = "Rebuild denormalised posting columns on finance journal lines."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Laporkan selisihnya tanpa menulis apa pun.",
        )

    @transaction.atomic
    def handle(self, *args, **options):
        dry_run = options.get("dry_run")

        posted_ids = list(
            Journal.objects
            .filter(status__in=LEDGER_JOURNAL_STATUSES, is_deleted=False)
            .values_list("pk", flat=True)
        )

        # Yang seharusnya bertanda terposting tapi tidak.
        missing = JournalLine.objects.filter(
            journal_id__in=posted_ids,
        ).exclude(
            is_posted=True,
            posting_date=F("journal__posting_date"),
            accounting_period=F("journal__accounting_period"),
        ).count()

        # Kebalikannya: bertanda terposting padahal jurnalnya tidak.
        stale = JournalLine.objects.filter(is_posted=True).exclude(
            journal_id__in=posted_ids,
        ).count()

        self.stdout.write(
            f"  Baris yang perlu ditandai ulang : {missing}\n"
            f"  Baris bertanda basi             : {stale}"
        )

        if dry_run:
            self.stdout.write(self.style.WARNING("Dry run — tidak ada yang ditulis."))

            return

        fixed = 0

        # Per jurnal, bukan satu UPDATE untuk semuanya: nilainya
        # berbeda per dokumen, dan `F()` tidak bisa menembus relasi
        # dalam sebuah UPDATE di PostgreSQL.
        for journal in Journal.objects.filter(pk__in=posted_ids).iterator():
            fixed += JournalLine.objects.filter(journal=journal).update(
                posting_date=journal.posting_date,
                accounting_period_id=journal.accounting_period_id,
                is_posted=True,
            )

        cleared = JournalLine.objects.filter(is_posted=True).exclude(
            journal_id__in=posted_ids,
        ).update(
            is_posted=False,
            posting_date=None,
            accounting_period=None,
        )

        self.stdout.write(
            self.style.SUCCESS(
                f"{fixed} baris ditandai ulang, {cleared} tanda basi dibersihkan."
            )
        )
