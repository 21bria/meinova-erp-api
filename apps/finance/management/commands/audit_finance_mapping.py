"""
Mendaftar pemetaan akun yang berpotensi ambigu.

Dijalankan **sebelum** ada jurnal yang gagal karenanya. Constraint unik
sudah menangkap baris yang syarat organisasinya persis sama; yang lolos
darinya baris yang `selectors`-nya cuma berbeda urutan kunci atau huruf
besar-kecil — JSON tidak punya urutan kunci yang stabil, jadi database
tidak bisa menilainya sama.
"""

from django.core.management.base import BaseCommand

from apps.administration.models import Company
from apps.finance.services import AccountMappingService


class Command(BaseCommand):
    help = "Report ambiguous finance account mappings."

    def add_arguments(self, parser):
        parser.add_argument("--company", help="Kode company.")

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

        conflicts = AccountMappingService.detect_conflicts(
            company_id=company_id,
        )

        if not conflicts:
            self.stdout.write(
                self.style.SUCCESS("Tidak ada pemetaan akun yang ambigu.")
            )

            return

        actionable = 0

        for row in conflicts:
            codes = ", ".join(row["codes"])

            if row["same_account"]:
                # Dua baris yang menunjuk akun yang sama ambigu secara
                # teknis tapi tidak merugikan — hasilnya sama apa pun
                # yang menang. Dilaporkan sebagai catatan, bukan sebagai
                # peringatan yang menenggelamkan yang sungguhan.
                self.stdout.write(
                    f"  · {row['mapping_key']}: {row['count']} baris "
                    f"kembar ke akun yang sama ({codes})"
                )

                continue

            actionable += 1

            self.stdout.write(
                self.style.WARNING(
                    f"  ! {row['mapping_key']}: {row['count']} baris "
                    f"sama-sama cocok ke akun BERBEDA ({codes}). Jurnal "
                    "yang memakainya akan ditolak."
                )
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"{len(conflicts)} kelompok ambigu, {actionable} perlu "
                "ditindaklanjuti."
            )
            if not actionable
            else self.style.ERROR(
                f"{len(conflicts)} kelompok ambigu, {actionable} perlu "
                "ditindaklanjuti."
            )
        )
