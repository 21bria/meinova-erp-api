"""
Data uji untuk Attendance Import: dua Import Profile, dua device, dan
pemetaan nomor mesin -> pegawai.

    python manage.py tenant_command seed_attendance_import_demo --schema=demo

Dua profile dengan sengaja **berbeda bentuk filenya**, bukan berbeda
lokasinya: satu file berpemisah koma yang membawa IN/OUT eksplisit, satu
file berpemisah TAB yang cuma berisi tap mentah. Itulah yang benar-benar
membedakan dua mesin di lapangan. Kalau nanti ada yang menulis
`if profile.code == ...` di kode importer, yang salah adalah kodenya —
nama profile di sini cuma label.

Aman dijalankan berulang: profile dicocokkan lewat `(module, code)`,
device lewat `code`, pemetaan lewat `(device, external_employee_id)`.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.hr.api.attendance.schedule import is_roster
from apps.hr.models import (
    AttendanceDevice,
    AttendanceDeviceEmployee,
    Employee,
)
from apps.imports.models import ImportProfile


MODULE = "hr/attendance"


# Profil kanonik — kolomnya **persis** yang dikeluarkan tombol Download
# Template (`AttendanceImporter.template_columns`).
#
# Ada dan jadi bawaan karena ketiadaannya sudah sekali membuat orang
# terjebak: mereka mengunduh template, mengisinya, mengunggahnya, lalu
# ditolak — karena satu-satunya profile bawaan waktu itu mencari kolom
# `timestamp` sementara templatenya menulis `log_time`. Template dan
# profile bawaan yang tidak sepakat adalah jebakan yang tidak berbunyi.
#
# `mapping` sengaja **kosong**: alias bawaan `AttendanceImporter` sudah
# mengenali seluruh nama kanonik plus sinonim yang lazim.
PROFILE_CANONICAL = {
    "module": MODULE,
    "code": "ATT-CSV-STANDARD",
    "name": "Attendance CSV (Standard template)",
    "description": (
        "The format produced by Download Template: employee_code, "
        "log_time, log_type, device_code. One row per tap. Start here "
        "when the machine export can be reshaped, or when testing."
    ),
    "source_type": "csv",
    "delimiter": ",",
    "encoding": "utf-8-sig",
    "mapping": {},
    "value_mapping": {},
    "datetime_formats": [
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d %H:%M",
    ],
    "defaults": {},
    "options": {
        "attendance": {
            "timezone": "Asia/Jakarta",
            "row_mode": "raw_tap",
            "event_mode": "auto",
        },
    },
    "is_default": True,
    "sort_order": 5,
}


# Profil A — file berpemisah koma, membawa kolom IN/OUT vendor yang
# nilainya angka. Terjemahan 0/1 -> in/out ada di `value_mapping`,
# bukan di parser.
PROFILE_COMMA = {
    "module": MODULE,
    "code": "ATT-CSV-COMMA-INOUT",
    "name": "Attendance CSV (Comma, explicit IN/OUT)",
    "description": (
        "Comma-separated export with an explicit event column. The "
        "vendor writes 0 for check in and 1 for check out; the "
        "translation lives in value_mapping, not in code."
    ),
    "source_type": "csv",
    "delimiter": ",",
    "encoding": "utf-8-sig",
    # Nama kanonik ikut didaftarkan di tiap target. Alias yang
    # ditimpa **mengganti** daftar bawaan, jadi menyebut `timestamp`
    # saja diam-diam membuang `log_time` — dan file yang memakai nama
    # kanonik jadi ditolak oleh profile yang kelihatannya cocok.
    "mapping": {
        "employee_code": [
            "employeecode",
            "employee_code",
            "pin",
        ],
        "log_time": [
            "timestamp",
            "datetime",
            "log_time",
        ],
        "log_type": [
            "status",
            "inout",
            "type",
            "log_type",
        ],
        "employee_name": ["name", "employee_name"],
    },
    "value_mapping": {
        "log_type": {
            "0": "in",
            "1": "out",
            "i": "in",
            "o": "out",
        },
    },
    "datetime_formats": [
        "%Y-%m-%d %H:%M:%S",
    ],
    "defaults": {},
    "options": {
        "attendance": {
            "timezone": "Asia/Jakarta",
            "event_mode": "explicit",
            "device_code": "FP-HO-01",
            "identifier": {
                "match_employee_number": True,
            },
        },
    },
    "is_default": False,
    "sort_order": 10,
}


# Profil B — file berpemisah TAB tanpa IN/OUT sama sekali, dan nomor
# mesinnya tidak berhubungan dengan Employee Number. Bentuk file inilah
# yang keluar dari mesin sidik jari yang dipakai di site.
PROFILE_TAB = {
    "module": MODULE,
    "code": "ATT-CSV-TAB-RAWTAP",
    "name": "Attendance CSV (Tab, raw tap)",
    "description": (
        "Tab-separated fingerprint export. Every row is a raw tap "
        "without IN/OUT, timestamps look like 03/07/2026 07.28.54, and "
        "the machine ID is not the ERP employee number — it is "
        "resolved through Attendance Device Employee Mapping."
    ),
    "source_type": "csv",
    "delimiter": "\t",
    "encoding": "utf-8-sig",
    "mapping": {
        "employee_code": ["no.id"],
        "log_time": ["tgl/waktu"],
        "employee_name": ["nama"],
        "department": ["departemen"],
    },
    "value_mapping": {},
    "datetime_formats": [
        "%d/%m/%Y %H.%M.%S",
        "%d/%m/%Y %H.%M",
    ],
    "defaults": {},
    "options": {
        "attendance": {
            "timezone": "Asia/Jakarta",
            "event_mode": "raw_tap",
            "device_code": "FP-SITE-01",
            "identifier": {
                "column": "No.ID",
                # Tanpa pemetaan device yang cocok, nomor mesinnya
                # dicoba apa adanya sebagai Employee Number. Tidak ada
                # awalan yang ditebak di sini dengan sengaja.
                "match_employee_number": True,
            },
        },
    },
    "is_default": False,
    "sort_order": 20,
}


# Profil C — satu baris per HARI, bukan per tap. Mesin yang mengekspor
# rekap harian mengeluarkan bentuk ini: tanggal, nomor pegawai, jam
# masuk, jam pulang, semuanya di satu baris. `row_mode` yang
# membedakannya dari dua profile di atas — bukan importer yang lain.
PROFILE_DAILY = {
    "module": MODULE,
    "code": "ATT-CSV-DAILY-INOUT",
    "name": "Attendance CSV (Daily in/out per row)",
    "description": (
        "One row per employee per work date, carrying the date plus "
        "check in and check out times in separate columns. Each row "
        "produces up to two taps; a row with only one of the two is "
        "flagged Incomplete Day rather than completed by guesswork."
    ),
    "source_type": "csv",
    "delimiter": ",",
    "encoding": "utf-8-sig",
    "mapping": {
        "employee_code": ["no"],
        "attendance_date": ["ymd"],
        "check_in": ["work1"],
        "check_out": ["work2"],
        "employee_name": ["name"],
        "department": ["depart"],
        "remark": ["remark"],
    },
    "value_mapping": {},
    "datetime_formats": [],
    "defaults": {},
    "options": {
        "attendance": {
            "timezone": "Asia/Jakarta",
            "row_mode": "daily_in_out",
            "date_formats": ["%Y/%m/%d", "%Y-%m-%d", "%d/%m/%Y"],
            "time_formats": ["%H:%M", "%H:%M:%S"],
            "device_code": "FP-HO-01",
            "identifier": {
                "column": "no",
                "match_employee_number": True,
            },
        },
    },
    "is_default": False,
    "sort_order": 30,
}


DEVICES = [
    {
        "code": "FP-HO-01",
        "name": "Head Office Fingerprint 01",
        "profile_code": PROFILE_COMMA["code"],
        "roster": False,
    },
    {
        "code": "FP-SITE-01",
        "name": "Site Fingerprint 01",
        "profile_code": PROFILE_TAB["code"],
        "roster": True,
    },
]


# Berapa pegawai per device yang dibuatkan pemetaan. Cukup untuk UAT;
# bukan angka yang punya arti bisnis.
MAPPING_LIMIT = 12


class Command(BaseCommand):
    help = (
        "Seed demo attendance import profiles, devices, and device "
        "employee mappings."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--prefix",
            action="append",
            default=None,
            help=(
                "Awalan nomor pegawai data uji. Boleh diulang. "
                "Bawaan: HO dan SGA, sama dengan seed data uji lain."
            ),
        )

    @transaction.atomic
    def handle(self, *args, **options):
        prefixes = options.get("prefix") or ["HO", "SGA"]

        profiles = {}

        for payload in (
            PROFILE_CANONICAL,
            PROFILE_COMMA,
            PROFILE_TAB,
            PROFILE_DAILY,
        ):
            profile, created = ImportProfile.objects.update_or_create(
                module=payload["module"],
                code=payload["code"],
                defaults=payload,
            )

            profiles[payload["code"]] = profile

            self.stdout.write(
                f"  {'+' if created else '~'} profile "
                f"{profile.code} - {profile.name}"
            )

        employees = self._employees(prefixes)

        if not employees:
            self.stdout.write(
                self.style.WARNING(
                    "Tidak ada pegawai data uji "
                    f"({'/'.join(prefixes)}*) — device dan pemetaan "
                    "dilewati.",
                )
            )

            return

        pools = self._pools(employees)

        for spec in DEVICES:
            pool = pools[bool(spec["roster"])]

            if not pool:
                self.stdout.write(
                    self.style.WARNING(
                        f"  ! {spec['code']} dilewati — tidak ada "
                        f"pegawai yang cocok.",
                    )
                )

                continue

            device = self._device(spec, pool[0], profiles)

            self._map_employees(device, pool[:MAPPING_LIMIT])

        self.stdout.write(
            self.style.SUCCESS("Attendance import demo seeded."),
        )

    # ------------------------------------------------------------------

    def _pools(self, employees):
        """
        `{False: pegawai device kantor, True: pegawai device site}`.

        Pembagian utamanya pola kerja — roster ke device site, kantor ke
        device kantor. Tenant data uji yang **belum** punya pegawai
        roster tetap harus bisa dipakai UAT, jadi daftarnya dibelah dua
        sebagai cadangan: yang mau ditunjukkan justru bahwa nomor mesin
        `0001` di dua device menunjuk dua orang berbeda, dan itu tidak
        butuh roster.
        """
        roster = [e for e in employees if is_roster(e)]
        office = [e for e in employees if not is_roster(e)]

        if roster and office:
            return {False: office, True: roster}

        available = roster or office

        half = max(len(available) // 2, 1)

        self.stdout.write(
            self.style.WARNING(
                "  ! Hanya satu jenis pola kerja di tenant ini — "
                "daftar pegawai dibelah dua untuk kedua device.",
            )
        )

        return {False: available[:half], True: available[half:]}

    def _employees(self, prefixes):
        from django.db.models import Q

        condition = Q()

        for prefix in prefixes:
            condition |= Q(employee_number__startswith=prefix)

        return list(
            Employee.objects
            .filter(condition, is_active=True, is_deleted=False)
            .select_related(
                "organization__company",
                "organization__branch",
                "organization__location",
                "employment",
            )
            .order_by("employee_number")
        )

    def _device(self, spec, sample_employee, profiles):
        organization = getattr(sample_employee, "organization", None)

        device, created = AttendanceDevice.objects.update_or_create(
            code=spec["code"],
            defaults={
                "name": spec["name"],
                "company": organization.company,
                "branch": getattr(organization, "branch", None),
                "location": getattr(organization, "location", None),
                "import_profile": profiles.get(spec["profile_code"]),
                "is_active": True,
            },
        )

        self.stdout.write(
            f"  {'+' if created else '~'} device {device.code} "
            f"-> {spec['profile_code']}"
        )

        return device

    def _map_employees(self, device, employees):
        created_count = 0

        wanted = {
            f"{index:04d}"
            for index in range(1, len(employees) + 1)
        }

        # Jalan ulang dengan daftar pegawai yang lebih pendek tidak boleh
        # meninggalkan pemetaan yatim: nomor mesin yang tidak lagi
        # dipakai seed ini dibuang, dan device demo memang hanya berisi
        # data seed.
        stale = (
            AttendanceDeviceEmployee.objects
            .filter(device=device, is_deleted=False)
            .exclude(external_employee_id__in=wanted)
        )

        removed, _ = stale.delete()

        for index, employee in enumerate(employees, start=1):
            # Nomor mesin sengaja **tidak** diturunkan dari Employee
            # Number: yang mau ditunjukkan data uji ini justru nomor
            # mesin yang tidak berhubungan dengan master.
            external_id = f"{index:04d}"

            _mapping, created = (
                AttendanceDeviceEmployee.objects.update_or_create(
                    device=device,
                    external_employee_id=external_id,
                    is_deleted=False,
                    defaults={
                        "employee": employee,
                        "is_active": True,
                    },
                )
            )

            created_count += int(created)

        self.stdout.write(
            f"      {len(employees)} pemetaan "
            f"({created_count} baru, {removed} dibuang)"
        )
