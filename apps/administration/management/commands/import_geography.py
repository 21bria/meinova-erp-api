"""
Import wilayah Indonesia (Provinsi -> Kabupaten/Kota -> Kecamatan ->
Kelurahan/Desa) dari empat berkas CSV berformat `id,name`.

    python manage.py tenant_command import_geography \\
        --dir=/path/ke/csv --dry-run --schema=demo

    python manage.py tenant_command import_geography \\
        --dir=/path/ke/csv --schema=demo

**Jalankan `--dry-run` lebih dulu.** Ia membaca dan memvalidasi seluruh
berkas tanpa menyentuh database sama sekali, dan melaporkan hal yang
sama persis dengan yang akan dilaporkan import sungguhan.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.administration.imports.geography import (
    LEVEL_ORDER,
    GeographyImportService,
)
from apps.administration.imports.geography.service import (
    DEFAULT_BATCH_SIZE,
    DEFAULT_COUNTRY_CODE,
    DEFAULT_MAX_ERRORS,
)


class Command(BaseCommand):
    help = (
        "Import wilayah Indonesia dari CSV Kemendagri (provinsi, "
        "kabupaten_kota, kecamatan, kelurahan). Induk ditentukan dari "
        "awalan kode — tidak pernah dari nama. Aman diulang: "
        "identitasnya tingkat + aid, jadi import ulang berkas yang sama "
        "tidak membuat baris kedua. Pakai --dry-run untuk memvalidasi "
        "tanpa menulis apa pun."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--dir",
            required=True,
            help=(
                "Folder berisi provinsi.csv, kabupaten_kota.csv, "
                "kecamatan.csv, kelurahan.csv."
            ),
        )

        parser.add_argument(
            "--dry-run",
            action="store_true",
            help=(
                "Baca + validasi saja. Tidak ada satu baris pun yang "
                "ditulis, diubah, atau dihapus."
            ),
        )

        parser.add_argument(
            "--level",
            action="append",
            choices=list(LEVEL_ORDER),
            help=(
                "Batasi ke tingkat tertentu (boleh diulang). Urutannya "
                "tetap dari induk ke anak, apa pun urutan penulisannya."
            ),
        )

        parser.add_argument(
            "--country",
            default=DEFAULT_COUNTRY_CODE,
            help=(
                f"Kode Country induk seluruh provinsi. Bawaan "
                f"'{DEFAULT_COUNTRY_CODE}'. Yang sudah ada dipakai "
                f"ulang, tidak pernah diduplikasi."
            ),
        )

        parser.add_argument(
            "--batch-size",
            type=int,
            default=DEFAULT_BATCH_SIZE,
            help=f"Ukuran batch bulk insert/update (bawaan {DEFAULT_BATCH_SIZE}).",
        )

        parser.add_argument(
            "--max-errors",
            type=int,
            default=DEFAULT_MAX_ERRORS,
            help=(
                f"Jumlah error yang ditampilkan per tingkat (bawaan "
                f"{DEFAULT_MAX_ERRORS}). Penghitungnya tetap utuh."
            ),
        )

    def handle(self, *args, **options):
        dry_run = bool(options["dry_run"])

        try:
            result = GeographyImportService.run(
                directory=options["dir"],
                levels=options.get("level"),
                dry_run=dry_run,
                batch_size=options["batch_size"],
                max_errors=options["max_errors"],
                country_code=options["country"],
            )
        except (FileNotFoundError, ValueError) as exc:
            raise CommandError(str(exc)) from exc

        self._report(result, dry_run=dry_run)

        if result["has_errors"]:
            self.stdout.write(
                self.style.WARNING(
                    "\nAda baris yang ditolak. Baris yang valid tetap "
                    "diproses — perbaiki yang ditolak lalu jalankan "
                    "ulang; yang sudah benar akan terlewati sebagai "
                    "Skipped."
                    if not dry_run
                    else "\nAda baris yang ditolak. Perbaiki dulu "
                    "sebelum menjalankan tanpa --dry-run."
                )
            )

    # ------------------------------------------------------------------
    # Laporan
    # ------------------------------------------------------------------

    def _report(self, result: dict, *, dry_run: bool) -> None:
        title = (
            "DRY RUN — tidak ada perubahan pada database"
            if dry_run
            else "IMPORT SELESAI"
        )

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING(title))
        self.stdout.write(f"Country: {result['country']}")
        self.stdout.write("")

        if dry_run:
            header = f"{'Level':<18}{'Total':>9}{'Valid':>9}{'Invalid':>9}"
        else:
            header = (
                f"{'Level':<18}{'Total':>9}{'Created':>9}"
                f"{'Updated':>9}{'Skipped':>9}{'Errors':>9}"
            )

        self.stdout.write(header)
        self.stdout.write("-" * len(header))

        for level in result["levels"]:
            if dry_run:
                line = (
                    f"{level['label']:<18}"
                    f"{level['total']:>9}"
                    f"{level['valid']:>9}"
                    f"{level['invalid']:>9}"
                )
            else:
                line = (
                    f"{level['label']:<18}"
                    f"{level['total']:>9}"
                    f"{level['created']:>9}"
                    f"{level['updated']:>9}"
                    f"{level['skipped']:>9}"
                    f"{level['error_count']:>9}"
                )

            style = (
                self.style.ERROR
                if level["invalid"]
                else self.style.SUCCESS
            )

            self.stdout.write(style(line))

        self._report_errors(result)

    def _report_errors(self, result: dict) -> None:
        for level in result["levels"]:
            if not level["errors"]:
                continue

            self.stdout.write("")
            self.stdout.write(
                self.style.ERROR(
                    f"{level['label']} — {level['error_count']} baris "
                    f"ditolak:"
                )
            )

            for item in level["errors"]:
                self.stdout.write(
                    f"  baris {item['row']}: "
                    f"code={item['code'] or '(kosong)'} "
                    f"name={item['name'] or '(kosong)'} "
                    f"parent={item['parent_code'] or '-'} "
                    f"-> {item['error']}"
                )

            hidden = level["error_count"] - len(level["errors"])

            if hidden > 0:
                self.stdout.write(
                    f"  ... {hidden} error lain tidak ditampilkan "
                    f"(naikkan --max-errors untuk melihatnya)."
                )
