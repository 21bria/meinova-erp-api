"""
Pelaksana fase 1 tenant peragaan HR — koreksi fondasi.

Dipisah dari `hr_demo.py` dengan sengaja: perencana di sana tidak
mengimpor satu pun service penulis, dan jaminan "laporan kering tidak
bisa menulis" hanya berlaku selama pemisahan itu dipertahankan.

Yang dikerjakan di sini persis enam hal, dan tidak satu pun menyentuh
mesin roster, mesin presensi, atau modul Finance:

1. penempatan `LOK006` yang tidak konsisten;
2. kepegawaian yang menunjuk shift yang sudah dipensiunkan;
3. lini TRL dinonaktifkan (bukan dihapus);
4. hari libur operasional site;
5. toleransi keterlambatan kantor pusat;
6. urutan penonaktifan/pengaktifan tanggal berhenti `LOK005` di sekitar
   pembangunan roster.

Nomor enam butuh penjelasan, karena bentuknya aneh kalau tidak dibaca
alasannya. `RosterSetupService.candidates()` membuang **siapa pun yang
punya tanggal berhenti**, bukan siapa pun yang sudah berhenti:

    .exclude(employment__termination_date__isnull=False)

Jadi memindahkan tanggal berhenti ke masa depan tidak membuat orangnya
jadi kandidat — kolomnya terisi, dan itu saja yang dilihat penyaringnya.
Yang benar bukan menembus penyaring itu, melainkan **mengikuti urutan
yang sebenarnya terjadi di lapangan**: orang dijadwalkan dulu selagi
masih bekerja, lalu tanggal berhentinya dicatat belakangan. Itu yang
dilakukan di sini, dan rencananya tetap lahir dari dokumen setup yang
sama dengan buatan pengguna.
"""

from __future__ import annotations

from datetime import date


# Keputusan fase 1, dinyatakan sebagai data supaya bisa dibaca ulang
# dan dibandingkan dengan laporannya — bukan tersebar sebagai angka di
# tengah kode.
# Penempatan lengkap, bukan sebagian. `OrganizationAssignment.clean()`
# menagih seluruh rantai konsisten — memindahkan lokasi dan departemen
# saja ditolak, karena divisi, jabatan, dan cost center yang tertinggal
# masih milik pohon kantor pusat. Penolakan itu benar, dan daftar di
# bawah adalah jawabannya: satu pohon utuh, disalin dari rekan sedepartemen
# (`LOK005`, mekanik di bawah supervisor yang sama).
LOK006_PLACEMENT = {
    "employee_number": "LOK006",
    "location_code": "SAGEA-MINE",
    "division_code": "OPS",
    "department_code": "PLANT",
    "section_code": "PLANT_MECH",
    # `demo.elec1` — listrik, bukan mekanik. Jabatannya ada di master.
    "position_code": "MMR-ELEC",
    "cost_center_code": "MMR-PLANT",
}

LOK005_TERMINATION = {
    "employee_number": "LOK005",
    "new_date": date(2026, 10, 10),
}

SITE_HOLIDAY = {
    "date": date(2026, 9, 4),
    "code": "SITE-SAFETY-STANDDOWN-2026",
    "name": "Sagea Mine Safety Stand-Down",
    "location_code": "SAGEA-MINE",
}

HO_POLICY = {
    "code": "ATT-MMR-HO",
    "late_tolerance_minutes": 15,
}

TRIAL_PREFIX = "TRL"

# Pegawai **kantor** yang tempat kerjanya di site.
#
# Ia bukan pegawai roster: jadwalnya dari Work Calendar, bukan dari
# blok rotasi. Dinyatakan di sini karena `RosterSetupService.candidates()`
# sengaja tidak membedakannya — penyaring itu menawarkan siapa pun yang
# belum punya rencana, termasuk orang yang memang tidak pernah perlu
# punya. Tanpa daftar ini, satu commit mengubah pegawai kantor jadi
# pegawai roster tanpa keputusan siapa pun.
NON_ROSTER_SITE_EMPLOYEES = ("HO008",)

