"""
Presensi data uji: satu bulan berjalan, sampai hari ini.

Tabel `EmployeeAttendance` sudah lama ada lengkap dengan layar dan
importernya, tapi di tenant data uji isinya nol baris — jadi layar
Attendance, filter statusnya, dan angka jam kerja di dashboard tidak
pernah bisa dilihat bentuknya. Ini yang mengisinya.

Dua pola jam kerja, dan pembedanya **pola kerja pegawai**, bukan
lokasinya
-------------------------------------------------------------------
* **Kantor (HO)** — 10:00–18:00, hari kerjanya dari `WorkCalendar`
  (Senin–Jumat, hari libur nasional dikecualikan). Akhir pekan tidak
  menghasilkan baris sama sekali: mesin fingerprint memang tidak
  merekam apa pun di hari orangnya tidak masuk.
* **Site (roster)** — 07:00–17:00, hari kerjanya dari baris
  `RotationPeriod` yang **nyata**, bukan dari rumus siklus. Rosternya
  boleh digeser tangan, dan begitu digeser rumusnya tidak lagi
  menggambarkan jadwal yang berlaku. Hanya segmen `WORK` yang
  menghasilkan baris — hari field break dan hari perjalanan tidak ada
  tap-nya, orangnya tidak di site.

Konsekuensinya yang harus disadari: pegawai roster yang seluruh
rentangnya jatuh di blok off **tidak mendapat satu baris pun**, dan itu
benar. Yang dilewati dilaporkan beserta alasannya, supaya tidak terbaca
seperti seed yang gagal.

Variasi jam sengaja deterministik
---------------------------------
Telat dan pulangnya diacak, tapi acaknya dibangkitkan dari
`(nomor pegawai, tanggal)` — jadi menjalankan ulang seed menghasilkan
angka yang sama persis. Data uji yang berubah tiap dijalankan membuat
angka yang kemarin dilaporkan tidak bisa dibandingkan dengan yang hari
ini.

Zona waktu
----------
`TIME_ZONE` proyek ini UTC, sementara jam yang dimaksud orang
("masuk jam 7") selalu jam dinding di tempatnya bekerja. Timestamp-nya
karena itu dibangun di `Asia/Jakarta`, bukan lewat
`timezone.get_current_timezone()` — kalau memakai yang kedua, baris
07:00 tersimpan sebagai 07:00 UTC dan layarnya (yang merender dengan
jam browser) menampilkannya jam 14:00.
"""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.db import transaction
from django.utils import timezone

from apps.hr.api.attendance.schedule import (
    is_roster,
    resolve_shift,
    scheduled_window,
    scheduled_work_days,
)
from apps.hr.api.attendance.services import EmployeeAttendanceService
from apps.hr.models import (
    Employee,
    EmployeeAttendance,
)
from apps.hr.models.attendance.choices import (
    AttendanceApprovalStatus,
    AttendanceSource,
)


# Jam dinding tempat pegawainya bekerja. Lihat catatan zona waktu di
# atas — ini bukan `TIME_ZONE`, dan memang tidak boleh sama.
WALL_CLOCK_TZ = ZoneInfo("Asia/Jakarta")


# Awalan nomor pegawai data uji, sama dengan `reset_demo_data` — dan
# **harus** sama: awalan yang tertinggal di sini (`LOK` sempat begitu)
# berarti sekelompok pegawai roster tidak pernah mendapat satu baris
# presensi pun, dan yang terlihat cuma layar Attendance yang separuh
# site-nya kosong.
#
# Ini penyaring **data uji**, bukan aturan bisnis: tidak ada satu jalur
# produksi pun yang menyimpulkan apa pun dari awalan nomor pegawai.
EMPLOYEE_PREFIXES = ["HO", "SGA", "LOK"]


# Penanda baris buatan seed. Dipakai dua arah: membuang baris seed lama
# saat dijalankan ulang, dan **tidak** membuang baris yang diketik orang
# di rentang tanggal yang sama.
EXTERNAL_PREFIX = "SEED-ATT-"


# **Tidak ada jam kerja di berkas ini lagi.** Dulu ada dua konstanta —
# kantor 10:00–18:00, site 07:00–17:00 — dan keduanya adalah salinan
# ketiga dari angka yang sudah tersimpan di master `Shift`. Akibatnya
# terlihat begitu ada shift malam: seed menerbitkan baris 07:00–17:00
# untuk orang yang jadwalnya 23:00–07:00, dan seluruh keterlambatannya
# terhitung dari jam yang tidak pernah berlaku.
#
# Sekarang jadwalnya dari `scheduled_window()` — resolver yang **sama**
# dengan yang dipakai importer dan penutup hari, jadi apa pun yang
# dilihat di layar Attendance bisa ditelusuri ke penugasan shift dan
# master Shift-nya.
#
# Ambang lembur dan potongan istirahat milik `AttendancePolicy`, juga
# bukan konstanta di sini.

