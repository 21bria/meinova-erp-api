"""
Presensi peragaan manajemen — pelaksana, HR-DEMO-2.

Dipisah dari perencananya supaya jaminan "perencana tidak menulis
apa pun" jadi struktural, bukan janji. Yang mengimpor service penulis
cuma berkas ini.

Empat langkah, dan tiap langkah lewat jalur yang sama dengan data
sungguhan:

1. **Bukti mesin** — CSV → `ImportPipelineService` → `AttendanceLog`
   mentah → `EmployeeAttendance`. Tidak ada satu pun `AttendanceLog`
   yang ditulis langsung: kalau jalur yang didukung bisa
   membuatnya, memakai jalan pintas berarti yang teruji cuma jalan
   pintasnya.
2. **Rekap deterministik** — sisa hari terjadwal lewat
   `EmployeeAttendanceService`. Status, telat, pulang cepat, lembur,
   dan jam kerja bersih **tidak dihitung di sini**; service yang
   menurunkannya dari `AttendancePolicy` yang berlaku.
3. **Penutupan** — `AttendanceClosingService` bercakupan pegawai.
   Mangkir hanya lahir dari mesin penutup hari, tidak pernah dari seed.
4. **Koreksi tangan** — satu skenario, lewat service yang sama dengan
   layar Attendance, lengkap dengan penanda dan alasannya.
"""

from __future__ import annotations

import csv
import tempfile
from datetime import timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from django.db import transaction

from apps.framework.imports.service import ImportPipelineService
from apps.hr.api.attendance.closing import AttendanceClosingService
from apps.hr.api.attendance.services import EmployeeAttendanceService
from apps.hr.models import (
    AttendanceLog,
    Employee,
    EmployeeAttendance,
)
from apps.hr.models.attendance.choices import (
    AttendanceApprovalStatus,
    AttendanceSource,
)
from apps.hr.seeds.hr_demo_attendance import (
    DEVICE_HO,
    DEVICE_PREFIX,
    DEVICE_SITE,
    IMPORT_BATCH,
    IMPORT_PROFILE_CODE,
    OWNED_PREFIXES,
    SEED_PREFIX,
    MANUAL_CORRECTION,
    cast_queryset,
)
from apps.imports.models import ImportProfile


WALL_CLOCK_TZ = ZoneInfo("Asia/Jakarta")

CSV_COLUMNS = (
    "employee_code",
    "log_time",
    "log_type",
    "device_code",
    "external_id",
)


# ======================================================================
# 0. Pembongkaran
# ======================================================================


def purge(*, plan, log) -> dict:
    """
    Membuang **hanya** yang dimiliki fase ini, di dalam jendela.

    Penyaringnya awalan `external_id`, bukan pegawai-dan-tanggal. Dua
    hal berbeda: yang kedua ikut menghapus baris yang diketik orang di
    tanggal yang sama, dan baris yang diketik orang tidak pernah bisa
    dibangun ulang seed mana pun.
    """
    cast = list(cast_queryset())

    from django.db.models import Q

    condition = Q()

    for prefix in OWNED_PREFIXES:
        condition |= Q(external_id__startswith=prefix)

    removed_rows, _ = (
        EmployeeAttendance.objects
        .filter(
            condition,
            employee__in=cast,
            work_date__gte=plan.start,
            work_date__lte=plan.end,
            is_deleted=False,
        )
        .delete()
    )

    # Tap mentah milik batch ini. Sehari lebih lebar di kedua ujungnya
    # karena tap pulang shift malam jatuh di tanggal berikutnya — dan
    # tap yatim yang tertinggal membuat unggahan ulang terbaca sebagai
    # duplikat lalu tidak menghasilkan baris presensi apa pun.
    removed_logs, _ = (
        AttendanceLog.objects
        .filter(
            employee__in=cast,
            import_batch_id=IMPORT_BATCH,
            occurred_at__date__gte=plan.start - timedelta(days=1),
            occurred_at__date__lte=plan.end + timedelta(days=1),
        )
        .delete()
    )

    log(
        f"  dibongkar: {removed_rows} baris presensi, "
        f"{removed_logs} tap mentah",
    )

    return {"attendance": removed_rows, "logs": removed_logs}


# ======================================================================
# 1. Bukti mesin lewat jalur import kanonik
# ======================================================================


def _device_for(band: str) -> str:
    return DEVICE_SITE if band == "SITE" else DEVICE_HO


def _local(moment):
    return moment.astimezone(WALL_CLOCK_TZ).strftime("%Y-%m-%d %H:%M:%S")