# Shift pengganti untuk kepegawaian yang masih menunjuk master yang
# sudah dipensiunkan. Dipilih lewat **kode**, bukan id: id berbeda di
# tiap tenant, kode tidak.
RETIRED_SHIFT_REPLACEMENT = {
    "SITE-DAY": "DAY",
    "OFFICE": "OFFICE-10",
}


def _by_code(model, code, **extra):
    return model.objects.filter(is_deleted=False, code=code, **extra).first()


# ----------------------------------------------------------------------
# 1 · Penempatan LOK006
# ----------------------------------------------------------------------

def fix_lok006_placement(*, log=print) -> dict:
    """
    Pegawai roster yang penempatannya di kantor pusat.

    `LOK006` memegang Roster Policy dan melapor ke Plant Supervisor di
    site, tapi `OrganizationAssignment`-nya menyebut kantor pusat dan
    departemen Direksi. Akibatnya ia tidak pernah muncul sebagai
    kandidat Roster Setup — penyaringnya memakai lokasi — dan presensi
    yang sudah ada untuknya tidak berpijak pada jadwal mana pun.

    Dikoreksi **sebelum** jendela peragaan dimulai, jadi ini bukan
    mutasi di tengah periode: seluruh jendela melihat satu penempatan
    yang sama.
    """
    from apps.administration.models import (
        CostCenter,
        Department,
        Division,
        Location,
        Position,
        Section,
    )
    from apps.hr.models import Employee

    employee = Employee.objects.filter(
        is_deleted=False,
        employee_number=LOK006_PLACEMENT["employee_number"],
    ).first()

    if employee is None:
        return {"changed": 0, "note": "LOK006 tidak ditemukan."}

    organization = getattr(employee, "organization", None)

    if organization is None:
        return {"changed": 0, "note": "LOK006 belum punya penempatan."}

    company = organization.company

    location = _by_code(
        Location, LOK006_PLACEMENT["location_code"], company=company,
    )
    division = _by_code(
        Division, LOK006_PLACEMENT["division_code"], company=company,
    )
    department = _by_code(
        Department, LOK006_PLACEMENT["department_code"], company=company,
    )
    section = _by_code(
        Section,
        LOK006_PLACEMENT["section_code"],
        company=company,
        department=department,
    ) if department else None
    position = _by_code(
        Position, LOK006_PLACEMENT["position_code"], company=company,
    )
    cost_center = _by_code(
        CostCenter, LOK006_PLACEMENT["cost_center_code"], company=company,
    )

    missing = [
        name
        for name, value in (
            ("location", location),
            ("division", division),
            ("department", department),
            ("section", section),
            ("position", position),
            ("cost_center", cost_center),
        )
        if value is None
    ]

    if missing:
        return {
            "changed": 0,
            "note": f"Master belum lengkap: {', '.join(missing)}.",
        }

    before = {
        "location": getattr(organization.location, "code", None),
        "division": getattr(organization.division, "code", None),
        "department": getattr(organization.department, "code", None),
        "section": getattr(organization.section, "code", None),
        "position": getattr(organization.position, "code", None),
        "cost_center": getattr(organization.cost_center, "code", None),
    }

    organization.location = location
    organization.division = division
    organization.department = department
    organization.section = section
    organization.position = position
    organization.cost_center = cost_center

    # Penempatan berlaku sejak sebelum jendela, bukan sejak hari ini —
    # kalau tidak, laporan yang membaca tanggal efektif akan mengira
    # orangnya baru pindah minggu ini.
    organization.organization_effective_date = min(
        organization.organization_effective_date or date(2026, 7, 25),
        date(2026, 7, 25),
    )

    organization.full_clean()
    organization.save()

    after = {
        "location": location.code,
        "division": division.code,
        "department": department.code,
        "section": section.code,
        "position": position.code,
        "cost_center": cost_center.code,
    }

    log(f"  LOK006 {before} → {after}")

    return {"changed": 1, "before": before, "after": after}


# ----------------------------------------------------------------------
# 2 · Shift yang sudah dipensiunkan
# ----------------------------------------------------------------------

