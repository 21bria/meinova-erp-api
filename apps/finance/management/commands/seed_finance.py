"""
Menyiapkan Finance untuk satu tenant.

Urutannya bukan selera — tiap tahap membutuhkan hasil tahap sebelumnya:
dimensi berdiri sendiri, bagan akun butuh company, tahun buku butuh
company, dan contoh kebijakan butuh bagan akunnya sudah ada.
"""

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.administration.models import Company
from apps.finance.seeds import (
    seed_chart_of_accounts,
    seed_dimensions,
    seed_payroll_policy,
    seed_fiscal_years,
)


STEPS = ("dimensions", "coa", "fiscal", "policy")


class Command(BaseCommand):
    help = "Seed Finance: dimensi, bagan akun contoh, tahun buku, kebijakan PAYROLL_POSTED."

    def add_arguments(self, parser):
        parser.add_argument(
            "--only",
            choices=STEPS,
            help="Jalankan satu tahap saja.",
        )
        parser.add_argument(
            "--company",
            help="Kode company. Kosong = seluruh company di tenant ini.",
        )
        parser.add_argument(
            "--year",
            type=int,
            help="Tahun buku. Kosong = tahun berjalan.",
        )
        parser.add_argument(
            "--skip-example-policy",
            action="store_true",
            help=(
                "Tidak membuat kebijakan PAYROLL_POSTED & pemetaan "
                "akunnya. Dipakai tenant yang menyusun kebijakannya "
                "sendiri dari layar Accounting Policy."
            ),
        )

    @transaction.atomic
    def handle(self, *args, **options):
        only = options.get("only")

        companies = Company.objects.filter(is_deleted=False)

        if options.get("company"):
            companies = companies.filter(code=options["company"])

        companies = list(companies.order_by("code"))

        if not companies:
            self.stdout.write(
                self.style.ERROR(
                    "Tidak ada company di tenant ini. Jalankan seed "
                    "organisasi lebih dulu — tahun buku dan bagan akun "
                    "keduanya milik perusahaan, jadi tanpa company "
                    "seluruh tahap di bawah menulis nol baris tanpa "
                    "mengeluh."
                )
            )

            return

        if only in (None, "dimensions"):
            result = seed_dimensions()

            self.stdout.write(
                f"  Dimensions      {result['created']} baru, "
                f"{result['updated']} diperbarui"
            )

        if only in (None, "coa"):
            created = skipped = 0

            for company in companies:
                result = seed_chart_of_accounts(company=company)

                created += result["created"]
                skipped += result["skipped"]

            self.stdout.write(
                f"  Chart of Accts  {created} baru, {skipped} dilewati"
            )

        if only in (None, "fiscal"):
            result = seed_fiscal_years(
                companies=companies,
                year=options.get("year"),
            )

            self.stdout.write(
                f"  Fiscal Years    {result['fiscal_years']} baru "
                f"({result['periods']} periode), "
                f"{result['skipped']} dilewati"
            )

        if only in (None, "policy") and not options.get("skip_example_policy"):
            mappings = policies = rules = 0
            retired_policies = retired_mappings = 0

            for company in companies:
                result = seed_payroll_policy(company=company)

                mappings += result["mappings"]
                policies += result["policies"]
                rules += result["rules"]
                retired_policies += result["retired_policies"]
                retired_mappings += result["retired_mappings"]

            self.stdout.write(
                f"  Payroll Policy  {policies} kebijakan, {rules} aturan, "
                f"{mappings} pemetaan akun"
            )

            if retired_policies or retired_mappings:
                # Dilaporkan, tidak didiamkan. Yang dinonaktifkan di sini
                # baris demo milik seed versi lama — dan orang yang
                # menjalankan perintah ini harus tahu kebijakan mana yang
                # berhenti berlaku, bukan menemukannya waktu jurnalnya
                # tidak terbit.
                self.stdout.write(
                    self.style.WARNING(
                        f"  Retired demo    {retired_policies} kebijakan, "
                        f"{retired_mappings} pemetaan akun dinonaktifkan "
                        "(soft delete) karena diganti kebijakan semantik."
                    )
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Finance seed selesai untuk {len(companies)} company."
            )
        )
