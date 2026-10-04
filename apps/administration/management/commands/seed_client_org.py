"""
Menulis struktur organisasi **milik satu klien** ke sebuah tenant.

Sengaja perintah tersendiri dan tidak pernah ikut `seed_administration`.
Struktur perusahaan bukan data referensi: yang dulu terdaftar di jalur
static adalah dua belas badan usaha milik satu klien, jadi setiap tenant
yang pernah dibuat mendapatkannya — termasuk tenant peragaan yang
tangkapan layarnya masuk ke Help Center.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.administration.seeds.client import oorja_group


# Kunci pendaftaran klien. Menambah klien = satu modul dataset baru di
# `seeds/client/` plus satu baris di sini.
CLIENTS = {
    "kw": oorja_group,
}


class Command(BaseCommand):
    help = (
        "Seed struktur organisasi milik klien tertentu ke tenant yang "
        "dipilih. Tidak pernah dijalankan otomatis. "
        "Contoh: tenant_command seed_client_org --client=kw --schema=kw-prod"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--client",
            required=True,
            choices=sorted(CLIENTS),
            help="Kode klien yang datasetnya mau ditulis.",
        )

    def handle(self, *args, **options):
        module = CLIENTS.get(options["client"])

        if module is None:
            raise CommandError(f"Klien tidak dikenal: {options['client']}")

        dataset = module.DATASET

        module.seed()

        self.stdout.write(
            self.style.SUCCESS(
                f"{dataset.name}: "
                f"{len(dataset.companies)} company, "
                f"{len(dataset.locations)} location, "
                f"{len(dataset.departments)} department, "
                f"{len(dataset.sections)} section, "
                f"{len(dataset.positions)} position."
            )
        )
