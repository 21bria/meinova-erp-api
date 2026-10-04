"""
Menyiapkan tenant peragaan untuk layar Contract Expiry.

Lihat `apps/hr/seeds/demo_contract_expiry.py` untuk alasannya —
ringkasnya: tanggal cast peragaan dipatok, laporan menghitung dari hari
ini, dan keduanya menjauh satu hari tiap hari.

    tenant_command seed_contract_expiry_demo --schema=demo

Aman diulang.
"""

from django.core.management.base import BaseCommand

from apps.hr.seeds import demo_contract_expiry


class Command(BaseCommand):
    help = (
        "Jangkarkan ulang akhir kontrak pegawai peragaan ke hari ini "
        "supaya kelima bucket Contract Expiry terlihat, dan terbitkan "
        "satu dokumen perpanjangan yang masih berjalan. Aman diulang. "
        "Contoh: tenant_command seed_contract_expiry_demo --schema=demo"
    )

    def handle(self, *args, **options):
        result = demo_contract_expiry.seed(log=self.stdout.write)

        self.stdout.write(
            self.style.MIGRATE_HEADING(
                f"\nContract Expiry peragaan — as of {result['as_of']}"
            )
        )

        self.stdout.write(
            f"  {'Kontrak dijangkarkan':<26}{len(result['moved']):>3}"
        )
        self.stdout.write(
            f"  {'Dokumen renewal terbuka':<26}"
            f"{result['open_documents']:>3}"
        )

        for note in result["skipped"]:
            self.stdout.write(self.style.WARNING(f"  ! {note}"))