def repoint_retired_shifts(*, log=print) -> dict:
    """
    Kepegawaian yang masih menunjuk master Shift bertanda terhapus.

    `resolve_shift()` membaca `employment.shift` tanpa menyaring
    `is_deleted`, jadi jam kerjanya tetap terhitung — dari master yang
    tidak muncul di layar mana pun. Angkanya benar dan sumbernya tidak
    bisa ditemukan siapa pun; itu bentuk kesalahan yang paling mahal.

    Yang diperbaiki di sini **datanya**, bukan mesinnya. Menyaring
    `is_deleted` di `resolve_shift()` mengubah perilaku seluruh tenant
    dan butuh gerbangnya sendiri.
    """
    from apps.administration.models import Shift
    from apps.hr.models import EmploymentAssignment

    retired = {
        row.pk: row.code
        for row in Shift.objects.filter(is_deleted=True)
    }

    if not retired:
        return {"changed": 0}

    changed = 0
    detail: dict[str, int] = {}

    for old_id, old_code in retired.items():
        replacement_code = RETIRED_SHIFT_REPLACEMENT.get(old_code)

        if replacement_code is None:
            continue

        replacement = _by_code(Shift, replacement_code)

        if replacement is None:
            continue

        rows = EmploymentAssignment.objects.filter(
            is_deleted=False, shift_id=old_id,
        )

        count = rows.count()

        if not count:
            continue

        rows.update(shift=replacement)

        changed += count
        detail[f"{old_code} → {replacement_code}"] = count

        log(f"  {count} kepegawaian: {old_code} → {replacement_code}")

    return {"changed": changed, "detail": detail}


# ----------------------------------------------------------------------
# 3 · Lini TRL
# ----------------------------------------------------------------------

def deactivate_trial_lineage(*, log=print) -> dict:
    """
    Lini uji teknis dinonaktifkan, **tidak** dihapus.

    `is_active=False` sudah cukup untuk mengeluarkannya dari jalur
    peragaan: `PayrollSourceService.eligible_employees()` dan
    `RosterSetupService.candidates()` dua-duanya menyaringnya. Barisnya
    tetap ada beserta manifest dan masternya, karena `test_trl_readiness`
    masih membuktikan angka dari data itu.
    """
    from apps.hr.models import Employee

    rows = Employee.objects.filter(
        is_deleted=False,
        employee_number__startswith=TRIAL_PREFIX,
        is_active=True,
    )

    numbers = list(rows.values_list("employee_number", flat=True))

    changed = rows.update(is_active=False)

    if changed:
        log(f"  {changed} pegawai TRL dinonaktifkan: {', '.join(numbers)}")

    return {"changed": changed, "employees": numbers}


# ----------------------------------------------------------------------
# 4 · Hari libur operasional site
# ----------------------------------------------------------------------

def create_site_holiday(*, log=print) -> dict:
    """
    Satu hari libur **tingkat lokasi**, dinyatakan perusahaan sendiri.

    Bukan klaim kalender nasional, dan dokumentasinya tidak boleh
    menyebutnya begitu: `scope=LOCATION`, `source=MANUAL`,
    `is_national=False`. Gunanya membuktikan bahwa kantor pusat dan
    site boleh punya kalender operasional yang berbeda — tanpa satu
    baris pun seperti ini, perbedaan itu cuma klaim di dokumen.
    """
    from apps.administration.models import Holiday, HolidayScope, Location

    location = _by_code(Location, SITE_HOLIDAY["location_code"])

    if location is None:
        return {"changed": 0, "note": "Lokasi site tidak ditemukan."}

    existing = Holiday.objects.filter(
        is_deleted=False,
        code=SITE_HOLIDAY["code"],
        date=SITE_HOLIDAY["date"],
    ).first()

    if existing is not None:
        return {"changed": 0, "note": "Sudah ada.", "id": existing.pk}

    holiday = Holiday(
        scope=HolidayScope.LOCATION,
        company=location.company,
        location=location,
        date=SITE_HOLIDAY["date"],
        code=SITE_HOLIDAY["code"],
        name=SITE_HOLIDAY["name"],
        is_national=False,
        is_recurring=False,
    )

    holiday.full_clean()
    holiday.save()

    log(f"  Hari libur {holiday.date} {holiday.code} ({location.code})")

    return {"changed": 1, "id": holiday.pk}


# ----------------------------------------------------------------------
# 5 · Toleransi kantor pusat
# ----------------------------------------------------------------------