def build_device_csv(*, plan, path: Path) -> int:
    """
    File tap dalam bentuk template kanonik `ATT-CSV-STANDARD`.

    Jam ditulis sebagai jam dinding Asia/Jakarta tanpa zona, persis
    seperti yang dikeluarkan mesin sungguhan — konfigurasi import yang
    menafsirkannya, bukan seed ini.

    Tap pulang shift malam ditulis apa adanya pada **tanggal
    berikutnya**. Tidak ada satu pun kolom di file ini yang menyebut
    tanggal kerjanya: yang menjawab itu resolver jadwal, dan itulah
    yang mau dibuktikan.
    """
    rows = 0

    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()

        for day in plan.days:
            if day.origin != "import":
                continue

            stamp = day.work_date.strftime("%Y%m%d")
            device = _device_for(day.band)

            writer.writerow({
                "employee_code": day.employee_number,
                "log_time": _local(day.check_in),
                "log_type": "in",
                "device_code": device,
                "external_id": (
                    f"{DEVICE_PREFIX}{day.employee_number}-{stamp}"
                ),
            })

            rows += 1

            if day.check_out is None:
                continue

            writer.writerow({
                "employee_code": day.employee_number,
                "log_time": _local(day.check_out),
                "log_type": "out",
                "device_code": device,
                "external_id": (
                    f"{DEVICE_PREFIX}{day.employee_number}-{stamp}-OUT"
                ),
            })

            rows += 1

    return rows


def import_device_evidence(*, plan, log, user=None) -> dict:
    profile = (
        ImportProfile.objects
        .filter(module="hr/attendance", code=IMPORT_PROFILE_CODE)
        .first()
    )

    if profile is None:
        raise RuntimeError(
            f"Import Profile '{IMPORT_PROFILE_CODE}' belum ada. "
            f"Jalankan `seed_attendance_import_demo` lebih dulu.",
        )

    handle = tempfile.NamedTemporaryFile(
        suffix=".csv", prefix="hrdemo2-taps-", delete=False,
    )
    handle.close()

    path = Path(handle.name)

    try:
        taps = build_device_csv(plan=plan, path=path)

        if not taps:
            return {"taps": 0, "created": 0, "updated": 0, "skipped": 0}

        result = ImportPipelineService.execute(
            module="hr/attendance",
            file_path=path,
            source_type=profile.source_type or "csv",
            parser_options={"delimiter": profile.delimiter or ","},
            mapping=profile.mapping or None,
            value_mapping=profile.value_mapping or None,
            date_formats=profile.datetime_formats or None,
            options={"import_batch_id": IMPORT_BATCH},
            user=user,
            profile=profile,
            skip_invalid=True,
        )
    finally:
        path.unlink(missing_ok=True)

    # Nama kuncinya milik `ImportPipelineService`, bukan karangan di
    # sini: `created_rows`, bukan `created`. Membacanya salah tidak
    # membuat import gagal — ia cuma melaporkan nol untuk pekerjaan yang
    # benar-benar terjadi, dan nol itu terbaca persis seperti nol yang
    # benar.
    summary = {
        "taps": taps,
        "created": result.get("created_rows", 0),
        "updated": result.get("updated_rows", 0),
        "skipped": result.get("skipped_rows", 0),
        "duplicate": result.get("duplicate_rows", 0),
        "failed": result.get("failed_rows", 0),
        "errors": result.get("error_rows") or [],
    }

    log(
        f"  bukti mesin: {taps} tap → {summary['created']} baris baru, "
        f"{summary['updated']} baris dilengkapi, "
        f"{summary['duplicate']} duplikat, "
        f"{summary['skipped']} dilewati, {summary['failed']} gagal",
    )

    return summary


# ======================================================================
# 2. Rekap deterministik
# ======================================================================


def fill_deterministic(*, plan, log, user=None) -> dict:
    employees = {
        employee.employee_number: employee
        for employee in cast_queryset()
    }

    existing = set(
        EmployeeAttendance.objects
        .filter(
            work_date__gte=plan.start,
            work_date__lte=plan.end,
            is_deleted=False,
        )
        .values_list("employee__employee_number", "work_date")
    )

    created = 0
    skipped = 0

    for day in plan.days:
        if day.origin != "import" and (
            (day.employee_number, day.work_date) in existing
        ):
            skipped += 1

            continue

        if day.origin != "seed":
            continue

        employee = employees[day.employee_number]

        EmployeeAttendanceService.create(
            data={
                "employee": employee,
                "work_date": day.work_date,
                "source": AttendanceSource.DEVICE,
                "approval_status": AttendanceApprovalStatus.APPROVED,
                "shift": _shift_of(employee, day),
                "scheduled_check_in": day.scheduled_in,
                "scheduled_check_out": day.scheduled_out,
                "check_in": day.check_in,
                "check_out": day.check_out,
                "first_check_in": day.check_in,
                "last_check_out": day.check_out,
                "device_code": _device_for(day.band),
                "external_id": (
                    f"{SEED_PREFIX}{day.employee_number}-"
                    f"{day.work_date.strftime('%Y%m%d')}"
                ),
                "is_geofence_valid": True,
            },
            user=user,
        )

        created += 1

    log(f"  rekap deterministik: {created} baris ({skipped} dilewati)")

    return {"created": created, "skipped": skipped}


def _shift_of(employee, day):
    from apps.hr.api.attendance.schedule import resolve_shift

    resolved = resolve_shift(employee, day.work_date)

    return getattr(resolved, "shift", None)


# ======================================================================
# 3. Penutupan bercakupan
# ======================================================================


