"""
Menghitung ulang status dan menit kehadiran menurut `AttendancePolicy`.

Dibutuhkan karena **baris yang sudah ada tidak ikut berubah sendiri**
saat aturannya disunting, dan itu keputusan yang disengaja: kalau
angkanya dihitung ulang otomatis, laporan bulan lalu yang sudah dikirim
ke manajemen berubah diam-diam setiap kali seseorang menggeser satu
angka toleransi. Perubahan riwayat harus jadi tindakan yang dipilih,
dengan rentang yang disebut.
"""

from datetime import datetime

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.hr.api.attendance.permission_effect import compute_for
from apps.hr.api.attendance.permission_resolver import (
    PERMISSION_FIELDS,
)
from apps.hr.api.attendance.policy import AttendancePolicyResolver
from apps.hr.models import EmployeeAttendance


def _parse(value: str):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise CommandError(
            f"Tanggal harus berformat YYYY-MM-DD, bukan '{value}'.",
        ) from exc


FIELDS = [
    "status",
    "late_minutes",
    "early_leave_minutes",
    "overtime_minutes",
    "worked_minutes",
    "break_minutes",
]


class Command(BaseCommand):
    help = (
        "Menghitung ulang status, keterlambatan, pulang cepat, lembur, "
        "jam kerja bersih dari AttendancePolicy yang berlaku, plus "
        "klasifikasi izin (excused/unauthorized) dari Attendance "
        "Permission yang disetujui. "
        "Baris tanpa jadwal (scheduled_check_in kosong) dilewati — "
        "tidak ada jam pembanding untuk dihitung."
    )

    def add_arguments(self, parser):
        parser.add_argument("--start", type=_parse, required=True)
        parser.add_argument("--until", type=_parse, required=True)

        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Hitung saja, tidak menulis apa pun.",
        )

    def handle(self, *args, **options):
        start = options["start"]
        until = options["until"]

        if start > until:
            raise CommandError(
                "Tanggal mulai tidak boleh melewati tanggal akhir.",
            )

        rows = (
            EmployeeAttendance.objects
            .filter(
                work_date__gte=start,
                work_date__lte=until,
                is_deleted=False,
            )
            .select_related(
                "employee__organization",
                "employee__employment",
            )
            .order_by("employee_id", "work_date")
        )

        # Policy di-resolve **sekali per pegawai**, bukan per baris:
        # rentang sebulan dikali ratusan pegawai berarti ribuan
        # pencarian untuk jawaban yang sama persis.
        cache: dict[int, object] = {}

        scanned = 0
        changed = 0

        with transaction.atomic():
            for attendance in rows.iterator(chunk_size=500):
                scanned += 1

                employee_id = attendance.employee_id

                if employee_id not in cache:
                    cache[employee_id] = AttendancePolicyResolver.rules_for(
                        attendance.employee,
                    )

                computed = AttendancePolicyResolver.compute(
                    rules=cache[employee_id],
                    scheduled_check_in=attendance.scheduled_check_in,
                    scheduled_check_out=attendance.scheduled_check_out,
                    check_in=attendance.check_in,
                    check_out=attendance.check_out,
                    status=attendance.status,
                )

                # Klasifikasi izin dihitung **di luar** `if not
                # computed`, dan itu bukan gaya penulisan: baris alpa
                # tidak punya jam untuk dihitung sehingga `computed`
                # kosong — dan justru baris alpa yang paling butuh
                # dikenali sebagai "tidak masuk dengan izin". Kalau ia
                # ikut dilewati, izin sehari penuh tidak pernah
                # terbaca perintah hitung ulang.
                permissions = compute_for(
                    employee=attendance.employee,
                    work_date=attendance.work_date,
                    status=computed.get("status", attendance.status),
                    late_minutes=computed.get(
                        "late_minutes", attendance.late_minutes,
                    ),
                    early_leave_minutes=computed.get(
                        "early_leave_minutes",
                        attendance.early_leave_minutes,
                    ),
                    check_in=attendance.check_in,
                    check_out=attendance.check_out,
                )

                merged = {**computed, **permissions}

                dirty = [
                    key
                    for key, value in merged.items()
                    if getattr(attendance, key) != value
                ]

                if not dirty:
                    continue

                changed += 1

                if options["dry_run"]:
                    continue

                for key, value in merged.items():
                    setattr(attendance, key, value)

                attendance.save(
                    update_fields=[
                        *(FIELDS if computed else []),
                        *PERMISSION_FIELDS,
                        "updated_at",
                    ],
                )

            if options["dry_run"]:
                transaction.set_rollback(True)

        prefix = "[dry-run] " if options["dry_run"] else ""

        self.stdout.write(
            self.style.SUCCESS(
                f"{prefix}Hitung ulang {start} s/d {until}: "
                f"{changed} baris berubah dari {scanned} baris diperiksa."
            )
        )
