"""
Data peragaan Shift Calendar: **shift yang berganti di dalam satu blok
kerja**, plus satu penyesuaian.

Yang mau terlihat di layar setelah seed ini jalan, dan tidak satu pun
di antaranya bisa terlihat sebelum ada tabel penugasan shift:

* satu pegawai site, satu blok kerja, **tiga shift berbeda** per minggu;
* satu penyesuaian tiga hari yang **menang** atas rencananya, dengan
  tanggal di luarnya kembali ke rencana semula;
* satu shift malam yang jam pulangnya jatuh di tanggal berikutnya —
  supaya baris presensi lintas tengah malam benar-benar ada isinya;
* blok OFF yang tidak menghasilkan satu kewajiban pun;
* Employee Group `BOARD` yang Attendance-nya dimatikan dan
  `MANAGEMENT` yang dinyalakan — **dari konfigurasi**, bukan dari kode
  group.

Tiga aturan yang membentuk bentuk berkas ini
--------------------------------------------
**Rotation tidak disentuh sama sekali.** Seed ini hanya membaca baris
`RotationPeriod` yang sudah ada lalu menempelkan shift ke atasnya.
Menerbitkan rosternya sendiri berarti dua seed yang sama-sama mengaku
tahu kapan orang bekerja, dan yang dijalankan belakangan menang.

**Mingguannya dijangkarkan ke awal blok kerja pegawainya**, bukan ke
tanggal seed dijalankan. Karena itu hasilnya sama persis berapa kali
pun dijalankan dan kapan pun — pola yang bergeser tiap hari membuat
tangkapan layar kemarin tidak bisa dibandingkan dengan hari ini.

**Jam tidak ditulis di sini.** Yang ditulis seed adalah baris master
`Shift`; jendela terjadwalnya diturunkan resolver. Mengubah jam sebuah
shift lewat layar master mengubah seluruh kalender tanpa menjalankan
apa pun lagi.
"""

from __future__ import annotations

from datetime import date, time, timedelta

from django.db import transaction

from apps.administration.models import RosterShiftRotation
from apps.administration.models.references.hr import EmployeeGroup
from apps.administration.models.references.hr_attendance import (
    Shift,
    ShiftGroup,
)
from apps.hr.api.attendance.schedule import is_roster
from apps.hr.api.shift_calendar.pattern import (
    RosterShiftPatternService,
)
from apps.hr.api.shift_calendar.services import (
    EmployeeShiftAssignmentService,
)
from apps.administration.models.references.roster_policy import (
    RosterPolicy,
)
from apps.hr.models import (
    Employee,
    EmployeeShiftAssignment,
    ShiftAssignmentLayer,
)


# ----------------------------------------------------------------------
# Master shift peragaan
# ----------------------------------------------------------------------
#
# Tiga shift operasional yang saling menyambung menutup 24 jam. Angkanya
# **konfigurasi**, bukan aturan: silakan diubah di layar master, dan
# kalender ikut berubah tanpa satu baris kode pun disentuh. Yang tidak
# boleh berubah cuma sifatnya — shift ketiga menyeberang tengah malam,
# dan itulah yang membuat baris presensinya layak diuji.
DEMO_SHIFTS = [
    {
        "code": "SHIFT-1",
        "name": "Shift 1 — Morning",
        "description": "Operational morning shift.",
        "start_time": time(7, 0),
        "end_time": time(15, 0),
        "break_start_time": time(11, 0),
        "break_end_time": time(12, 0),
        "crosses_midnight": False,
        "sort_order": 110,
    },
    {
        "code": "SHIFT-2",
        "name": "Shift 2 — Day",
        "description": "Operational day shift.",
        "start_time": time(15, 0),
        "end_time": time(23, 0),
        "break_start_time": time(19, 0),
        "break_end_time": time(20, 0),
        "crosses_midnight": False,
        "sort_order": 120,
    },
    {
        "code": "SHIFT-3",
        "name": "Shift 3 — Night",
        "description": "Operational night shift, ends the next morning.",
        "start_time": time(23, 0),
        "end_time": time(7, 0),
        "break_start_time": time(3, 0),
        "break_end_time": time(4, 0),
        "crosses_midnight": True,
        "sort_order": 130,
    },
]