def close_window(*, plan, log, user=None) -> dict:
    """
    Mangkir diterbitkan mesin penutup hari, bukan seed.

    Cakupannya **disebut terang-terangan**: id peserta presensi
    rombongan kanonik. Tanpa itu penutup hari akan ikut menutup
    silsilah uji, yang di tenant ini duduk di company dan lokasi yang
    sama persis dengan pegawai kantor — dan `--company`/`--location`
    tidak bisa memisahkan keduanya.
    """
    ids = list(
        Employee.objects
        .filter(
            employee_number__in=plan.participants,
            is_deleted=False,
        )
        .values_list("id", flat=True)
    )

    result = AttendanceClosingService.close(
        start=plan.start,
        end=plan.end,
        employees=ids,
        user=user,
    )

    log(
        f"  penutupan: {result['absent']} tidak hadir, "
        f"{result['leave']} cuti, dari {result['scanned']} hari "
        f"terjadwal ({result['employees']} pegawai)",
    )

    return result


# ======================================================================
# 3b. Hitung ulang
# ======================================================================


def recalculate(*, plan, log) -> dict:
    """
    Menerapkan ulang kebijakan **dan** klasifikasi izin ke seluruh
    jendela, lewat perintah kanonik.

    Kelihatannya mubazir — angka kebijakannya memang sudah diturunkan
    `EmployeeAttendanceService` saat barisnya dibuat. Tapi jalur import
    **tidak** memanggil `apply_permissions()`: ia hanya menurunkan
    angka kebijakan. Baris berasal-import karena itu terbit tanpa
    `permission_state`, dan daftar pengecualian kehilangan justru baris
    yang paling menarik untuk diperagakan.

    Nol baris berubah di sini juga jawaban yang sah, dan jawaban yang
    bagus: artinya seluruh baris sudah konsisten dengan kebijakan yang
    berlaku.
    """
    from django.core.management import call_command
    from io import StringIO

    buffer = StringIO()

    call_command(
        "recalculate_attendance",
        start=plan.start,
        until=plan.end,
        stdout=buffer,
    )

    message = buffer.getvalue().strip()

    log(f"  hitung ulang: {message}")

    return {"message": message}


# ======================================================================
# 4. Koreksi tangan
# ======================================================================


def manual_correction(*, plan, log, user=None) -> dict:
    """
    Satu koreksi atasan atas hari yang tap pulangnya tidak pernah masuk.

    Lewat service yang sama dengan layar Attendance, jadi angkanya tetap
    diturunkan `AttendancePolicy` — yang ditetapkan orang cuma jam
    pulangnya, bukan hasil hitungannya.
    """
    number = MANUAL_CORRECTION["employee_number"]

    target = next(
        (
            day
            for day in plan.days
            if day.employee_number == number and day.check_out is None
        ),
        None,
    )

    if target is None:
        log("  koreksi tangan: tidak ada baris tanpa tap pulang — dilewati")

        return {}

    instance = (
        EmployeeAttendance.objects
        .filter(
            employee__employee_number=number,
            work_date=target.work_date,
            is_deleted=False,
        )
        .select_related("employee")
        .first()
    )

    if instance is None:
        log(f"  koreksi tangan: baris {number} {target.work_date} tidak ada")

        return {}

    before = {
        "work_date": instance.work_date,
        "status": instance.status,
        "check_in": instance.check_in,
        "check_out": instance.check_out,
        "worked_minutes": instance.worked_minutes,
        "source": instance.source,
        "is_manual_adjustment": instance.is_manual_adjustment,
    }

    corrected = target.scheduled_out + timedelta(
        minutes=MANUAL_CORRECTION["check_out_offset"],
    )

    EmployeeAttendanceService.update(
        instance=instance,
        data={
            "check_out": corrected,
            "last_check_out": corrected,
            "is_manual_adjustment": True,
            "adjustment_reason": MANUAL_CORRECTION["reason"],
        },
        user=user,
    )

    instance.refresh_from_db()

    after = {
        "work_date": instance.work_date,
        "status": instance.status,
        "check_in": instance.check_in,
        "check_out": instance.check_out,
        "worked_minutes": instance.worked_minutes,
        "source": instance.source,
        "is_manual_adjustment": instance.is_manual_adjustment,
        "adjustment_reason": instance.adjustment_reason,
        "updated_by": getattr(instance.updated_by, "username", None),
    }

    log(f"  koreksi tangan: {number} {target.work_date} dikoreksi")

    return {"employee_number": number, "before": before, "after": after}


# ======================================================================
# Orkestrasi
# ======================================================================


@transaction.atomic
def run(*, plan, log, user=None) -> dict:
    if plan.is_blocked:
        raise RuntimeError(
            "Rencana masih terhalang. Tidak ada yang dijalankan.",
        )

    return {
        "purged": purge(plan=plan, log=log),
        "imported": import_device_evidence(plan=plan, log=log, user=user),
        "filled": fill_deterministic(plan=plan, log=log, user=user),
        "closed": close_window(plan=plan, log=log, user=user),
        "recalculated": recalculate(plan=plan, log=log),
        "corrected": manual_correction(plan=plan, log=log, user=user),
    }
