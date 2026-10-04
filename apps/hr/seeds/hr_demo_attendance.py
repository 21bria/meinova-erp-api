"""
Presensi peragaan manajemen — perencana, HR-DEMO-2.

Berkas ini **tidak menulis apa pun**, dan jaminannya struktural: tidak
ada satu pun service penulis yang diimpor di sini. Yang mengeksekusi
`hr_demo_attendance_apply.py`. Perencana yang diam-diam bisa menulis
adalah perencana yang laporan keringnya tidak bisa dipercaya siapa pun.

Apa yang direncanakan
---------------------
Satu jendela dua bulan presensi untuk rombongan peragaan kanonik, yang
seluruh barisnya bisa ditelusuri ke **hari kerja terjadwal yang nyata**
— bukan ke `employee.is_active`, bukan ke awalan nomor pegawai, bukan
ke kalender yang disalin ke dalam seed.

Urutan hari untuk setiap pegawai selalu sama:

    Penempatan → Lokasi Kerja → Kalender atau Roster
    → Segmen Rotasi → Shift → Hari Kerja Terjadwal

dan baru sesudah itu pertanyaannya jadi "hari ini ada catatan
kehadirannya atau tidak".

Empat asal-usul baris, dan bedanya harus terbaca dari barisnya
--------------------------------------------------------------
* `DEV-ATT-` + `source=import` — tap mesin sungguhan. Lewat jalur
  import kanonik, jadi `AttendanceLog` mentahnya ikut tersimpan.
* `SEED-ATT-` + `source=device` — rekap harian yang dibangkitkan
  deterministik. Tidak ada tap mentah yang disimpan, persis seperti
  sinkronisasi mesin yang cuma mengirim rekap.
* `CLOSE-` + `source=system` — kesimpulan penutup hari: hari terjadwal
  yang tidak ada catatannya. **Tidak pernah ditulis seed ini.**
* `is_manual_adjustment=True` — seseorang memutuskan.

Yang **tidak** dilakukan fase ini: menerbitkan dokumen Cuti, Izin
Kehadiran, atau Lembur. Anomali yang butuh ketiganya sengaja
ditinggalkan utuh — itu bahan HR-DEMO-3, dan menyelesaikannya di sini
berarti tidak ada lagi yang bisa diperagakan di sana.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal

from apps.hr.api.attendance.policy import AttendancePolicyResolver
from apps.hr.api.attendance.schedule import (
    employment_bounds,
    is_roster,
    planned_work_days,
    resolve_shift,
    rest_days,
    rotation_states,
    scheduled_window,
    scheduled_work_days,
)
from apps.hr.applicability import HRFeature, is_applicable
from apps.hr.models import (
    AttendanceLog,
    Employee,
    EmployeeAttendance,
)


# ======================================================================
# Batas-batas yang dibekukan HR-DEMO-2
# ======================================================================

WINDOW_START = date(2026, 7, 25)
WINDOW_END = date(2026, 9, 25)

# Awalan nomor pegawai rombongan kanonik. **Penyaring data peragaan**,
# bukan aturan bisnis: tidak ada satu jalur produksi pun yang
# menyimpulkan apa pun dari awalan nomor pegawai.
CAST_PREFIXES = ("HO", "SGA", "LOK", "BOD")

# Silsilah uji. Tidak pernah masuk rombongan, tidak pernah dapat
# presensi, tidak pernah jadi dependensi peragaan, dan **tidak pernah
# disentuh** — bukan dihapus, bukan diubah.
TRIAL_PREFIX = "TRL"

# Awalan yang dimiliki fase ini. Hanya baris berawalan salah satu dari
# ini yang boleh dibongkar ulang. Apa pun yang lain di dalam cakupan
# adalah milik orang lain: dilaporkan, dipertahankan, dan kalau
# kepemilikannya tidak bisa dipastikan, ia **menghentikan** pembongkaran.
OWNED_PREFIXES = ("DEV-ATT-", "SEED-ATT-", "CLOSE-")

DEVICE_PREFIX = "DEV-ATT-"
SEED_PREFIX = "SEED-ATT-"
CLOSE_PREFIX = "CLOSE-"

# Penanda batch import milik fase ini. Yang membuat `AttendanceLog`
# buatan peragaan bisa dibedakan dari tap sungguhan tanpa menebak dari
# tanggal.
IMPORT_BATCH = "HRDEMO2-DEVICE"

IMPORT_PROFILE_CODE = "ATT-CSV-STANDARD"

DEVICE_HO = "FP-HO-01"
DEVICE_SITE = "FP-SITE-01"


# ======================================================================
# Sebaran jam — KONFIGURASI PERAGAAN, bukan aturan presensi
# ======================================================================
#
# Bobot dulu, lalu rentang menit relatif terhadap jadwal; negatif
# berarti lebih awal. Bentuknya dipilih supaya satu sebaran kedatangan
# yang **sama** menghasilkan angka telat yang sangat berbeda di bawah
# dua kebijakan yang berbeda — itulah yang mau diperagakan:
#
#   ATT-MMR-HO    toleransi 15 menit  → sekitar 16% telat
#   ATT-MMR-SITE  toleransi  0 menit  → sekitar 32% telat
#
# Tidak ada satu angka pun di sini yang menyentuh perhitungan. Yang
# menghitung telat, pulang cepat, lembur, dan jam kerja bersih tetap
# `AttendancePolicyResolver` — seed cuma menentukan jam berapa orangnya
# menekan mesin.

CHECK_IN_PROFILE = [
    (58, (-25, -2)),      # datang lebih awal — mayoritas
    (14, (-1, 3)),        # sekitar tepat waktu
    (16, (4, 14)),        # telat tipis: dimaafkan di HO, dihitung di site
    (8, (16, 40)),        # telat sungguhan di kedua kebijakan
    (3, (55, 95)),        # telat jauh
    (1, (130, 180)),      # luar biasa — melewati ambang 120 menit HO
]

CHECK_OUT_PROFILE = [
    (34, (0, 8)),         # pulang tepat waktu
    (26, (12, 40)),       # lewat sedikit, di bawah ambang lembur
    (18, (65, 150)),      # bukti lembur
    (14, (-18, -2)),      # pulang cepat
    (8, (-40, -20)),      # pulang jauh lebih cepat
]

# Berapa bagian hari terjadwal yang sengaja **dibiarkan kosong**, supaya
# penutup hari punya sesuatu untuk ditemukan. Angka site lebih kecil
# dengan sengaja: orang yang sudah berada di site jarang tidak menekan
# mesin — dia memang di sana.
ABSENCE_RATE_OFFICE = 0.055
ABSENCE_RATE_SITE = 0.02


# ======================================================================
# Skenario yang dipatok
# ======================================================================
#
# Sebaran di atas membuat datanya hidup; yang di bawah ini membuat
# ceritanya bisa diulang. Setiap baris menyebut pegawai, tanggal
# (atau cara memilihnya), dan apa yang harus terbukti.
#
# Menit di sini **relatif terhadap jadwal hari itu**, bukan jam dinding
# — jadi skenario yang sama berlaku untuk shift pagi maupun shift malam
# tanpa satu pun cabang `if malam`.

# --- Kantor: ambang toleransi 15 menit -------------------------------
HO_TOLERANCE_CASES = [
    ("HO003", 0, +12, +5, "datang 12 menit lewat jadwal — masih dimaafkan"),
    ("HO003", 1, +15, +5, "datang persis di batas toleransi"),
    ("HO003", 2, +16, +5, "lewat satu menit dari batas — mulai terhitung"),
    ("HO003", 3, +18, +5, "lewat tiga menit dari batas"),
]

# Telat melewati ambang 120 menit → penanda "seharusnya mengambil cuti".
# Bahan serah-terima HR-DEMO-3.
HO_LEAVE_REQUIRED = ("HO001", 26, +166, +20)

# Pulang cepat, dan telat+pulang cepat pada satu hari.
HO_EARLY_LEAVE = ("HO005", 12, -5, -90)
HO_LATE_AND_EARLY = ("HO006", 18, +40, -45)

# Tap masuk tanpa tap pulang. Bukan status tersendiri di sistem ini —
# `check_out` yang kosong, dan itu memang yang terjadi di mesin.
HO_MISSING_CHECKOUT = ("HO009", 30, -6)

# Koreksi tangan atasan atas hari yang tap pulangnya tidak pernah masuk.
MANUAL_CORRECTION = {
    "employee_number": "HO009",
    "check_out_offset": +14,
    "reason": (
        "Tap pulang tidak terekam mesin. Jam pulang dikoreksi "
        "berdasarkan catatan pengawas shift."
    ),
}

# Hari yang sengaja dikosongkan supaya penutup hari yang mengubahnya
# jadi ABSENT — bukan seed. Indeks ke dalam hari terjadwal pegawainya.
FORCED_ABSENCE = [
    ("HO004", 28),
    ("HO004", 29),
    ("LOK004", 22),
]

# --- Site: toleransi 0 menit -----------------------------------------
SITE_LATE_CASE = ("SGA003", 20, +6, +5)
SITE_OVERTIME_CASE = ("SGA002", 24, -7, +125)

# Bukti mesin lintas tengah malam. Tanggal kerjanya **tidak** ditentukan
# di sini — yang dicari hari SHIFT-3 pertama milik pegawainya, lalu
# resolver jadwal yang menentukan tap jam 07:xx esok paginya milik
# tanggal kerja yang mana.
SITE_NIGHT_CASE = ("SGA002", "SHIFT-3", -8, +38)


# ======================================================================
# Hasil perencanaan
# ======================================================================


@dataclass
class DayPlan:
    employee_number: str
    work_date: date
    band: str                 # "HO" | "SITE"
    shift_code: str
    scheduled_in: datetime
    scheduled_out: datetime
    check_in: datetime | None
    check_out: datetime | None
    origin: str               # "import" | "seed" | "(kosong)"
    scenario: str = ""
    status: str = ""
    late_minutes: int = 0
    early_leave_minutes: int = 0
    overtime_minutes: int = 0
    worked_minutes: int = 0
    leave_required: Decimal = Decimal("0")
    crosses_midnight: bool = False


@dataclass
class Plan:
    start: date
    end: date
    cast: list = field(default_factory=list)
    participants: list = field(default_factory=list)
    days: list[DayPlan] = field(default_factory=list)
    untapped: list = field(default_factory=list)
    remove_attendance: int = 0
    remove_attendance_by_prefix: dict = field(default_factory=dict)
    remove_logs: int = 0
    foreign_rows: list = field(default_factory=list)
    blockers: list = field(default_factory=list)
    notes: list = field(default_factory=list)
    exclusions: dict = field(default_factory=dict)
    schedule: dict = field(default_factory=dict)

    @property
    def is_blocked(self) -> bool:
        return bool(self.blockers)


# ======================================================================
# Undian deterministik
# ======================================================================


def _rng(*parts) -> random.Random:
    """
    Undian yang dibangkitkan dari isinya, bukan dari jam proses.

    Data peragaan yang berubah tiap dijalankan membuat angka yang
    kemarin dilaporkan ke manajemen tidak bisa dibandingkan dengan yang
    hari ini — dan yang paling sering terjadi bukan orang menyadarinya,
    melainkan orang berhenti mempercayai keduanya.
    """
    return random.Random("|".join(str(part) for part in parts))


def _pick(profile, rng: random.Random) -> int:
    total = sum(weight for weight, _ in profile)
    roll = rng.uniform(0, total)
    upto = 0

    for weight, (low, high) in profile:
        upto += weight

        if roll <= upto:
            return rng.randint(low, high)

    return 0


def skips_tap(employee_number: str, day: date, rate: float) -> bool:
    """
    Hari yang sengaja **tidak** dibuatkan baris.

    Bukan baris berstatus Absent: ketidakhadiran di sistem ini memang
    berbentuk baris yang tidak ada, dan menuliskannya langsung di sini
    berarti data peragaan melewati jalur yang justru mau diperagakan.

    Undiannya terpisah dari undian jam supaya mengubah angka ini tidak
    menggeser satu pun jam masuk yang sudah ada.
    """
    return _rng("absence", employee_number, day.isoformat()).random() < rate


def offsets_for(employee_number: str, day: date) -> tuple[int, int]:
    rng = _rng(employee_number, day.isoformat())

    return _pick(CHECK_IN_PROFILE, rng), _pick(CHECK_OUT_PROFILE, rng)


# ======================================================================
# Perencanaan
# ======================================================================


def cast_queryset():
    from django.db.models import Q

    condition = Q()

    for prefix in CAST_PREFIXES:
        condition |= Q(employee_number__startswith=prefix)

    return (
        Employee.objects
        .filter(condition, is_deleted=False)
        .exclude(employee_number__startswith=TRIAL_PREFIX)
        .select_related(
            "organization__company",
            "organization__location",
            "employment__employee_group",
            "employment__roster_crew__work_schedule",
            "employment__working_calendar",
            "employment__shift",
        )
        .order_by("employee_number")
    )


def _nth_scheduled(days: list[date], index: int) -> date | None:
    if 0 <= index < len(days):
        return days[index]

    return None


def _scenario_overrides(schedule) -> dict:
    """
    `(nomor pegawai, tanggal) → (offset masuk, offset pulang, catatan)`.

    Tanggalnya diambil dari hari terjadwal pegawainya, bukan dari
    tanggal yang diketik di konstanta: jadwal boleh bergeser, dan
    skenario yang memaku tanggal akan diam-diam jatuh di hari off
    begitu rosternya digeser sehari.
    """
    overrides: dict = {}

    def put(number, day, in_offset, out_offset, note):
        if day is not None:
            overrides[(number, day)] = (in_offset, out_offset, note)

    for number, index, in_offset, out_offset, note in HO_TOLERANCE_CASES:
        put(
            number,
            _nth_scheduled(schedule.get(number, []), index),
            in_offset,
            out_offset,
            note,
        )

    number, index, in_offset, out_offset = HO_LEAVE_REQUIRED
    put(
        number,
        _nth_scheduled(schedule.get(number, []), index),
        in_offset,
        out_offset,
        "telat melewati ambang 120 menit — penanda kewajiban cuti",
    )

    number, index, in_offset, out_offset = HO_EARLY_LEAVE
    put(
        number,
        _nth_scheduled(schedule.get(number, []), index),
        in_offset,
        out_offset,
        "pulang cepat",
    )

    number, index, in_offset, out_offset = HO_LATE_AND_EARLY
    put(
        number,
        _nth_scheduled(schedule.get(number, []), index),
        in_offset,
        out_offset,
        "telat sekaligus pulang cepat",
    )

    number, index, in_offset = HO_MISSING_CHECKOUT
    put(
        number,
        _nth_scheduled(schedule.get(number, []), index),
        in_offset,
        None,
        "tap pulang tidak terekam",
    )

    number, index, in_offset, out_offset = SITE_LATE_CASE
    put(
        number,
        _nth_scheduled(schedule.get(number, []), index),
        in_offset,
        out_offset,
        "telat 6 menit di site — toleransi nol",
    )

    number, index, in_offset, out_offset = SITE_OVERTIME_CASE
    put(
        number,
        _nth_scheduled(schedule.get(number, []), index),
        in_offset,
        out_offset,
        "bukti lembur",
    )

    return overrides


def night_case_day(employee, days: list[date]) -> date | None:
    """Hari SHIFT-3 pertama milik pegawainya di dalam jendela."""
    _, shift_code, _, _ = SITE_NIGHT_CASE

    for day in days:
        resolved = resolve_shift(employee, day)

        if getattr(getattr(resolved, "shift", None), "code", "") == shift_code:
            return day

    return None


def forced_absence_days(schedule) -> set:
    result = set()

    for number, index in FORCED_ABSENCE:
        day = _nth_scheduled(schedule.get(number, []), index)

        if day is not None:
            result.add((number, day))

    return result


def build(*, start: date = WINDOW_START, end: date = WINDOW_END, schema: str) -> Plan:
    """
    Rencana lengkap fase 2. **Tidak menulis apa pun.**
    """
    plan = Plan(start=start, end=end)

    if schema == "public":
        plan.blockers.append(
            "Schema `public` tidak memuat data bisnis tenant. "
            "Jalankan lewat `tenant_command ... --schema=<tenant>`.",
        )

        return plan

    if start > end:
        plan.blockers.append("Tanggal mulai melewati tanggal akhir.")

        return plan

    cast = list(cast_queryset())

    if not cast:
        plan.blockers.append(
            "Tidak ada pegawai rombongan peragaan "
            f"({'/'.join(CAST_PREFIXES)}) di tenant ini.",
        )

        return plan

    plan.cast = [employee.employee_number for employee in cast]

    # ------------------------------------------------------------------
    # 1. Siapa yang punya kewajiban presensi — dijawab mesinnya
    # ------------------------------------------------------------------

    not_applicable = []
    schedule: dict[str, list[date]] = {}
    exclusions = {
        "field_break": 0,
        "travel_out": 0,
        "travel_in": 0,
        "recovery": 0,
        "office_non_working": 0,
        "post_termination": 0,
        "not_applicable_employees": 0,
    }

    for employee in cast:
        number = employee.employee_number

        if not is_applicable(employee, HRFeature.ATTENDANCE):
            not_applicable.append(number)
            exclusions["not_applicable_employees"] += 1

            continue

        days = sorted(scheduled_work_days(employee, start, end))

        schedule[number] = days

        if days:
            plan.participants.append(number)

        planned = planned_work_days(employee, start, end)
        recovery = rest_days(employee, start, end) & planned

        exclusions["recovery"] += len(recovery)

        if is_roster(employee):
            states = rotation_states(employee, start, end)

            for segment in ("field_break", "travel_out", "travel_in"):
                exclusions[segment] += sum(
                    1 for value in states.values() if value == segment
                )
        else:
            total = (end - start).days + 1

            exclusions["office_non_working"] += total - len(days)

        _, termination = employment_bounds(employee)

        if termination is not None and start <= termination <= end:
            exclusions["post_termination"] += (end - termination).days

    plan.exclusions = exclusions
    plan.schedule = {
        number: len(days) for number, days in schedule.items()
    }

    if not_applicable:
        plan.notes.append(
            f"{len(not_applicable)} pegawai tanpa kewajiban presensi "
            f"(Feature Applicability mematikannya): "
            f"{', '.join(not_applicable)}. Mereka tetap anggota "
            f"rombongan kanonik, tapi bukan peserta presensi.",
        )

    # ------------------------------------------------------------------
    # 2. Apa yang akan dibongkar
    # ------------------------------------------------------------------

    scope = EmployeeAttendance.objects.filter(
        employee__in=cast,
        work_date__gte=start,
        work_date__lte=end,
        is_deleted=False,
    )

    by_prefix: dict[str, int] = {}
    foreign: list = []

    for number, work_date, external_id, source in scope.values_list(
        "employee__employee_number", "work_date", "external_id", "source",
    ):
        external_id = external_id or ""

        owner = next(
            (
                prefix
                for prefix in OWNED_PREFIXES
                if external_id.startswith(prefix)
            ),
            None,
        )

        if owner is None:
            foreign.append((number, work_date, external_id, source))

            continue

        by_prefix[owner] = by_prefix.get(owner, 0) + 1

    plan.remove_attendance = sum(by_prefix.values())
    plan.remove_attendance_by_prefix = by_prefix
    plan.foreign_rows = foreign

    if foreign:
        plan.blockers.append(
            f"{len(foreign)} baris presensi di dalam cakupan tidak "
            f"berawalan milik peragaan ({'/'.join(OWNED_PREFIXES)}). "
            f"Kepemilikannya tidak bisa dipastikan, jadi pembongkaran "
            f"dihentikan. Contoh: "
            + "; ".join(
                f"{number} {work_date} {external_id!r} source={source}"
                for number, work_date, external_id, source in foreign[:5]
            ),
        )

    plan.remove_logs = (
        AttendanceLog.objects
        .filter(
            employee__in=cast,
            import_batch_id=IMPORT_BATCH,
            occurred_at__date__gte=start - timedelta(days=1),
            occurred_at__date__lte=end + timedelta(days=1),
        )
        .count()
    )

    foreign_logs = (
        AttendanceLog.objects
        .filter(
            employee__in=cast,
            occurred_at__date__gte=start,
            occurred_at__date__lte=end,
        )
        .exclude(import_batch_id=IMPORT_BATCH)
        .count()
    )

    if foreign_logs:
        plan.notes.append(
            f"{foreign_logs} baris AttendanceLog di dalam jendela bukan "
            f"milik batch {IMPORT_BATCH}. Dipertahankan apa adanya.",
        )

    # ------------------------------------------------------------------
    # 3. Apa yang akan dibangun
    # ------------------------------------------------------------------

    employees_by_number = {
        employee.employee_number: employee for employee in cast
    }

    overrides = _scenario_overrides(schedule)
    forced = forced_absence_days(schedule)

    night_employee_number = SITE_NIGHT_CASE[0]
    night_day = None

    if night_employee_number in schedule:
        night_day = night_case_day(
            employees_by_number[night_employee_number],
            schedule[night_employee_number],
        )

        if night_day is not None:
            _, _, in_offset, out_offset = SITE_NIGHT_CASE

            overrides[(night_employee_number, night_day)] = (
                in_offset,
                out_offset,
                "bukti mesin lintas tengah malam",
            )
        else:
            plan.notes.append(
                f"{night_employee_number} tidak punya hari SHIFT-3 di "
                f"jendela ini — contoh lintas tengah malam dilewati.",
            )

    # Hari yang dibangun lewat jalur import: seluruh skenario yang
    # dipatok. Sisanya lewat jalur rekap deterministik.
    import_days = set(overrides)

    for number, days in schedule.items():
        employee = employees_by_number[number]
        band = "SITE" if is_roster(employee) else "HO"
        rate = ABSENCE_RATE_SITE if band == "SITE" else ABSENCE_RATE_OFFICE
        rules = AttendancePolicyResolver.rules_for(employee)

        for day in days:
            key = (number, day)

            if key in forced:
                plan.untapped.append((number, day, "skenario mangkir"))

                continue

            if key not in overrides and skips_tap(number, day, rate):
                plan.untapped.append((number, day, "tanpa tap"))

                continue

            resolved = resolve_shift(employee, day)

            scheduled_in, scheduled_out = scheduled_window(
                employee, day, work_days=set(days), resolved=resolved,
            )

            if scheduled_in is None or scheduled_out is None:
                plan.blockers.append(
                    f"{number} {day}: hari terjadwal tanpa jendela "
                    f"jadwal. Master shift-nya belum lengkap.",
                )

                continue

            if key in overrides:
                in_offset, out_offset, note = overrides[key]
                origin = "import"
            else:
                in_offset, out_offset = offsets_for(number, day)
                note = ""
                origin = "seed"

            check_in = scheduled_in + timedelta(minutes=in_offset)

            check_out = (
                None
                if out_offset is None
                else scheduled_out + timedelta(minutes=out_offset)
            )

            computed = AttendancePolicyResolver.compute(
                rules=rules,
                scheduled_check_in=scheduled_in,
                scheduled_check_out=scheduled_out,
                check_in=check_in,
                check_out=check_out,
            )

            plan.days.append(
                DayPlan(
                    employee_number=number,
                    work_date=day,
                    band=band,
                    shift_code=getattr(
                        getattr(resolved, "shift", None), "code", "",
                    ),
                    scheduled_in=scheduled_in,
                    scheduled_out=scheduled_out,
                    check_in=check_in,
                    check_out=check_out,
                    origin=origin,
                    scenario=note,
                    status=str(computed.get("status", "")),
                    late_minutes=int(computed.get("late_minutes", 0) or 0),
                    early_leave_minutes=int(
                        computed.get("early_leave_minutes", 0) or 0,
                    ),
                    overtime_minutes=int(
                        computed.get("overtime_minutes", 0) or 0,
                    ),
                    worked_minutes=int(computed.get("worked_minutes", 0) or 0),
                    leave_required=Decimal(
                        computed.get("leave_required_days", 0) or 0,
                    ),
                    crosses_midnight=(
                        scheduled_out.date() != scheduled_in.date()
                    ),
                ),
            )

    plan.notes.append(
        f"{len(import_days)} hari dibangun lewat jalur import kanonik "
        f"(AttendanceLog mentah tersimpan); sisanya lewat rekap "
        f"deterministik.",
    )

    return plan