# Urutan perputaran mingguan. Sengaja **bukan** 1-2-3: yang dijalani
# crew tambang lazimnya melompat supaya jeda antar shift cukup panjang,
# dan urutan menaik membuat pergantian pagi→siang→malam yang tidak
# pernah memberi waktu istirahat penuh.
WEEKLY_ROTATION = ["SHIFT-1", "SHIFT-3", "SHIFT-2"]

WEEK_DAYS = 7


# Jeda istirahat minimum antar pergantian shift, dalam jam. Sama seperti
# urutan di atas: **isian data peragaan**, bukan aturan yang dipegang
# berkas ini. Angkanya tersimpan di `RosterPolicy.min_rest_hours` dan
# bisa diubah dari layar Roster Policy tanpa menjalankan seed lagi.
#
# Dua puluh empat dipilih karena ia yang membuat bentuk aturannya
# terlihat pada pola peragaan: SHIFT-3 (23:00–07:00 +1) yang disusul
# SHIFT-2 (15:00) hanya berjarak delapan jam, dan begitu pula SHIFT-2
# (selesai 23:00) yang disusul SHIFT-1 (07:00) di blok berikutnya.
# Keduanya karena itu disela satu hari Recovery. Pergantian
# SHIFT-1 → SHIFT-3 berjarak 32 jam dan **tidak** disela — dan itu yang
# membuktikan aturannya mengukur, bukan menyisipkan di tiap pergantian.
DEMO_MIN_REST_HOURS = 24


# Penanda baris buatan seed. Dipakai dua arah: membuang baris seed lama
# saat dijalankan ulang, dan **tidak** membuang penugasan yang dibuat
# orang di layar.
SEED_MARK = "[demo]"


# Berapa jauh ke depan rencana shift disusun. Dibatasi supaya seed tidak
# menerbitkan ratusan baris untuk tanggal yang tidak dilihat siapa pun.
DEFAULT_WEEKS = 16


def _configure_rotation(shifts, log) -> list[str]:
    """
    Menuliskan urutan perputaran ke **Roster Policy**, bukan ke seed.

    Sejak perputaran jadi konfigurasi, urutan di bawah bukan lagi aturan
    yang dipegang berkas ini — ia cuma isian data peragaan. Yang
    membuktikan bedanya: mengubah barisnya lewat layar Roster Policy
    mengubah seluruh jadwal tanpa satu baris kode pun disentuh.
    """
    notes: list[str] = []

    policies = list(
        RosterPolicy.objects
        .filter(is_deleted=False, is_active=True)
        .order_by("code"),
    )

    if not policies:
        return ["Belum ada Roster Policy — perputaran shift dilewati."]

    for policy in policies:
        if policy.min_rest_hours != DEMO_MIN_REST_HOURS:
            policy.min_rest_hours = DEMO_MIN_REST_HOURS
            policy.save(update_fields=["min_rest_hours"])

        # Hard delete baris peragaan lama: `sequence` unik per policy,
        # dan baris yang di-soft-delete tetap menempati kuncinya kalau
        # constraint-nya tidak dikondisikan — di sini ia memang
        # dikondisikan, tapi menumpuk satu generasi tiap kali seed jalan
        # tetap tidak ada gunanya.
        RosterShiftRotation.objects.filter(policy=policy).delete()

        for index, code in enumerate(WEEKLY_ROTATION, start=1):
            RosterShiftRotation.objects.create(
                policy=policy,
                sequence=index,
                shift=shifts[code],
                block_days=WEEK_DAYS,
                notes=f"{SEED_MARK} pola peragaan",
            )

        log(
            f"  {policy.code}: "
            + " → ".join(WEEKLY_ROTATION)
            + f" ({WEEK_DAYS} hari per langkah, jeda minimum "
            + f"{DEMO_MIN_REST_HOURS} jam)"
        )

    return notes


def _demo_site_employees():
    """
    Pegawai roster, deterministik, tanpa menebak dari nomor pegawai.

    Yang menentukan `roster_crew`/`roster_policy` — penanda yang sama
    yang dipakai `scheduled_work_days()`. Menebaknya dari awalan nomor
    membuat seed berhenti bekerja begitu klien menamai pegawainya lain.
    """
    return [
        employee
        for employee in (
            Employee.objects
            .filter(is_deleted=False, is_active=True)
            .select_related(
                "employment",
                "employment__employee_group",
                "employment__roster_policy",
                "employment__roster_crew",
                "organization",
            )
            .order_by("employee_number")
        )
        if is_roster(employee)
    ]


