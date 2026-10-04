"""
Laporan read-only invariant custody dan pemesanan aset
(`docs/claude/assets.md` §12, §26).

    python manage.py tenant_command audit_asset_custody --schema=<tenant>

Dua pemeriksaan yang tidak bisa dijaga constraint database sendirian:

* custody — aset ACTIVE menunjuk tepat custody terbukanya, salinan
  lokasi/fasilitas sama (`AssetCustodyService.integrity_issues`);
* pemesanan — dokumen SUBMITTED/APPROVED ⇔ pemesanan terbuka, tanpa
  pemesanan yatim (`AssetReservationService.integrity_issues`).

Tidak menulis apa pun. Keluar dengan kode 1 bila ada pelanggaran, supaya
bisa dipakai sebagai gerbang.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.assets.services import AssetCustodyService, AssetReservationService


class Command(BaseCommand):
    help = "Periksa invariant custody dan pemesanan aset (read-only)."

    def handle(self, *args, **options):
        custody = AssetCustodyService.integrity_issues()
        reservations = AssetReservationService.integrity_issues()

        if not custody and not reservations:
            self.stdout.write(self.style.SUCCESS("Custody dan pemesanan aset bersih."))

            return

        for issue in custody:
            self.stdout.write(
                f"{issue['asset_code']} (#{issue['asset_id']}): {issue['problem']}"
            )

        for issue in reservations:
            self.stdout.write(
                f"aset #{issue['asset_id']} {issue['document']}: {issue['problem']}"
            )

        raise CommandError(
            f"{len(custody)} pelanggaran custody, "
            f"{len(reservations)} pelanggaran pemesanan."
        )
