"""
Menutup hari presensi dari baris perintah.

`--employee` dan `--employee-prefix` menyempitkan cakupan ke pegawai
yang disebut. Tanpa keduanya perintah ini berperilaku persis seperti
sebelumnya — seluruh pegawai yang punya kewajiban presensi, disaring
`--company`/`--location` kalau disebut.

Nomor yang tidak ketemu **menghentikan** perintah. Diam-diam melewati
nomor yang salah ketik berarti melaporkan "0 tidak hadir" untuk
pegawai yang sebenarnya tidak pernah diperiksa, dan angka nol itu
terbaca persis seperti angka nol yang benar.
"""

from datetime import datetime

from django.core.management.base import BaseCommand, CommandError

from apps.hr.api.attendance.closing import AttendanceClosingService
from apps.hr.models import Employee


def _parse(value: str):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise CommandError(
            f"Tanggal harus berformat YYYY-MM-DD, bukan '{value}'.",
        ) from exc


class Command(BaseCommand):
    help = (
        "Menutup hari presensi: hari yang terjadwal tapi tidak punya "
        "catatan kehadiran ditulis sebagai Absent — atau Leave kalau "
        "tertutup dokumen cuti yang sudah disetujui. Tidak pernah "
        "menimpa baris yang sudah ada, jadi aman diulang. Bawaannya "
        "berhenti kemarin: hari yang masih berjalan belum bisa disebut "
        "mangkir."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--until",
            type=_parse,
            default=None,
            help="Hari terakhir yang ditutup. Bawaan: kemarin.",
        )

        parser.add_argument(
            "--start",
            type=_parse,
            default=None,
            help=(
                "Hari pertama yang ditutup. "
                "Bawaan: tanggal 1 di bulan `--until`."
            ),
        )

        parser.add_argument(
            "--company",
            type=int,
            default=None,
            help="Batasi ke satu company (id).",
        )

        parser.add_argument(
            "--location",
            type=int,
            default=None,
            help="Batasi ke satu location (id).",
        )

        parser.add_argument(
            "--employee",
            dest="employee",
            action="append",
            default=None,
            metavar="EMPLOYEE_NUMBER",
            help=(
                "Batasi ke pegawai tertentu (nomor pegawai). Boleh "
                "diulang. Nomor yang tidak ketemu menghentikan "
                "perintah."
            ),
        )

        parser.add_argument(
            "--employee-prefix",
            dest="employee_prefix",
            action="append",
            default=None,
            metavar="PREFIX",
            help=(
                "Batasi ke pegawai yang nomornya berawalan ini. Boleh "
                "diulang. Awalan yang tidak menjaring siapa pun "
                "menghentikan perintah."
            ),
        )

        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Hitung saja, tidak menulis apa pun.",
        )

    # ------------------------------------------------------------------

    def _scope(self, options):
        """
        Daftar id pegawai yang diminta, atau `None` kalau tidak dibatasi.

        `None` dan daftar kosong **bukan** hal yang sama di sini, dan
        perbedaannya sengaja tidak bisa terjadi tanpa disadari: yang
        pertama hanya lahir kalau tidak ada satu pun penyaring pegawai
        yang disebut, dan yang kedua tidak pernah sampai ke service
        karena perintah ini berhenti lebih dulu.
        """
        numbers = options.get("employee") or []
        prefixes = options.get("employee_prefix") or []

        if not numbers and not prefixes:
            return None

        ids: set[int] = set()

        if numbers:
            found = dict(
                Employee.objects
                .filter(is_deleted=False, employee_number__in=numbers)
                .values_list("employee_number", "id"),
            )

            missing = sorted(set(numbers) - set(found))

            if missing:
                raise CommandError(
                    f"Nomor pegawai tidak ketemu: {', '.join(missing)}.",
                )

            ids.update(found.values())

        for prefix in prefixes:
            matched = list(
                Employee.objects
                .filter(is_deleted=False, employee_number__startswith=prefix)
                .values_list("id", flat=True),
            )

            if not matched:
                raise CommandError(
                    f"Awalan '{prefix}' tidak menjaring satu pegawai pun.",
                )

            ids.update(matched)

        return sorted(ids)

    # ------------------------------------------------------------------

    def handle(self, *args, **options):
        employees = self._scope(options)

        if employees is not None:
            self.stdout.write(
                self.style.WARNING(
                    f"  Cakupan dibatasi ke {len(employees)} pegawai.",
                ),
            )

        result = AttendanceClosingService.close(
            start=options["start"],
            end=options["until"],
            company=options["company"],
            location=options["location"],
            employees=employees,
            dry_run=options["dry_run"],
            log=self.stdout.write,
        )

        prefix = "[dry-run] " if options["dry_run"] else ""

        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}Penutupan {result['start']} s/d {result['end']}: "
                f"{result['absent']} tidak hadir, "
                f"{result['leave']} cuti, "
                f"{result.get('business_trip', 0)} dinas, dari "
                f"{result['scanned']} hari terjadwal "
                f"({result['employees']} pegawai)."
            )
        )