def _ensure_shifts(log) -> dict[str, Shift]:
    group = (
        ShiftGroup.objects
        .filter(code="MINING", is_deleted=False)
        .first()
    )

    shifts: dict[str, Shift] = {}

    for row in DEMO_SHIFTS:
        shift, _ = Shift.objects.update_or_create(
            code=row["code"],
            defaults={
                **{
                    key: value
                    for key, value in row.items()
                    if key != "code"
                },
                # `update_or_create` mencocokkan lewat `code` dan ikut
                # menemukan baris yang sudah di-soft-delete; tanpa kolom
                # ini, shift yang pernah dihapus seseorang dari layar
                # tidak pernah hidup lagi walau seed dijalankan berapa
                # kali pun.
                "is_deleted": False,
                "is_active": True,
                "shift_group": group,
            },
        )

        shifts[row["code"]] = shift

        log(
            f"  {shift.code} {shift.name}: "
            f"{shift.start_time:%H:%M}–{shift.end_time:%H:%M}"
            + (" (+1)" if shift.crosses_midnight else "")
        )

    return shifts


def _configure_applicability(log) -> list[str]:
    """
    Attendance dimatikan untuk `BOARD`, dinyalakan untuk `MANAGEMENT`.

    Ditulis sebagai **konfigurasi peragaan**, bukan sebagai bawaan
    master: tenant yang belum memutuskan tidak boleh tiba-tiba
    kehilangan presensi direksinya karena seed referensi berubah. Dan
    `MANAGEMENT` disebut secara eksplisit justru untuk membuktikan ia
    **tidak** otomatis dikecualikan — pertanyaan yang paling sering
    muncul saat orang melihat baris BOARD.
    """
    notes: list[str] = []

    wanted = {
        "BOARD": False,
        "MANAGEMENT": True,
    }

    for code, applicable in wanted.items():
        group = (
            EmployeeGroup.objects
            .filter(code=code, is_deleted=False)
            .first()
        )

        if group is None:
            notes.append(
                f"Employee Group '{code}' belum ada di master — "
                "dilewati.",
            )

            continue

        if group.attendance_applicable != applicable:
            group.attendance_applicable = applicable
            group.save(update_fields=["attendance_applicable"])

        log(
            f"  {group.code}: Attendance "
            f"{'Applicable' if applicable else 'Not Applicable'}"
        )

    return notes


def _override_for(plan, shifts):
    """
    Satu penyesuaian, dan letaknya sengaja **di tengah minggu malam**.

    Di ujung minggu, penyesuaian terlihat seperti pergantian shift biasa
    dan tidak membuktikan apa pun. Di tengah, tanggal sebelum dan
    sesudahnya harus kembali ke rencana semula — itulah yang mau
    diperlihatkan.

    `plan` berisi `(kode shift, mulai, selesai)` apa adanya dari rekap
    sinkronisasi.
    """
    night = shifts["SHIFT-3"]

    for code, start, end in plan:
        if code != night.code:
            continue

        if (end - start).days < 4:
            continue

        override_start = start + timedelta(days=2)
        override_end = min(override_start + timedelta(days=2), end - timedelta(days=1))

        if override_end < override_start:
            continue

        return (shifts["SHIFT-2"], override_start, override_end)

    return None


