"""
Perencana tenant peragaan HR — fase HR-DEMO-1 (fondasi).

Berkas ini **merencanakan** dan melaporkan; yang mengeksekusi tetap
seed dan service yang sudah ada. Itu bukan pembagian kerja yang
kebetulan: tiap langkah di bawah sudah punya pemiliknya sendiri
(`seed_demo_roster`, `seed_calendar`, `seed_attendance_policy`,
`RosterSetupService`), dan menulis ulang logikanya di sini berarti dua
tempat yang bisa berbeda tanpa satu pun terlihat salah.

Yang benar-benar baru di sini cuma tiga hal:

1. **Jangkar.** Seluruh rencana berangkat dari satu tanggal yang
   dioper pemanggil, bukan dari `timezone.localdate()` yang tersebar
   di tiap seed. Tanpa itu, rencana roster lahir dari tanggal 1 bulan
   berjalan sementara presensinya diisi dua bulan ke belakang — dan
   dua-duanya terlihat benar sendiri-sendiri.
2. **Rencana sebelum tulisan.** Laporan kering menyebutkan apa yang
   akan dibuat, apa yang akan dibuang, dan apa yang menghalangi,
   sebelum satu baris pun berubah.
3. **Pagar.** Schema, prefix nomor pegawai, run payroll yang sudah
   dikunci, dan pengajuan alur yatim. Masing-masing punya alasan yang
   sudah pernah terjadi.

Yang **tidak** dilakukan berkas ini
-----------------------------------
Menyentuh apa pun milik lini TRL. Pegawai `TRL*`, `TRL-OT-TIER`,
`TRL-DAILY`, dan manifestnya adalah lini teknis yang terpisah dari
peragaan manajemen: tidak dipakai sebagai persona, tidak dipakai
sebagai dependensi, dan tidak dihapus tanpa persetujuan. Yang
dilakukan di sini terhadapnya persis satu: **menghitungnya dan
melaporkannya.**
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta


# Nomor pegawai yang membentuk peragaan manajemen. Site dan kantor
# pusat; `BOD` ikut karena ia memang bagian dari tenant (dan justru
# membuktikan Feature Applicability), tapi ia bukan subjek proses
# operasional mana pun.
CANONICAL_PREFIXES = ("HO", "SGA", "LOK", "BOD")

# Lini teknis yang **bukan** bagian peragaan manajemen.
TRIAL_PREFIXES = ("TRL",)

# Prefix apa pun di luar dua daftar di atas berarti perintah ini sedang
# dijalankan di tenant yang bukan peragaan. Itu pagar mati.
KNOWN_PREFIXES = CANONICAL_PREFIXES + TRIAL_PREFIXES


WINDOW_MONTHS = 2


@dataclass
class Line:
    label: str
    value: str
    note: str = ""


@dataclass
class Section:
    title: str
    lines: list[Line] = field(default_factory=list)

    def add(self, label, value, note=""):
        self.lines.append(Line(label, str(value), note))


@dataclass
class Plan:
    anchor: date
    window_start: date
    window_end: date
    schema: str
    sections: list[Section] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    destructive: list[tuple[str, int]] = field(default_factory=list)

    def section(self, title: str) -> Section:
        found = Section(title)

        self.sections.append(found)

        return found

    @property
    def safe(self) -> bool:
        return not self.blockers


def window_for(anchor: date) -> tuple[date, date]:
    """
    Dua bulan ke belakang dari jangkar, inklusif di kedua ujung.

    Dihitung dengan mundur bulan, bukan `timedelta(days=60)`: yang
    dimaksud "dua bulan" adalah tanggal yang sama dua bulan lalu, dan
    selisih hari membuat jendelanya bergeser tiap bulan panjang.
    """
    month = anchor.month - WINDOW_MONTHS
    year = anchor.year

    while month <= 0:
        month += 12
        year -= 1

    day = anchor.day

    # 31 Maret mundur dua bulan bukan 31 Januari yang salah, tapi ujung
    # bulan Februari. Dipendekkan sampai tanggalnya sah.
    while True:
        try:
            start = date(year, month, day)

            break
        except ValueError:
            day -= 1

    return start, anchor


def _prefix(employee_number: str) -> str:
    for prefix in KNOWN_PREFIXES:
        if employee_number.upper().startswith(prefix):
            return prefix

    return "?"


def build(*, anchor: date, schema: str) -> Plan:
    """
    Menyusun rencana fase 1 dari keadaan tenant apa adanya.

    Read-only sepenuhnya. Tidak ada `save()`, tidak ada `delete()`,
    tidak ada `create()` — dan itu dijaga dengan tidak mengimpor satu
    pun service penulis di sini.
    """
    from apps.administration.models import (
        AttendancePolicy,
        Holiday,
        Location,
        RosterPolicy,
        Shift,
        WorkCalendar,
    )
    from apps.hr.models import (
        Employee,
        EmployeeAttendance,
        EmployeeShiftAssignment,
        ROSTER_LIVE_STATUSES,
        RotationPeriod,
        SiteRotation,
    )
    from apps.payroll.models import PayrollRun
    from apps.workflow.services.orphans import HARD, SOFT, UNKNOWN, scan

    start, end = window_for(anchor)

    plan = Plan(
        anchor=anchor,
        window_start=start,
        window_end=end,
        schema=schema,
    )

    # ------------------------------------------------------------------
    # Pagar
    # ------------------------------------------------------------------

    if schema == "public":
        plan.blockers.append(
            "Schema public bukan tenant. Jalankan lewat tenant_command.",
        )

        return plan

    employees = list(
        Employee.objects
        .filter(is_deleted=False)
        .select_related("organization", "organization__location", "employment")
        .order_by("employee_number")
    )

    unknown_numbers = [
        person.employee_number
        for person in employees
        if _prefix(person.employee_number) == "?"
    ]

    if unknown_numbers:
        plan.blockers.append(
            f"{len(unknown_numbers)} pegawai bernomor di luar pola "
            f"peragaan ({', '.join(unknown_numbers[:5])}). Tenant ini "
            "kemungkinan bukan tenant peragaan — dihentikan.",
        )

    locked_runs = list(
        PayrollRun.objects
        .filter(is_deleted=False, status="finalized")
        .values_list("document_number", flat=True)
    )

    if locked_runs:
        plan.blockers.append(
            f"{len(locked_runs)} payroll run sudah FINALIZED "
            f"({', '.join(locked_runs[:3])}). Run terkunci membawa "
            "kejadian akuntansi; fondasi tidak boleh dibangun ulang di "
            "bawahnya.",
        )

    # ------------------------------------------------------------------
    # Ringkasan tenant
    # ------------------------------------------------------------------

    scope = plan.section("CAKUPAN")
    scope.add("Schema", schema)
    scope.add("Jangkar", anchor.isoformat())
    scope.add(
        "Jendela",
        f"{start.isoformat()} … {end.isoformat()}",
        f"{(end - start).days + 1} hari",
    )

    canonical = [
        person for person in employees
        if _prefix(person.employee_number) in CANONICAL_PREFIXES
    ]
    trial = [
        person for person in employees
        if _prefix(person.employee_number) in TRIAL_PREFIXES
    ]

    # ------------------------------------------------------------------
    # Pegawai
    # ------------------------------------------------------------------

    people = plan.section("PEGAWAI")
    people.add("Total", len(employees))
    people.add("Kanonik (peragaan)", len(canonical))
    people.add(
        "Lini TRL (teknis)",
        len(trial),
        "dilaporkan saja — tidak disentuh fase ini",
    )

    ho = [
        person for person in canonical
        if getattr(getattr(person, "organization", None), "location", None)
        and "head office" in person.organization.location.name.lower()
    ]
    site = [
        person for person in canonical
        if getattr(getattr(person, "organization", None), "location", None)
        and person not in ho
    ]

    people.add("Kantor pusat", len(ho))
    people.add("Site", len(site))

    # ------------------------------------------------------------------
    # Lini TRL — hitung, jangan sentuh
    # ------------------------------------------------------------------

    trial_ids = [person.pk for person in trial]

    trl = plan.section("LINI TRL — DISPOSISI (TANPA PERUBAHAN)")
    trl.add("Pegawai", len(trial))

    if trial_ids:
        trl.add(
            "Penugasan shift",
            EmployeeShiftAssignment.objects.filter(
                employee_id__in=trial_ids, is_deleted=False,
            ).count(),
            "bertanda reason=TRL-2026-09-E2E",
        )
        trl.add(
            "Presensi",
            EmployeeAttendance.objects.filter(
                employee_id__in=trial_ids, is_deleted=False,
            ).count(),
        )
        trl.add(
            "Rencana roster",
            SiteRotation.objects.filter(
                employee_id__in=trial_ids, is_deleted=False,
            ).count(),
        )

    trl.add(
        "Dipakai peragaan manajemen",
        "TIDAK",
        "bukan persona, bukan cohort, bukan dependensi",
    )

    # ------------------------------------------------------------------
    # Shift
    # ------------------------------------------------------------------

    shifts = plan.section("SHIFT")

    retired = {
        row.pk: row.code
        for row in Shift.objects.filter(is_deleted=True)
    }

    stale_shift = [
        person for person in canonical
        if getattr(getattr(person, "employment", None), "shift_id", None)
        in retired
    ]

    shifts.add("Master aktif", Shift.objects.filter(is_deleted=False).count())
    shifts.add("Master pensiun", len(retired), ", ".join(retired.values()))
    shifts.add(
        "Kepegawaian menunjuk shift pensiun",
        len(stale_shift),
        "akan dialihkan ke shift aktif" if stale_shift else "",
    )

    night = Shift.objects.filter(
        is_deleted=False, crosses_midnight=True,
    ).values_list("code", flat=True)

    shifts.add("Shift lewat tengah malam", ", ".join(night) or "—")

    # ------------------------------------------------------------------
    # Kalender & hari libur
    # ------------------------------------------------------------------

    calendar = plan.section("KALENDER")
    calendar.add(
        "Kalender kerja",
        WorkCalendar.objects.filter(is_deleted=False).count(),
    )

    holidays = list(
        Holiday.objects
        .filter(is_deleted=False, date__gte=start, date__lte=end)
        .order_by("date")
        .values_list("date", "code", "scope")
    )

    calendar.add("Hari libur dalam jendela", len(holidays))

    for row in holidays:
        calendar.add(f"  {row[0].isoformat()}", row[1], row[2])

    if len(holidays) < 2:
        plan.decisions.append(
            "Hanya "
            f"{len(holidays)} hari libur di dalam jendela. Hari libur "
            "tingkat lokasi belum ada, jadi perbedaan kalender kantor "
            "pusat dan site tidak bisa diperagakan. Menambahnya = "
            "master data baru yang dinyatakan perusahaan sendiri, "
            "bukan klaim kalender nasional.",
        )

    # ------------------------------------------------------------------
    # Aturan kehadiran
    # ------------------------------------------------------------------

    policies = plan.section("ATURAN KEHADIRAN")

    for row in AttendancePolicy.objects.filter(is_deleted=False).order_by("code"):
        policies.add(
            row.code,
            f"telat {row.late_tolerance_minutes}′ · "
            f"pulang cepat {row.early_leave_tolerance_minutes}′ · "
            f"lembur {row.overtime_threshold_minutes}′",
            f"skor {row.specificity}",
        )

        if row.late_tolerance_minutes in (0, 1) and row.location_id:
            location = Location.objects.filter(pk=row.location_id).first()

            if location and "head office" in (location.name or "").lower():
                plan.decisions.append(
                    f"{row.code} bertoleransi "
                    f"{row.late_tolerance_minutes} menit di kantor "
                    "pusat. Angka itu menandai hampir semua orang "
                    "terlambat. Menaikkannya adalah pintu satu arah: "
                    "AttendancePolicy tidak ber-effective date, jadi "
                    "perhitungan ulang menimpa sejarah.",
                )

    # ------------------------------------------------------------------
    # Roster — inti fase ini
    # ------------------------------------------------------------------

    roster = plan.section("ROSTER")

    roster_people = [
        person for person in site
        if getattr(getattr(person, "employment", None), "roster_policy_id", None)
        or getattr(getattr(person, "employment", None), "roster_crew_id", None)
    ]

    site_ids = [person.pk for person in site]

    live_plans = set(
        SiteRotation.objects
        .filter(
            is_deleted=False,
            effective_to__isnull=True,
            status__in=ROSTER_LIVE_STATUSES,
            employee_id__in=site_ids,
        )
        .values_list("employee_id", flat=True)
    )

    terminated = [
        person for person in roster_people
        if getattr(getattr(person, "employment", None), "termination_date", None)
    ]

    roster.add("Pegawai roster", len(roster_people))
    roster.add("Punya rencana berjalan", len(live_plans))
    roster.add("Belum punya rencana", len(roster_people) - len(live_plans))
    roster.add(
        "Berhenti (bukan kandidat setup)",
        len(terminated),
        ", ".join(
            person.employee_number for person in terminated
        ) or "—",
    )

    # Urutannya **harus sama** dengan `demo_roster._policy()`. Laporan
    # yang menyebut policy lain dari yang nanti benar-benar dipakai
    # lebih buruk daripada laporan yang tidak menyebutnya sama sekali:
    # ia terbaca seperti fakta yang sudah diperiksa.
    policy = (
        RosterPolicy.objects
        .filter(is_deleted=False, is_active=True)
        .exclude(cycle_work_days__isnull=True)
        .exclude(cycle_off_days__isnull=True)
        .order_by("-is_default", "code")
        .first()
    )

    if policy is None:
        plan.blockers.append(
            "Tidak ada Roster Policy berpola siklus. Jalankan "
            "seed_roster_policy lebih dulu.",
        )
    else:
        roster.add(
            "Policy dipakai",
            policy.code,
            f"{policy.cycle_work_days}/{policy.cycle_off_days} — "
            f"siklus {policy.cycle_length} hari",
        )

    if terminated:
        plan.decisions.append(
            "Pegawai berhenti tidak pernah jadi kandidat Roster Setup "
            "(`candidates()` membuangnya). Jadwal historis mereka tidak "
            "bisa diterbitkan lewat dokumen setup — dokumen itu memang "
            "untuk menjadwalkan ke depan, bukan merekonstruksi masa "
            "lalu: "
            + ", ".join(person.employee_number for person in terminated),
        )

    # Berapa baris presensi site yang **tidak** berpijak pada segmen
    # kerja. Angka inilah yang memberi nama pada seluruh fase ini.
    contradicting = 0

    for row in (
        EmployeeAttendance.objects
        .filter(is_deleted=False, employee_id__in=[p.pk for p in roster_people])
        .values_list("employee_id", "work_date")
    ):
        exists = RotationPeriod.objects.filter(
            employee_id=row[0],
            is_deleted=False,
            segment_type="work",
            start_date__lte=row[1],
            end_date__gte=row[1],
        ).exists()

        if not exists:
            contradicting += 1

    roster.add(
        "Presensi site tanpa segmen kerja",
        contradicting,
        "target sesudah fase ini: 0",
    )

    # ------------------------------------------------------------------
    # Yang akan dibuang
    # ------------------------------------------------------------------

    plan.destructive.append(
        (
            "SiteRotation (pegawai site)",
            SiteRotation.objects.filter(
                employee_id__in=site_ids,
            ).count(),
        ),
    )
    plan.destructive.append(
        (
            "RotationPeriod (pegawai site)",
            RotationPeriod.objects.filter(
                rotation__employee_id__in=site_ids,
            ).count(),
        ),
    )
    plan.destructive.append(
        (
            "EmployeeShiftAssignment (pegawai site)",
            EmployeeShiftAssignment.objects.filter(
                employee_id__in=site_ids,
            ).count(),
        ),
    )

    # ------------------------------------------------------------------
    # Pengajuan alur yatim
    # ------------------------------------------------------------------

    rows = scan()

    workflow = plan.section("PENGAJUAN ALUR")
    workflow.add("Diperiksa", len(rows))
    workflow.add(
        "Yatim HARD",
        sum(1 for row in rows if row.kind == HARD),
        "dokumennya sudah tidak ada",
    )
    workflow.add(
        "Yatim SOFT",
        sum(1 for row in rows if row.kind == SOFT),
        "dokumennya bertanda terhapus",
    )
    workflow.add(
        "Jenis tak terdaftar",
        sum(1 for row in rows if row.kind == UNKNOWN),
    )

    if any(row.kind in (HARD, SOFT) for row in rows):
        plan.decisions.append(
            "Ada pengajuan alur yatim. Bersihkan lewat "
            "`audit_workflow_orphans --fix` sebelum siklus reset "
            "berikutnya menambahnya.",
        )

    return plan