# Berapa bagian hari terjadwal yang sengaja **tidak** dibuatkan baris,
# supaya `close_attendance` punya sesuatu untuk ditemukan. Angka site
# lebih kecil dengan sengaja: orang yang sudah berada di site jarang
# tidak menekan mesin — dia memang di sana.
ABSENCE_RATE_OFFICE = 0.06
ABSENCE_RATE_SITE = 0.02


# Sebaran keterlambatan. Bobot dulu, rentang menit sesudahnya; negatif
# berarti datang lebih awal. Bentuknya diambil dari data absensi
# sungguhan: mayoritas datang beberapa menit sebelum jadwal, sisanya
# telat sedikit, dan sebagian kecil telat sejam ke atas.
CHECK_IN_PROFILE = [
    (45, (-20, -1)),    # datang lebih awal
    (15, (0, 0)),       # pas
    (25, (10, 25)),     # telat lewat sepuluh menit
    (10, (45, 75)),     # telat sekitar sejam
    (5, (90, 150)),     # telat jauh, jarang
]

# Sebaran jam pulang. Positif = pulang lewat jadwal.
CHECK_OUT_PROFILE = [
    (30, (0, 5)),       # pulang tepat waktu
    (25, (15, 45)),     # lewat sedikit
    (20, (60, 150)),    # lembur
    (15, (-20, -1)),    # pulang cepat
    (10, (-45, -25)),   # pulang jauh lebih cepat
]


def _employees():
    from django.db.models import Q

    condition = Q()

    for prefix in EMPLOYEE_PREFIXES:
        condition |= Q(employee_number__startswith=prefix)

    return (
        Employee.objects
        .filter(condition, is_deleted=False)
        .select_related(
            "organization__company",
            "organization__location",
            "employment__roster_crew__work_schedule",
            "employment__working_calendar",
        )
        .order_by("employee_number")
    )


def _skips_tap(employee_number: str, day: date, rate: float) -> bool:
    """
    Hari yang sengaja **tidak** dibuatkan baris.

    Bukan baris berstatus Absent: ketidakhadiran di sistem ini memang
    berbentuk baris yang tidak ada, dan menuliskannya langsung di sini
    berarti data uji melewati jalur yang justru mau diuji.
    `close_attendance` yang mengubahnya jadi Absent — atau Leave kalau
    tanggalnya tertutup dokumen cuti.

    Undiannya terpisah dari undian jam supaya menambah/mengubah angka
    ini tidak menggeser seluruh jam masuk yang sudah ada.
    """
    rng = random.Random(f"absence|{employee_number}|{day.isoformat()}")

    return rng.random() < rate


def _pick(profile, rng: random.Random) -> int:
    total = sum(weight for weight, _ in profile)

    roll = rng.uniform(0, total)

    upto = 0

    for weight, (low, high) in profile:
        upto += weight

        if roll <= upto:
            return rng.randint(low, high)

    return 0


def _build_row(
    *,
    employee,
    day: date,
    scheduled_in: datetime,
    scheduled_out: datetime,
    shift,
    device_code: str,
) -> dict:
    """
    Satu baris presensi untuk satu hari terjadwal.

    `scheduled_in`/`scheduled_out` sudah datetime ber-timezone hasil
    `scheduled_window()`, jadi shift malam membawa tanggal pulang
    berikutnya apa adanya — tidak ada satu pun cabang `if malam` di
    sini, dan memang tidak boleh ada.
    """
    # Diacak per (pegawai, tanggal), bukan per proses: seed yang
    # dijalankan ulang harus menghasilkan angka yang sama.
    rng = random.Random(f"{employee.employee_number}|{day.isoformat()}")

    in_offset = _pick(CHECK_IN_PROFILE, rng)
    out_offset = _pick(CHECK_OUT_PROFILE, rng)

    check_in = scheduled_in + timedelta(minutes=in_offset)
    check_out = scheduled_out + timedelta(minutes=out_offset)

    # Status, keterlambatan, pulang cepat, lembur, dan jam kerja bersih
    # **tidak dihitung di sini**. `EmployeeAttendanceService` yang
    # menurunkannya dari `AttendancePolicy` yang berlaku untuk pegawai
    # itu — data uji harus lewat jalur yang sama dengan data sungguhan,
    # kalau tidak yang teruji cuma aritmetika seed-nya sendiri.
    return {
        "employee": employee,
        "work_date": day,
        "source": AttendanceSource.DEVICE,
        "approval_status": AttendanceApprovalStatus.APPROVED,
        "shift": shift,
        "scheduled_check_in": scheduled_in,
        "scheduled_check_out": scheduled_out,
        "check_in": check_in,
        "check_out": check_out,
        "first_check_in": check_in,
        "last_check_out": check_out,
        "device_code": device_code,
        "external_id": (
            f"{EXTERNAL_PREFIX}{employee.employee_number}-"
            f"{day.strftime('%Y%m%d')}"
        ),
        "is_geofence_valid": True,
    }


