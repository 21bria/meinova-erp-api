"""
Membangun ulang `Account.path` dan `Account.level`.

Keduanya turunan dari `parent` dan ditulis `AccountService` setiap kali
induk berubah. Perintah ini ada karena turunan yang **tidak bisa
dibangun ulang** bukan turunan, melainkan sumber kebenaran kedua — dan
sumber kedua yang menyimpang dari yang pertama adalah laporan
berhierarki yang diam-diam kehilangan cabang.

Dipakai sesudah impor massal, sesudah data migration, dan kapan pun
seseorang curiga laporan "seluruh akun di bawah X" tidak lengkap.
"""

from django.core.management.base import BaseCommand

from apps.administration.models import Company
from apps.finance.services import AccountService


class Command(BaseCommand):
    help = "Rebuild the materialised path/level of the chart of accounts."

    def add_arguments(self, parser):
        parser.add_argument(
            "--company",
            help="Kode company. Kosong = seluruh company.",
        )

    def handle(self, *args, **options):
        company_id = None

        if options.get("company"):
            company = Company.objects.filter(
                code=options["company"], is_deleted=False,
            ).first()

            if company is None:
                self.stdout.write(
                    self.style.ERROR(
                        f"Company '{options['company']}' tidak ditemukan."
                    )
                )

                return

            company_id = company.pk

        touched = AccountService.rebuild_tree(company_id=company_id)

        self.stdout.write(
            self.style.SUCCESS(f"{touched} akun diperbarui jalurnya.")
        )