def set_ho_tolerance(*, log=print) -> dict:
    """
    Toleransi keterlambatan kantor pusat 1 → 15 menit.

    **Pintu satu arah.** `AttendancePolicy` tidak ber-effective date,
    jadi perhitungan ulang menerapkan aturan yang berlaku sekarang ke
    seluruh rentang yang dipilih — termasuk bulan yang sudah lewat.
    Jam tap sendiri tidak ikut berubah; yang berubah status dan
    menit-menit turunannya.
    """
    from apps.administration.models import AttendancePolicy

    policy = _by_code(AttendancePolicy, HO_POLICY["code"])

    if policy is None:
        return {"changed": 0, "note": f"{HO_POLICY['code']} tidak ada."}

    before = policy.late_tolerance_minutes

    if before == HO_POLICY["late_tolerance_minutes"]:
        return {"changed": 0, "before": before, "after": before}

    policy.late_tolerance_minutes = HO_POLICY["late_tolerance_minutes"]

    policy.full_clean()
    policy.save()

    log(f"  {policy.code} toleransi telat {before}′ → "
        f"{policy.late_tolerance_minutes}′")

    return {
        "changed": 1,
        "before": before,
        "after": policy.late_tolerance_minutes,
    }


# ----------------------------------------------------------------------
# 6 · Tanggal berhenti LOK005, di sekitar pembangunan roster
# ----------------------------------------------------------------------

def clear_termination(*, log=print) -> dict:
    """Melepas tanggal berhenti supaya orangnya jadi kandidat setup."""
    from apps.hr.models import EmploymentAssignment

    employment = EmploymentAssignment.objects.filter(
        is_deleted=False,
        employee__employee_number=LOK005_TERMINATION["employee_number"],
    ).first()

    if employment is None:
        return {"changed": 0, "note": "LOK005 tidak ditemukan."}

    before = employment.termination_date

    if before is None:
        return {"changed": 0, "before": None}

    employment.termination_date = None

    employment.save(update_fields=["termination_date", "updated_at"])

    log(f"  LOK005 tanggal berhenti {before} dilepas sementara.")

    return {"changed": 1, "before": before}


def set_future_termination(*, log=print) -> dict:
    """Mencatat tanggal berhenti yang baru, **sesudah** rencananya terbit."""
    from apps.hr.models import EmploymentAssignment

    employment = EmploymentAssignment.objects.filter(
        is_deleted=False,
        employee__employee_number=LOK005_TERMINATION["employee_number"],
    ).first()

    if employment is None:
        return {"changed": 0, "note": "LOK005 tidak ditemukan."}

    employment.termination_date = LOK005_TERMINATION["new_date"]

    employment.save(update_fields=["termination_date", "updated_at"])

    log(f"  LOK005 tanggal berhenti → {employment.termination_date}")

    return {"changed": 1, "after": employment.termination_date}


# ----------------------------------------------------------------------
# 7 · Siapa yang memang pegawai roster
# ----------------------------------------------------------------------