@transaction.atomic
def run(
    *,
    log=print,
    until: date | None = None,
    start: date | None = None,
) -> dict:
    until = until or timezone.localdate()
    start = start or until.replace(day=1)

    if start > until:
        raise ValueError(
            "Tanggal mulai tidak boleh melewati tanggal akhir.",
        )

    employees = list(_employees())

    if not employees:
        return {
            "created": 0,
            "removed": 0,
            "untapped": 0,
            "employees": 0,
            "start": start,
            "until": until,
            "skipped": ["Tidak ada pegawai data uji (HO*/SGA*)."],
        }

    # Hanya baris buatan seed yang dibuang. Baris yang diketik orang di
    # rentang tanggal yang sama tetap tinggal — dan tanggalnya ikut
    # dilewati di bawah, karena `(employee, work_date)` unik.
    removed, _ = (
        EmployeeAttendance.objects
        .filter(
            employee__in=employees,
            work_date__gte=start,
            work_date__lte=until,
            external_id__startswith=EXTERNAL_PREFIX,
        )
        .delete()
    )

    existing = set(
        EmployeeAttendance.objects
        .filter(
            employee__in=employees,
            work_date__gte=start,
            work_date__lte=until,
            is_deleted=False,
        )
        .values_list("employee_id", "work_date")
    )

    created = 0
    untapped = 0
    no_schedule = 0
    skipped: list[str] = []

    for employee in employees:
        roster = is_roster(employee)

        days = scheduled_work_days(employee, start, until)

        if roster:
            device_code = "FP-SITE-01"
            absence_rate = ABSENCE_RATE_SITE
        else:
            device_code = "FP-HO-01"
            absence_rate = ABSENCE_RATE_OFFICE

        if not days:
            skipped.append(
                f"{employee.employee_number} — tidak ada hari kerja di "
                f"rentang ini "
                + (
                    "(seluruhnya jatuh di blok off / travel)."
                    if roster
                    else "(kalender kerjanya kosong di rentang ini)."
                )
            )

            continue

        rows = 0

        for day in sorted(days):
            if (employee.id, day) in existing:
                skipped.append(
                    f"{employee.employee_number} {day} — sudah ada baris "
                    f"non-seed, dilewati."
                )

                continue

            if _skips_tap(employee.employee_number, day, absence_rate):
                untapped += 1

                continue

            scheduled_in, scheduled_out = scheduled_window(
                employee,
                day,
                work_days=days,
            )

            if scheduled_in is None or scheduled_out is None:
                # Master belum menyebut jam kerjanya. Menebaknya di sini
                # berarti data uji memakai jam yang tidak tersimpan di
                # mana pun, dan angkanya terbaca persis seperti angka
                # yang benar.
                no_schedule += 1

                skipped.append(
                    f"{employee.employee_number} {day} — belum ada "
                    "shift/jadwal untuk tanggal ini.",
                )

                continue

            resolved = resolve_shift(employee, day)

            EmployeeAttendanceService.create(
                data=_build_row(
                    employee=employee,
                    day=day,
                    scheduled_in=scheduled_in,
                    scheduled_out=scheduled_out,
                    shift=getattr(resolved, "shift", None),
                    device_code=device_code,
                ),
            )

            rows += 1

        created += rows

        log(
            f"  {employee.employee_number} {employee.full_name}: "
            f"{rows} hari ({'site/roster' if roster else 'kantor'})"
        )

    return {
        "created": created,
        "removed": removed,
        "untapped": untapped,
        "no_schedule": no_schedule,
        "employees": len(employees),
        "start": start,
        "until": until,
        "skipped": skipped,
    }
