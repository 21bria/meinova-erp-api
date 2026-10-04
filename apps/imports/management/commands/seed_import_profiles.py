# python manage.py tenant_command seed_import_profiles --schema=demo

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.imports.models import ImportProfile


PROFILES = [
    {
        "module": "hr/employees",
        "code": "EMPLOYEE-CSV-DEFAULT",
        "name": "Employee CSV (Default)",
        "description": (
            "Profil bawaan import employee. Header dicocokkan otomatis "
            "lewat daftar alias di EmployeeImporter. "
            "defaults.contract_type dipakai hanya untuk baris yang "
            "punya tanggal akhir kontrak — ganti kalau klien memakai "
            "jenis kontrak selain PKWT."
        ),
        "source_type": "csv",
        "delimiter": ",",
        "encoding": "utf-8-sig",
        "mapping": {},
        "defaults": {
            "contract_type": "PKWT",
        },
        "is_default": True,
        "sort_order": 10,
    },
    {
        "module": "hr/employees",
        "code": "EMPLOYEE-CSV-SEMICOLON",
        "name": "Employee CSV (Semicolon)",
        "description": (
            "Untuk file hasil export Excel regional Indonesia yang "
            "memakai pemisah titik koma."
        ),
        "source_type": "csv",
        "delimiter": ";",
        "encoding": "utf-8-sig",
        "mapping": {},
        "defaults": {
            "contract_type": "PKWT",
        },
        "is_default": False,
        "sort_order": 20,
    },
    {
        "module": "hr/employees",
        "code": "EMPLOYEE-CSV-US-PTKP",
        "name": "Employee CSV (US Date + PTKP)",
        "description": (
            "Untuk file export Excel berformat tanggal M/D/YYYY dengan "
            "kolom 'marital_status' yang sebenarnya berisi kode PTKP "
            "(TK/0, K/1, ...). Kolom itu dibaca dua kali: nilai aslinya "
            "masuk ke Tax Status, dan lewat value_mapping diterjemahkan "
            "jadi Marital Status. Sesuaikan defaults.payroll_group "
            "dengan grup payroll klien."
        ),
        "source_type": "csv",
        "delimiter": ",",
        "encoding": "utf-8-sig",
        "mapping": {
            "tax_status": [
                "marital_status",
                "tax_status",
                "ptkp",
            ],
        },
        "defaults": {
            "payroll_group": "MONTHLY",
            "payroll_currency": "IDR",
            "contract_type": "PKWT",
        },
        "value_mapping": {
            "marital_status": {
                "TK": "S",
                "TK/0": "S",
                "TK/1": "S",
                "TK/2": "S",
                "TK/3": "S",
                "K": "M",
                "K/0": "M",
                "K/1": "M",
                "K/2": "M",
                "K/3": "M",
            },
        },
        "datetime_formats": [
            "%m/%d/%Y",
        ],
        "is_default": False,
        "sort_order": 30,
    },
    {
        "module": "hr/leave-opening-balances",
        "code": "LEAVE-OPENING-CSV-DEFAULT",
        "name": "Leave Opening Balance CSV (Default)",
        "description": (
            "Profil bawaan import saldo awal cuti. Header dicocokkan "
            "otomatis lewat daftar alias di "
            "LeaveOpeningBalanceImporter. Isi defaults.leave_type "
            "kalau file klien tidak memuat kolom jenis cuti — lazimnya "
            "file migrasi hanya berisi saldo cuti tahunan."
        ),
        "source_type": "csv",
        "delimiter": ",",
        "encoding": "utf-8-sig",
        "mapping": {},
        "defaults": {},
        "is_default": True,
        "sort_order": 40,
    },
    {
        "module": "hr/leave-opening-balances",
        "code": "LEAVE-OPENING-CSV-US-DATE",
        "name": "Leave Opening Balance CSV (US Date)",
        "description": (
            "Untuk file export berformat tanggal M/D/YYYY. Tanpa "
            "datetime_formats, 5/2/2026 terbaca sebagai 5 Februari "
            "— tanpa error, dan tanggal berlakunya meleset tiga bulan."
        ),
        "source_type": "csv",
        "delimiter": ",",
        "encoding": "utf-8-sig",
        "mapping": {},
        "defaults": {},
        "datetime_formats": [
            "%m/%d/%Y",
        ],
        "is_default": False,
        "sort_order": 50,
    },
    {
        "module": "administration/calendar/work-calendar",
        "code": "WORK-CALENDAR-CSV-DEFAULT",
        "name": "Work Calendar CSV (Default)",
        "description": (
            "Profil bawaan import Work Calendar. Kolom scope menerima "
            "GLOBAL / COMPANY / LOCATION. Baris GLOBAL harus "
            "mengosongkan company dan location — satu baris itu berlaku "
            "untuk seluruh perusahaan, termasuk yang dibuat kemudian."
        ),
        "source_type": "csv",
        "delimiter": ",",
        "encoding": "utf-8-sig",
        "mapping": {},
        "defaults": {},
        "is_default": True,
        "sort_order": 60,
    },
    {
        "module": "administration/calendar/work-calendar",
        "code": "WORK-CALENDAR-CSV-SEMICOLON",
        "name": "Work Calendar CSV (Semicolon)",
        "description": (
            "Untuk file hasil export Excel regional Indonesia yang "
            "memakai pemisah titik koma."
        ),
        "source_type": "csv",
        "delimiter": ";",
        "encoding": "utf-8-sig",
        "mapping": {},
        "defaults": {},
        "is_default": False,
        "sort_order": 70,
    },
    {
        "module": "administration/calendar/holiday",
        "code": "HOLIDAY-CSV-DEFAULT",
        "name": "Holiday CSV (Default)",
        "description": (
            "Profil bawaan import Holiday. Kolom scope menerima "
            "GLOBAL (sinonim: NATIONAL) / COMPANY / LOCATION / "
            "SELECTED_COMPANIES. Libur nasional cukup satu baris tanpa "
            "company — jangan menulis ulang per perusahaan."
        ),
        "source_type": "csv",
        "delimiter": ",",
        "encoding": "utf-8-sig",
        "mapping": {},
        "defaults": {},
        "is_default": True,
        "sort_order": 80,
    },
    {
        "module": "administration/calendar/holiday",
        "code": "HOLIDAY-CSV-ID-DATE",
        "name": "Holiday CSV (Indonesian Date)",
        "description": (
            "Untuk file berformat tanggal DD/MM/YYYY. Tanpa "
            "datetime_formats, 05/08/2026 bisa terbaca 8 Mei — tanpa "
            "error, dan tanggal merahnya meleset tiga bulan."
        ),
        "source_type": "csv",
        "delimiter": ",",
        "encoding": "utf-8-sig",
        "mapping": {},
        "defaults": {},
        "datetime_formats": [
            "%d/%m/%Y",
        ],
        "is_default": False,
        "sort_order": 90,
    },
]


class Command(BaseCommand):
    help = "Seed generic import profiles"

    @transaction.atomic
    def handle(self, *args, **options):
        created_count = 0
        updated_count = 0

        for payload in PROFILES:
            profile, created = ImportProfile.objects.update_or_create(
                module=payload["module"],
                code=payload["code"],
                defaults=payload,
            )

            if created:
                created_count += 1
            else:
                updated_count += 1

            self.stdout.write(
                f"  {'+' if created else '~'} "
                f"{profile.module} / {profile.code}"
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Import profiles seeded "
                f"({created_count} created, {updated_count} updated)."
            )
        )
