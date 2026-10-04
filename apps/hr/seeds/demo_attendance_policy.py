"""
Aturan kehadiran tenant peragaan: kantor pusat dan site, berdampingan.

Sengaja **bukan** di `seed_attendance_policy` (seed bawaan). Yang di
sana hanya `ATT-STD` global tanpa toleransi, dan itu keputusan yang
benar: berapa menit keterlambatan boleh dimaafkan tidak diatur
undang-undang mana pun, jadi angka bawaan di master lebih berbahaya
daripada tidak ada angka — orang menganggapnya sudah divalidasi.
Pelajaran yang sama dengan `SICK-STD` 30 hari yang ditarik dari seed
jatah cuti.

Di tenant peragaan angkanya justru harus ada, karena yang mau
diperlihatkan persis inilah: **satu tenant, dua aturan, dan yang
menentukan mana yang berlaku adalah cakupannya, bukan urutan barisnya.**

    ATT-STD        cakupan kosong            skor 0  ← yang tidak punya aturan sendiri
    ATT-MMR-HO     MMR + Jakarta Head Office skor 6
    ATT-MMR-SITE   MMR + Sagea Mine          skor 6

Kosong berarti "berlaku untuk semua", **bukan** "tidak berlaku" — itu
jebakan paling gampang di layar settingnya.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import transaction

from apps.administration.models import (
    AttendancePolicy,
    Company,
    LeaveType,
    Location,
)


COMPANY_CODE = "MMR"

HO_LOCATION_CODE = "JKT-HO"
SITE_LOCATION_CODE = "SAGEA-MINE"


POLICIES = [
    {
        "code": "ATT-MMR-HO",
        "name": "Kantor Pusat — Jakarta",
        "location": HO_LOCATION_CODE,
        "description": (
            "Jam kerja 10:00–18:00 (shift OFFICE-10). Toleransi satu "
            "menit; telat lebih dari dua jam dianggap mengambil "
            "setengah hari cuti, begitu juga pulang lebih dari dua jam "
            "lebih awal."
        ),
        "late_tolerance_minutes": 1,
        "late_counts_from_tolerance": True,
        "early_leave_tolerance_minutes": 1,
        # Dua jam. Ambangnya dinilai terhadap **jam jadwal**, bukan
        # terhadap menit telat yang sudah dipotong toleransi — kalau
        # tidak, mengubah toleransi ikut menggeser ambang ini tanpa ada
        # yang menyadarinya.
        "late_leave_threshold_minutes": 120,
        "early_leave_leave_threshold_minutes": 120,
        "leave_deduction_days": Decimal("1.0"),
        "overtime_threshold_minutes": 30,
        "break_minutes": 60,
        "sort_order": 20,
    },
    {
        "code": "ATT-MMR-SITE",
        "name": "Site — Sagea Mine",
        "location": SITE_LOCATION_CODE,
        "description": (
            "Jam kerja 07:00–17:00 (shift SITE). Tanpa toleransi: "
            "orangnya tinggal di mess, tidak ada perjalanan yang bisa "
            "terlambat. Tanpa ambang cuti — yang tidak masuk di site "
            "diurus lewat roster dan travel request, bukan lewat "
            "potongan setengah hari."
        ),
        "late_tolerance_minutes": 0,
        "late_counts_from_tolerance": True,
        "early_leave_tolerance_minutes": 0,
        "late_leave_threshold_minutes": 0,
        "early_leave_leave_threshold_minutes": 0,
        "leave_deduction_days": Decimal("1.0"),
        "overtime_threshold_minutes": 30,
        "break_minutes": 60,
        "sort_order": 30,
    },
]


@transaction.atomic
def run(*, log=print) -> dict:
    company = Company.objects.filter(
        code=COMPANY_CODE,
        is_deleted=False,
    ).first()

    if company is None:
        return {"written": 0, "skipped": [f"Company {COMPANY_CODE} belum ada."]}

    locations = {
        row.code: row
        for row in Location.objects.filter(
            company=company,
            is_deleted=False,
        )
    }

    # Jenis cuti yang dipotong. Wajib begitu ambangnya menyala —
    # "wajib ambil cuti" tanpa menyebut saldo yang mana tidak bisa
    # dieksekusi, dan `clean()` menolaknya.
    annual = (
        LeaveType.objects
        .filter(code__iexact="ANNUAL", is_deleted=False)
        .first()
    )

    written = 0
    skipped: list[str] = []

    for row in POLICIES:
        location = locations.get(row["location"])

        if location is None:
            skipped.append(
                f"{row['code']} — lokasi {row['location']} belum ada."
            )
            continue

        defaults = {
            key: value
            for key, value in row.items()
            if key not in {"code", "location"}
        }

        defaults["company"] = company
        defaults["location"] = location
        defaults["is_active"] = True
        defaults["is_deleted"] = False

        if row.get("late_leave_threshold_minutes") or row.get(
            "early_leave_leave_threshold_minutes",
        ):
            if annual is None:
                skipped.append(
                    f"{row['code']} — master LeaveType ANNUAL belum ada. "
                    f"Jalankan `seed_administration --only=hr-reference`.",
                )

                continue

            defaults["leave_type"] = annual

        policy, _ = AttendancePolicy.objects.update_or_create(
            code=row["code"],
            defaults=defaults,
        )

        # Dijalankan supaya pertentangan antar-angka ketahuan di sini,
        # bukan nanti sebagai potongan cuti yang tidak bisa dijelaskan.
        policy.full_clean()

        written += 1

        log(
            f"  {policy.code:14} {policy.name:26} "
            f"toleransi {policy.late_tolerance_minutes}m, "
            f"ambang cuti {policy.late_leave_threshold_minutes or '-'}m, "
            f"potong {policy.leave_deduction_days} hari"
        )

    return {"written": written, "skipped": skipped}