def normalize_roster_membership(*, log=print) -> dict:
    """
    Merapikan dua keadaan yang dua-duanya membuat daftar roster salah.

    **`LOK005` nonaktif padahal tanggal berhentinya di masa depan.**
    Penonaktifan itu peninggalan tanggal berhenti yang lama
    (2026-08-20). Sesudah tanggalnya dipindah ke 2026-10-10 ia
    **sedang bekerja**, dan `is_active=False` menyatakan sebaliknya —
    ia hilang dari daftar pegawai, dari kandidat roster, dan dari
    payroll, tanpa satu pun layar menyebut sebabnya.

    **Pegawai kantor yang terlanjur dijadikan pegawai roster.**
    `commit_line()` menuliskan Roster Policy ke kepegawaian setiap
    baris yang di-commit. Pegawai kantor yang ikut tertarik masuk
    dokumen setup karena kebetulan berkantor di site jadi berubah
    sumber jadwalnya — dari Work Calendar ke blok rotasi — dan itu
    tidak pernah diputuskan siapa pun.
    """
    from apps.hr.models import (
        Employee,
        EmployeeShiftAssignment,
        EmploymentAssignment,
        SiteRotation,
    )

    result = {"reactivated": [], "unrostered": []}

    # --- LOK005 -------------------------------------------------------

    employee = Employee.objects.filter(
        is_deleted=False,
        employee_number=LOK005_TERMINATION["employee_number"],
    ).select_related("employment").first()

    if employee is not None and not employee.is_active:
        termination = getattr(
            getattr(employee, "employment", None), "termination_date", None,
        )

        if termination is None or termination > date(2026, 9, 25):
            employee.is_active = True

            employee.save(update_fields=["is_active", "updated_at"])

            result["reactivated"].append(employee.employee_number)

            log(
                f"  {employee.employee_number} diaktifkan kembali "
                f"(tanggal berhenti {termination} belum lewat).",
            )

    # --- pegawai kantor di site ---------------------------------------

    for number in NON_ROSTER_SITE_EMPLOYEES:
        employment = EmploymentAssignment.objects.filter(
            is_deleted=False,
            employee__employee_number=number,
        ).first()

        if employment is None:
            continue

        touched = False

        if employment.roster_policy_id or employment.roster_crew_id:
            employment.roster_policy = None
            employment.roster_crew = None
            employment.roster_cycle_start = None

            employment.save(
                update_fields=[
                    "roster_policy",
                    "roster_crew",
                    "roster_cycle_start",
                    "updated_at",
                ],
            )

            touched = True

        # Rencana yang terlanjur terbit ikut dibuang — kalau tidak, ia
        # tetap jadi sumber jadwal walau kepegawaiannya sudah bersih.
        plans = SiteRotation.objects.filter(
            employee__employee_number=number,
        )

        removed = plans.count()

        if removed:
            plans.delete()

            touched = True

        # **Dan rencana shift-nya.** Ini yang paling mudah tertinggal:
        # `EmployeeShiftAssignment` tidak punya FK ke rencana roster,
        # jadi membuang rencananya tidak membawanya serta. Yang tersisa
        # adalah pegawai kantor yang kepegawaiannya sudah bersih tapi
        # jam kerjanya tetap berputar mengikuti shift site — dan
        # `resolve_shift()` memang mendahulukan baris itu di atas shift
        # tetapnya.
        shifts = EmployeeShiftAssignment.objects.filter(
            employee__employee_number=number,
        )

        shift_rows = shifts.count()

        if shift_rows:
            shifts.delete()

            touched = True

        if touched:
            result["unrostered"].append(number)

            log(
                f"  {number} dikembalikan jadi pegawai kantor "
                f"({removed} rencana + {shift_rows} rencana shift "
                "dibuang).",
            )

    return result


# ----------------------------------------------------------------------
# 8 · Dokumen setup roster yang tinggal bangkai
# ----------------------------------------------------------------------

def purge_orphan_roster_setup(*, log=print) -> dict:
    """
    Baris setup yang induknya sudah bertanda terhapus.

    Bentuknya sama dengan pengajuan alur yatim, dan sebabnya sama:
    dokumen dibuang lewat layar (soft delete) sementara barisnya tidak
    ikut ditandai. Yang tersisa adalah baris berstatus `committed` yang
    rencananya sudah lama hilang — di daftar baris ia terbaca seperti
    jadwal yang sudah terbit, dan tidak ada satu pun rencana di
    baliknya.

    Hard delete, karena baris bertanda terhapus tetap menempati kunci
    uniknya dan justru menghalangi pembangunan ulang.
    """
    from apps.hr.models import RosterSetupLine, RosterSetupRequest

    dead_requests = list(
        RosterSetupRequest.objects
        .filter(is_deleted=True)
        .values_list("pk", "document_number")
    )

    if not dead_requests:
        return {"lines": 0, "requests": 0}

    ids = [row[0] for row in dead_requests]

    lines = RosterSetupLine.objects.filter(request_id__in=ids)

    line_count = lines.count()

    lines.delete()

    requests = RosterSetupRequest.objects.filter(pk__in=ids)

    request_count = requests.count()

    requests.delete()

    log(
        f"  {request_count} dokumen setup bertanda terhapus + "
        f"{line_count} barisnya dibuang "
        f"({', '.join(row[1] for row in dead_requests)})",
    )

    return {
        "lines": line_count,
        "requests": request_count,
        "documents": [row[1] for row in dead_requests],
    }