@transaction.atomic
def run(
    *,
    log=print,
    start: date | None = None,
    weeks: int = DEFAULT_WEEKS,
    employees: int = 0,
) -> dict:
    from django.utils import timezone

    start = start or timezone.localdate().replace(day=1)
    end = start + timedelta(days=weeks * WEEK_DAYS - 1)

    log("Master shift:")

    shifts = _ensure_shifts(log)

    log("\nFeature Applicability:")

    notes = _configure_applicability(log)

    log("\nPerputaran shift di Roster Policy:")

    notes += _configure_rotation(shifts, log)

    roster_employees = _demo_site_employees()

    if employees:
        roster_employees = roster_employees[:employees]

    if not roster_employees:
        return {
            "shifts": len(shifts),
            "employees": 0,
            "assignments": 0,
            "rest_days": 0,
            "min_rest_hours": DEMO_MIN_REST_HOURS,
            "overrides": 0,
            "start": start,
            "end": end,
            "notes": notes + [
                "Tidak ada pegawai roster. Jalankan "
                "`seed_demo_workforce` / `seed_demo_roster` lebih dulu.",
            ],
        }

    # Hard delete, bukan soft delete. Pemeriksaan tumpang tindih di
    # `clean()` memang menyaring `is_deleted=False`, jadi soft delete
    # tidak akan menggagalkan pembangunan ulang — yang dihindari di sini
    # tabel yang tumbuh satu generasi tiap kali seed dijalankan.
    #
    # Yang dibuang **hanya** baris bertanda seed. Penugasan yang dibuat
    # orang di layar tetap tinggal, dan kalau rentangnya bertabrakan,
    # seed berhenti dengan pesan yang menyebut tanggalnya — itu benar:
    # data uji tidak boleh menimpa keputusan orang.
    removed, _ = (
        EmployeeShiftAssignment.objects
        .filter(
            employee__in=roster_employees,
            notes__startswith=SEED_MARK,
        )
        .delete()
    )

    log(f"\nRencana shift {start} s/d {end}:")

    assignments = 0
    rest_days = 0
    overrides = 0
    override_note = ""

    for position, employee in enumerate(roster_employees):
        segments = RosterShiftPatternService.work_segments(
            employee,
            start,
            end,
        )

        if not segments:
            notes.append(
                f"{employee.employee_number} — tidak ada blok kerja di "
                "rentang ini.",
            )

            continue

        # **Jalur yang sama dengan tombolnya.** Seed tidak lagi memegang
        # rumus maupun urutan shift-nya sendiri: keduanya dibaca dari
        # konfigurasi Roster Policy yang barusan ditulis, lewat service
        # yang juga dipanggil setiap kali roster berubah. Data peragaan
        # yang lahir dari jalur berbeda cepat atau lambat berbeda pula
        # hasilnya, dan itu ketahuannya paling telat saat orang
        # membandingkan layar dengan tangkapan layar kemarin.
        result = RosterShiftPatternService.sync(
            employee=employee,
            start=start,
            end=end,
            notes=f"{SEED_MARK} rencana shift blok kerja",
        )

        if result.get("skipped") == "no_rotation":
            notes.append(
                f"{employee.employee_number} — Roster Policy-nya belum "
                "punya urutan perputaran shift.",
            )

            continue

        plan = [
            (block["shift_code"], block["start_date"], block["end_date"])
            for block in result["blocks"]
        ]

        assignments += result["created"]
        rest_days += result.get("rest_days") or 0

        # Satu penyesuaian saja, dan pada pegawai pertama: yang mau
        # diperagakan bentuknya, bukan jumlahnya. Sepuluh penyesuaian
        # membuat layar terlihat seperti jadwal yang memang berantakan.
        if position == 0:
            adjustment = _override_for(plan, shifts)

            if adjustment is not None:
                shift, override_start, override_end = adjustment

                EmployeeShiftAssignmentService.create(
                    data={
                        "employee": employee,
                        "shift": shift,
                        "layer": ShiftAssignmentLayer.OVERRIDE,
                        "start_date": override_start,
                        "end_date": override_end,
                        "reason": "Coverage plant shutdown",
                        "notes": f"{SEED_MARK} penyesuaian supervisor",
                    },
                )

                overrides += 1

                override_note = (
                    f"{employee.employee_number} "
                    f"{override_start}–{override_end} → {shift.code}"
                )

        log(
            f"  {employee.employee_number} {employee.full_name}: "
            f"{len(plan)} blok shift"
        )

    return {
        "shifts": len(shifts),
        "employees": len(roster_employees),
        "assignments": assignments,
        "rest_days": rest_days,
        "min_rest_hours": DEMO_MIN_REST_HOURS,
        "overrides": overrides,
        "override": override_note,
        "removed": removed,
        "start": start,
        "end": end,
        "notes": notes,
    }
