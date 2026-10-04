# python manage.py tenant_command seed_payroll_config --schema=demo
from django.core.management.base import BaseCommand

from apps.payroll.seeds.payroll_config import seed_payroll_config


class Command(BaseCommand):
    help = (
        "Seed konfigurasi payroll di atas master existing. Bawaan: "
        "PTKP dan lapisan tarif PPh21 (keduanya dari peraturan). "
        "--with-components menambahkan contoh komponen "
        "tunjangan/potongan yang nominalnya DATA PERAGAAN, bukan "
        "kebijakan perusahaan. Non-destruktif — baris yang sudah ada "
        "tidak ditimpa."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--with-components",
            action="store_true",
            help=(
                "Ikut menyeed contoh komponen tunjangan/potongan. "
                "Nominalnya data peragaan, bukan aturan perusahaan."
            ),
        )

    def handle(self, *args, **kwargs):
        with_components = kwargs.get("with_components", False)

        result = seed_payroll_config(with_components=with_components)

        self.stdout.write(
            self.style.SUCCESS(
                "Payroll config seeded: "
                f"{result['allowance_components']} komponen tunjangan, "
                f"{result['deduction_components']} komponen potongan, "
                f"{result['tax_brackets']} tax bracket, "
                f"{result['ptkp']} PTKP terisi."
            ),
        )

        if not with_components:
            self.stdout.write(
                "Komponen tunjangan/potongan TIDAK diseed. Nominalnya "
                "keputusan perusahaan — isi lewat layar Allowance/"
                "Deduction Components, atau jalankan ulang dengan "
                "--with-components untuk data peragaan.",
            )
