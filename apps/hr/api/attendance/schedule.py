"""
Hari yang **dijadwalkan** bagi seorang pegawai.

Dipakai dua pemanggil yang harus sepakat: seed presensi data uji dan
`AttendanceClosingService` yang menutup hari. Dua salinan aturan yang
harus tetap sama adalah persis cara selisih diam-diam lahir — penutup
hari yang menghitung hari kerja berbeda dari yang menerbitkan barisnya
akan menandai mangkir orang yang memang tidak dijadwalkan.

Dua cabang, dan pembedanya **pola kerja pegawai**, bukan lokasinya:

* **Roster** — dari baris `RotationPeriod` yang benar-benar berlaku,
  bukan dari rumus siklus. Roster boleh digeser tangan, dan begitu
  digeser rumusnya tidak lagi menggambarkan jadwal yang berlaku.
* **Kantor** — dari `WorkCalendar` berlapis milik `LeaveDayCalculator`,
  dikurangi hari libur.

Hanya segmen `WORK` yang dihitung. Hari perjalanan tidak, walau
`period_type`-nya bisa saja `work` (aturan #4 menghitungnya On Site):
yang dijawab di sini "hari ini orangnya seharusnya menekan mesin atau
tidak", dan orang yang sedang di kapal tidak menekan apa pun.

Dan pertanyaan kedua: **shift apa**
-----------------------------------
Bagian bawah berkas ini menjawab "kalau memang bekerja, jam berapa" —
`resolve_shift()`, berjenjang dari penugasan shift per tanggal
(`EmployeeShiftAssignment`, lapis override lalu baseline) turun ke shift
permanen pegawai lalu `WorkScheduleDay`.

Dan hari yang **tidak** punya shift walau rosternya bilang kerja
------------------------------------------------------------------
Baris `EmployeeShiftAssignment` ber-`kind=REST` — hari pemulihan yang
disisipkan aturan jeda minimum antar shift. Ia dibaca dua kali di
berkas ini: `scheduled_work_days()` mengurangkannya dari hari kerja,
dan `resolve_shift()` berhenti di situ alih-alih turun ke shift
permanen pegawainya. **Aturannya sendiri tidak ada di sini** — yang
menghitung berapa hari pemulihan yang dibutuhkan
`RosterShiftPatternService`; berkas ini cuma membaca barisnya.

Dua pertanyaan itu **tidak boleh** dijawab satu tabel. Roster menentukan
kapan bekerja; penugasan shift menentukan shift apa. Baris penugasan
boleh membentang melewati blok OFF dan pada tanggal itu tidak dibaca
sama sekali — itu yang membuat rencana shift enam minggu tidak perlu
dipotong tiap kali rosternya digeser sehari.

Kontrak lengkapnya: `docs/claude/hr/shift-calendar.md`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Sequence
from zoneinfo import ZoneInfo

from apps.administration.models.references.hr_attendance import (
    WorkScheduleDay,
)
from apps.hr.api.leave.calculator import LeaveDayCalculator
from apps.hr.applicability import HRFeature, is_applicable
from apps.hr.models import (
    LAYER_PRECEDENCE,
    RosterSegmentType,
    RotationPeriod,
    RotationPeriodStatus,
    ShiftAssignmentKind,
    ShiftAssignmentLayer,
    assignment_lookup,
)


def is_roster(employee) -> bool:
    """
    Dua penanda, karena ada dua jalur yang sama-sama sah: `roster_crew`
    (jalur lama) dan `roster_policy` (jalur dokumen Roster Setup).
    Memeriksa salah satunya saja membuat separuh pegawai site terbaca
    sebagai pegawai kantor.
    """
    employment = getattr(employee, "employment", None)

    if employment is None:
        return False

    return bool(
        employment.roster_crew_id
        or employment.roster_policy_id,
    )


def employment_bounds(employee) -> tuple[date | None, date | None]:
    """
    `(join_date, termination_date)` — pagar di kedua ujungnya.

    Tanpa ini, pegawai yang baru masuk tanggal 20 ditandai mangkir untuk
    seluruh tanggal 1–19, dan yang sudah keluar terus ditagih setiap
    hari sampai ada yang menyadarinya.
    """
    employment = getattr(employee, "employment", None)

    if employment is None:
        return None, None

    return employment.join_date, employment.termination_date


def _expand(period_start: date, period_end: date, start: date, end: date):
    """Tanggal satu segmen roster, dipotong ke rentang yang diminta."""
    current = max(period_start, start)
    last = min(period_end, end)

    while current <= last:
        yield current
        current += timedelta(days=1)


def _segment_rows(employee_ids: Sequence[int], start: date, end: date):
    """
    Segmen roster **apa pun jenisnya** yang berlaku pada rentang.

    Satu-satunya tempat penyaringan segmen roster ditulis — hari
    terjadwal, kalender shift, dan jalur borongan sama-sama lewat sini,
    jadi tidak ada dua salinan aturan yang harus dijaga tetap sama.
    """
    return (
        RotationPeriod.objects
        .filter(
            employee_id__in=list(employee_ids),
            is_deleted=False,
            # Baris versi lama tetap tersimpan sebagai sejarah. Ikut
            # dibaca berarti satu hari terhitung dua kali.
            version_to__isnull=True,
            start_date__lte=end,
            end_date__gte=start,
        )
        .exclude(status=RotationPeriodStatus.CANCELLED)
    )


def _roster_rows(employee_ids: Sequence[int], start: date, end: date):
    """Segmen WORK saja — hari yang orangnya memang menekan mesin."""
    return (
        _segment_rows(employee_ids, start, end)
        .filter(segment_type=RosterSegmentType.WORK)
        .values_list("employee_id", "start_date", "end_date")
    )


def rotation_states(employee, start: date, end: date) -> dict[date, str]:
    """
    `tanggal → RosterSegmentType` untuk satu pegawai roster.

    Ini yang menjawab pertanyaan pertama kalender: **hari ini bekerja
    atau tidak**, dan kalau tidak — field break, travel keluar, atau
    travel kembali. Dibaca dari baris `RotationPeriod` yang benar-benar
    ada, bukan dari rumus siklus: roster boleh digeser tangan, dan
    begitu digeser rumusnya tidak lagi menggambarkan jadwal yang
    berlaku.

    Tanggal yang tidak disentuh satu segmen pun **tidak muncul** di
    hasil — pemanggil yang memutuskan apa artinya. Untuk pegawai
    roster artinya "belum ada rencana", dan itu berbeda dari "off".
    """
    states: dict[date, str] = {}

    rows = (
        _segment_rows([employee.id], start, end)
        .values_list("start_date", "end_date", "segment_type")
    )

    for period_start, period_end, segment_type in rows:
        for day in _expand(period_start, period_end, start, end):
            states[day] = segment_type

    return states


def _roster_days(employee, start: date, end: date) -> set[date]:
    days: set[date] = set()

    for _, period_start, period_end in _roster_rows(
        [employee.id],
        start,
        end,
    ):
        days.update(_expand(period_start, period_end, start, end))

    return days


def _office_days_from(
    weekdays,
    holidays: set[date],
    start: date,
    end: date,
) -> set[date]:
    """
    Hari kerja kantor dari kalender yang **sudah** diresolusi.

    Dipisah dari `_office_days` supaya pemanggil borongan bisa memakai
    ulang satu hasil resolusi kalender untuk banyak pegawai tanpa
    menyalin aturannya — yang disalin cepat atau lambat menyimpang.
    """
    days: set[date] = set()

    current = start

    while current <= end:
        if current.weekday() in weekdays and current not in holidays:
            days.add(current)

        current += timedelta(days=1)

    return days


def _office_days(employee, start: date, end: date) -> set[date]:
    calendar = LeaveDayCalculator.resolve_calendar(employee)
    weekdays = LeaveDayCalculator.working_weekdays(calendar)
    holidays = LeaveDayCalculator.resolve_holidays(employee, start, end)

    return _office_days_from(weekdays, holidays, start, end)


def planned_work_days(employee, start: date, end: date) -> set[date]:
    """
    Hari kerja **sebelum** hari pemulihan dikurangkan.

    Dipisah dari `scheduled_work_days()` karena kalender perlu tahu
    bedanya: hari Recovery jatuh di dalam blok kerja, dan merendernya
    sebagai "Off" membuat orang mengira rosternya yang berubah. Yang
    dipakai seluruh pemanggil lain tetap `scheduled_work_days()` —
    fungsi ini isi perutnya, bukan jalur kedua.
    """
    # Employee Group yang mematikan Attendance membuat pegawainya
    # **tidak dijadwalkan sama sekali** — bukan dijadwalkan lalu
    # dimaafkan. Bedanya terlihat di angka: yang kedua menerbitkan baris
    # mangkir yang harus dibersihkan tangan setiap bulan, yang pertama
    # tidak pernah menerbitkannya.
    #
    # Ditaruh di sini, bukan di `AttendanceClosingService`, karena
    # fungsi ini yang jadi satu-satunya jawaban "hari mana orang ini
    # seharusnya menekan mesin" — penutup hari, seed, dan laporan
    # Period Summary sama-sama lewat sini. Menaruhnya di penutup hari
    # berarti laporannya tetap menghitung direksi sebagai mangkir.
    if not is_applicable(employee, HRFeature.ATTENDANCE):
        return set()

    join_date, termination_date = employment_bounds(employee)

    if join_date and join_date > start:
        start = join_date

    if termination_date and termination_date < end:
        end = termination_date

    if start > end:
        return set()

    if is_roster(employee):
        return _roster_days(employee, start, end)

    return _office_days(employee, start, end)


def scheduled_work_days(employee, start: date, end: date) -> set[date]:
    """
    Hari yang benar-benar menerbitkan kewajiban presensi.

    Sama seperti sebelumnya, dikurangi satu hal yang baru: **hari
    pemulihan**. Baris `EmployeeShiftAssignment` ber-`kind=REST`
    menyatakan tanggal itu tidak punya shift sama sekali — jeda antar
    pergantian shift yang tidak cukup disela di sini, bukan di
    presensi. Presensi cuma membacanya.

    Aturan jeda minimumnya sendiri **tidak ada di berkas ini**. Yang
    menghitungnya `RosterShiftPatternService` saat rencana shift
    disusun; yang di sini hanya membaca barisnya, persis seperti ia
    membaca baris shift biasa.
    """
    planned = planned_work_days(employee, start, end)

    if not planned:
        return planned

    return planned - rest_days(employee, start, end)


def scheduled_work_days_bulk(
    employees,
    start: date,
    end: date,
) -> dict[int, set[date]]:
    """
    `scheduled_work_days()` untuk banyak pegawai sekaligus.

    **Aturannya sama persis** — yang berbeda cuma jumlah query. Jalur
    satu pegawai memanggil `_roster_days`/`_office_days`; jalur ini
    memanggil `_roster_rows`/`_office_days_from` yang sama, dengan
    segmen roster diambil sekali untuk seluruh pegawai dan resolusi
    kalender/hari libur dipakai ulang antar pegawai yang kalender dan
    lokasinya sama.

    Tanpa ini, satu laporan sebulan untuk 300 pegawai kantor berarti
    600 query hanya untuk menjawab "hari mana saja orang ini
    dijadwalkan" — jawaban yang bentuknya kecil dan isinya berulang.
    """
    employees = list(employees)

    result: dict[int, set[date]] = {employee.id: set() for employee in employees}

    if not employees:
        return result

    # Aturan yang sama dengan jalur satu pegawai, dan **harus** sama:
    # kuncinya tetap terbit dengan himpunan kosong, jadi pemanggil yang
    # membaca `result[employee.id]` tidak perlu tahu apa pun soal
    # applicability. Menyaring `employees` sesudah `result` dibangun,
    # bukan sebelumnya — dibalik, `KeyError` untuk pegawai yang memang
    # dioper.
    employees = [
        employee
        for employee in employees
        if is_applicable(employee, HRFeature.ATTENDANCE)
    ]

    if not employees:
        return result

    roster_employees = [
        employee for employee in employees if is_roster(employee)
    ]

    office_employees = [
        employee for employee in employees if not is_roster(employee)
    ]

    # Pagar join/termination dipegang di sini supaya kedua cabang di
    # bawah cukup memikirkan jadwalnya saja.
    windows: dict[int, tuple[date, date]] = {}

    for employee in employees:
        join_date, termination_date = employment_bounds(employee)

        window_start = max(start, join_date) if join_date else start
        window_end = min(end, termination_date) if termination_date else end

        if window_start <= window_end:
            windows[employee.id] = (window_start, window_end)

    # ------------------------------------------------------------------
    # Roster: satu query untuk seluruh pegawai
    # ------------------------------------------------------------------

    if roster_employees:
        rows = _roster_rows(
            [employee.id for employee in roster_employees],
            start,
            end,
        )

        for employee_id, period_start, period_end in rows:
            window = windows.get(employee_id)

            if window is None:
                continue

            result[employee_id].update(
                _expand(period_start, period_end, *window),
            )

    # ------------------------------------------------------------------
    # Kantor: resolusi kalender dipakai ulang
    # ------------------------------------------------------------------
    #
    # Kuncinya (kalender pegawai, company, location) — persis ketiga hal
    # yang dibaca `LeaveDayCalculator.resolve_calendar()` dan
    # `resolve_holidays()`. Dua pegawai dengan kunci sama pasti
    # menghasilkan jawaban yang sama, jadi query keduanya cukup sekali.

    cache: dict[tuple, tuple] = {}

    for employee in office_employees:
        window = windows.get(employee.id)

        if window is None:
            continue

        employment = getattr(employee, "employment", None)
        organization = getattr(employee, "organization", None)

        key = (
            getattr(employment, "working_calendar_id", None),
            getattr(organization, "company_id", None),
            getattr(organization, "location_id", None),
        )

        resolved = cache.get(key)

        if resolved is None:
            resolved = (
                LeaveDayCalculator.working_weekdays(
                    LeaveDayCalculator.resolve_calendar(employee),
                ),
                LeaveDayCalculator.resolve_holidays(employee, start, end),
            )

            cache[key] = resolved

        weekdays, holidays = resolved

        result[employee.id] = _office_days_from(weekdays, holidays, *window)

    # ------------------------------------------------------------------
    # Hari pemulihan, satu query untuk seluruh pegawai
    # ------------------------------------------------------------------
    #
    # Aturannya **sama persis** dengan jalur satu pegawai — keduanya
    # memanggil `_rest_days_from()` yang sama, dan yang berbeda cuma
    # dari mana barisnya datang. Dua salinan aturan yang harus tetap
    # sepakat adalah persis cara laporan mulai menghitung hari kerja
    # yang berbeda dari kalender.
    rows = list(
        assignment_lookup(
            [employee.id for employee in employees],
            start,
            end,
        ),
    )

    if rows:
        for employee in employees:
            window = windows.get(employee.id)

            if window is None:
                continue

            result[employee.id] -= _rest_days_from(
                rows,
                employee.id,
                *window,
            )

    return result


def holidays_bulk(employees, start: date, end: date) -> dict[int, set[date]]:
    """
    Hari libur yang berlaku per pegawai, dengan resolusi dipakai ulang.

    Tetap `LeaveDayCalculator.resolve_holidays()` yang menjawab — yang
    ditambahkan di sini cuma ingatan bahwa dua pegawai di company dan
    lokasi yang sama punya daftar libur yang sama.
    """
    cache: dict[tuple, set[date]] = {}
    result: dict[int, set[date]] = {}

    for employee in employees:
        organization = getattr(employee, "organization", None)

        key = (
            getattr(organization, "company_id", None),
            getattr(organization, "location_id", None),
        )

        if key not in cache:
            cache[key] = LeaveDayCalculator.resolve_holidays(
                employee,
                start,
                end,
            )

        result[employee.id] = cache[key]

    return result


# ======================================================================
# JAM JADWAL
#
# Bagian yang selama ini hilang, dan hilangnya diam. `AttendancePolicy`
# sudah lama bisa menyimpan toleransi keterlambatan, tapi
# `AttendancePolicyResolver.compute()` melewati baris yang
# `scheduled_check_in`-nya kosong — dan **tidak ada satu pun jalur yang
# mengisinya**: importer fingerprint tidak, sync agent tidak. Jadi
# seluruh aturan toleransi tersimpan rapi di master lalu tidak pernah
# dievaluasi untuk satu pun tap sungguhan.
#
# Yang menjawab "jam berapa orang ini seharusnya masuk hari itu" ada di
# sini, satu tempat, dipakai importer maupun jalur agent.
# ======================================================================

# Jam dinding kantor. Sengaja tidak `timezone.get_current_timezone()`:
# `TIME_ZONE` proyek ini UTC sementara frontend merender dengan jam
# browser, jadi jadwal 10:00 yang disimpan sebagai 10:00 UTC tampil jam
# 17:00 di layar — dan seluruh perhitungan telat ikut meleset tujuh jam.
# Dipegang di sini supaya importer, jalur agent, dan seed presensi
# memakai patokan yang sama; tiga salinan konstanta ini adalah persis
# cara selisih tujuh jam lahir di salah satunya saja.
WALL_CLOCK_TZ = ZoneInfo("Asia/Jakarta")


def _employment(employee):
    return getattr(employee, "employment", None)


# Dari mana jam kerja hari itu datang. Ikut dikirim ke kalender supaya
# layar bisa membedakan "shift bawaan orangnya" dari "shift yang
# memang dijadwalkan hari itu" — dua hal yang di layar terlihat sama
# persis dan artinya sangat berbeda saat ada yang bertanya kenapa.
class ShiftSource:
    OVERRIDE = "override"
    BASELINE = "baseline"
    EMPLOYMENT = "employment"
    WORK_SCHEDULE = "work_schedule"


# Nilai di atas adalah **semantik**, dan itu yang dikirim payload.
# Yang di bawah ini yang dibaca orang. Dipisahkan supaya frontend tidak
# perlu tahu bahwa lapis rencana shift bernama "baseline" — istilah itu
# milik tabelnya, bukan milik pengguna HR yang cuma menyusun roster.
SHIFT_SOURCE_LABELS = {
    ShiftSource.OVERRIDE: "Adjustment",
    ShiftSource.BASELINE: "Roster",
    ShiftSource.EMPLOYMENT: "Employee Default",
    ShiftSource.WORK_SCHEDULE: "Work Schedule",
}


@dataclass(frozen=True)
class ResolvedShift:
    """Shift yang benar-benar berlaku untuk satu pegawai pada satu tanggal."""

    start_time: time
    end_time: time
    crosses_midnight: bool
    source: str

    # Baris master `Shift`-nya. Kosong kalau jamnya datang dari
    # `WorkScheduleDay` yang mengetik jamnya sendiri tanpa menunjuk
    # baris Shift mana pun — keadaan yang sah dan memang ada di seed.
    shift: object | None = None

    # Baris `EmployeeShiftAssignment` yang memenangkannya, kalau ada.
    # Dipakai kalender untuk menautkan sel ke penugasan yang membuatnya.
    assignment_id: int | None = None

    # Alasan tertulis penyesuaian. "Kenapa shift saya diubah" adalah
    # pertanyaan yang pasti ditanyakan orangnya, dan jawabannya sudah
    # wajib diisi saat penyesuaian dibuat — tinggal ikut dibawa sampai
    # ke layar, bukan dicari lagi lewat query kedua per tanggal.
    assignment_reason: str = ""

    @property
    def shift_code(self) -> str:
        return getattr(self.shift, "code", "") or ""

    @property
    def shift_name(self) -> str:
        return getattr(self.shift, "name", "") or ""

    @property
    def is_override(self) -> bool:
        return self.source == ShiftSource.OVERRIDE

    def as_times(self) -> tuple[time, time, bool]:
        return (self.start_time, self.end_time, self.crosses_midnight)


def _from_shift(
    shift,
    source,
    *,
    assignment_id=None,
    assignment_reason: str = "",
) -> ResolvedShift | None:
    if shift is None or not shift.start_time or not shift.end_time:
        return None

    return ResolvedShift(
        start_time=shift.start_time,
        end_time=shift.end_time,
        crosses_midnight=bool(shift.crosses_midnight),
        source=source,
        shift=shift,
        assignment_id=assignment_id,
        assignment_reason=assignment_reason or "",
    )


def shift_assignments_for(employee, start: date, end: date) -> list:
    """
    Baris penugasan yang menyentuh sebuah rentang, sekali query.

    Dioper ke `resolve_shift(..., assignments=…)` oleh pemanggil yang
    memproses banyak tanggal sekaligus — kalender sebulan yang
    menanyakan ulang tiap hari berarti tiga puluh query untuk jawaban
    yang bentuknya kecil dan isinya berulang.
    """
    return list(assignment_lookup([employee.id], start, end))


def shift_assignment_for(employee, work_date: date, *, rows=None):
    """
    Baris `EmployeeShiftAssignment` yang berlaku pada satu tanggal.

    `OVERRIDE` diperiksa lebih dulu; kalau tidak ada, `BASELINE`.
    Tumpang tindih sesama lapis sudah ditolak `clean()`, jadi di sini
    cukup mengambil yang pertama — tidak ada aturan pemenang kedua yang
    perlu ditulis (dan aturan begitu justru menyembunyikan data yang
    seharusnya diperbaiki).

    `rows` boleh dioper pemanggil yang sudah mengambil barisnya untuk
    rentang yang lebih lebar; penyaringan tanggalnya dikerjakan di
    memori dengan syarat yang **sama persis** dengan query-nya.
    """
    if rows is None:
        rows = assignment_lookup([employee.id], work_date, work_date)

    return _winning_row(rows, employee.id, work_date)


def _winning_row(rows, employee_id: int, work_date: date):
    """
    Baris yang menang untuk satu pegawai pada satu tanggal.

    Dipisah dari `shift_assignment_for()` supaya jalur borongan — yang
    memegang `employee_id` tanpa objek pegawainya — memakai **aturan
    urutan yang sama**, bukan salinannya.
    """
    candidates = [
        row
        for row in rows
        if row.employee_id == employee_id
        and row.start_date <= work_date <= row.end_date
    ]

    for layer in LAYER_PRECEDENCE:
        for row in candidates:
            if row.layer == layer:
                return row

    return None


def _rest_days_from(
    rows,
    employee_id: int,
    start: date,
    end: date,
) -> set[date]:
    """
    Tanggal yang **menang** sebagai hari pemulihan, dari baris yang
    sudah diambil.

    Lapisnya tetap menentukan, dan justru itu yang membuat fungsi ini
    tidak boleh sekadar mengumpulkan tanggal semua baris `REST`:
    penyesuaian supervisor yang menugaskan shift di atas hari pemulihan
    **menang**, dan tanggal itu kembali jadi hari kerja. Sebaliknya juga
    berlaku — penyesuaian yang menyatakan istirahat menang atas rencana
    shift di bawahnya.
    """
    candidates: set[date] = set()

    for row in rows:
        if row.employee_id != employee_id:
            continue

        if row.kind != ShiftAssignmentKind.REST:
            continue

        day = max(row.start_date, start)
        last = min(row.end_date, end)

        while day <= last:
            candidates.add(day)
            day += timedelta(days=1)

    if not candidates:
        return candidates

    return {
        day
        for day in candidates
        if getattr(_winning_row(rows, employee_id, day), "kind", None)
        == ShiftAssignmentKind.REST
    }


def rest_days(
    employee,
    start: date,
    end: date,
    *,
    rows=None,
) -> set[date]:
    """
    Hari pemulihan seorang pegawai pada sebuah rentang.

    `rows` boleh dioper pemanggil yang sudah mengambil barisnya
    (kalender): tanpa itu satu layar berarti satu query tambahan untuk
    jawaban yang barusan diambil.
    """
    if rows is None:
        rows = assignment_lookup([employee.id], start, end)

    return _rest_days_from(rows, employee.id, start, end)


def resolve_shift(
    employee,
    work_date: date,
    *,
    assignments=None,
) -> ResolvedShift | None:
    """
    Jam kerja yang berlaku, berjenjang, dan urutannya menentukan:

    0. **Baris `kind=REST`** yang memenangkan tanggal itu — hari
       pemulihan. Menjawab `None` dan **berhenti**: tidak turun ke
       cadangan mana pun, karena "tidak ada shift" di sini adalah
       keputusan, bukan data yang belum diisi.
    1. **`EmployeeShiftAssignment` lapis `OVERRIDE`** — penyesuaian
       supervisor untuk rentang tanggal tertentu.
    2. **`EmployeeShiftAssignment` lapis `BASELINE`** — rencana shift
       blok kerja. Inilah yang membuat satu crew bisa pagi minggu ini
       dan malam minggu depan tanpa menyentuh pola rosternya.
    3. **`EmploymentAssignment.shift`** — shift permanen orangnya.
       Cadangan untuk pegawai yang shift-nya memang tidak pernah
       berganti, dan jalur yang membuat data lama tetap terhitung sama
       persis seperti sebelum tabel penugasan ada.
    4. **`WorkScheduleDay`** milik `work_schedule` pegawai, dipilih per
       hari-dalam-minggu. Jam di barisnya menang atas jam shift-nya —
       kolom itu memang ada untuk menimpa.
    5. Tidak ketemu → `None`, dan pemanggil membiarkan jadwalnya kosong.
       Itu keadaan yang sah (master belum diisi), dan menebak jam kerja
       jauh lebih berbahaya daripada tidak menghitung telat: angka yang
       ditebak terbaca persis seperti angka yang benar.

    Jam-nya **selalu** dibaca dari master `Shift`/`WorkScheduleDay`,
    tidak pernah dari kode. Mengubah jam sebuah shift di layar master
    mengubah jendela terjadwal seluruh pegawai yang memakainya.
    """
    assignment = shift_assignment_for(
        employee,
        work_date,
        rows=assignments,
    )

    # Baris pemulihan menjawab pertanyaannya dengan **tidak ada shift**,
    # dan jawabannya berhenti di sini. Kalau ia dibiarkan jatuh ke
    # cadangan di bawah, hari pemulihan justru terbit sebagai shift
    # permanen pegawainya — persis hari kerja yang mau dihindari, dengan
    # jam yang terbaca meyakinkan.
    if assignment is not None and assignment.kind == ShiftAssignmentKind.REST:
        return None

    if assignment is not None:
        resolved = _from_shift(
            assignment.shift,
            (
                ShiftSource.OVERRIDE
                if assignment.layer == ShiftAssignmentLayer.OVERRIDE
                else ShiftSource.BASELINE
            ),
            assignment_id=assignment.id,
            assignment_reason=assignment.reason,
        )

        if resolved is not None:
            return resolved

    employment = _employment(employee)

    if employment is None:
        return None

    resolved = _from_shift(
        getattr(employment, "shift", None),
        ShiftSource.EMPLOYMENT,
    )

    if resolved is not None:
        return resolved

    schedule = getattr(employment, "work_schedule", None)

    if schedule is None:
        return None

    # `weekday()` Python: Senin=0. `WorkScheduleDay.Weekday`: Senin=1.
    day = (
        WorkScheduleDay.objects
        .select_related("shift")
        .filter(
            work_schedule=schedule,
            weekday=work_date.weekday() + 1,
        )
        .first()
    )

    if day is None or not day.is_working_day:
        return None

    start = day.start_time or getattr(day.shift, "start_time", None)
    end = day.end_time or getattr(day.shift, "end_time", None)

    if not start or not end:
        return None

    return ResolvedShift(
        start_time=start,
        end_time=end,
        crosses_midnight=bool(
            getattr(day.shift, "crosses_midnight", False),
        ),
        source=ShiftSource.WORK_SCHEDULE,
        shift=day.shift,
    )


def shift_times(employee, work_date: date) -> tuple[time, time, bool] | None:
    """
    `(jam masuk, jam pulang, lewat tengah malam)` untuk satu tanggal.

    Pembungkus tipis `resolve_shift()`; dipertahankan karena bentuk tuple
    inilah yang dipakai pemanggil lama.
    """
    resolved = resolve_shift(employee, work_date)

    if resolved is None:
        return None

    return resolved.as_times()


def shift_span(
    work_date: date,
    start_time: time,
    end_time: time,
    crosses: bool,
) -> tuple[datetime, datetime]:
    """
    Jendela satu shift sebagai datetime **naif** — jam dinding apa
    adanya, tanpa timezone.

    Satu-satunya tempat aturan "pulangnya di tanggal berikutnya"
    ditulis. `scheduled_window()` memakainya lalu menempelkan zona
    waktu; penyusun rencana shift memakainya untuk mengukur jeda antar
    pergantian. Dua salinan aturan ini adalah cara paling pelan untuk
    membuat kalender dan penyusun rencana berbeda pendapat tentang jam
    berapa sebuah shift malam selesai.

    `crosses` yang dikirim pemanggil tetap dihormati, tapi
    `end <= start` **juga** menyeberang: penanda master yang lupa
    dicentang tidak boleh menghasilkan jam kerja negatif.
    """
    begin = datetime.combine(work_date, start_time)

    finish_date = work_date

    if crosses or end_time <= start_time:
        finish_date = work_date + timedelta(days=1)

    return begin, datetime.combine(finish_date, end_time)


def scheduled_window(
    employee,
    work_date: date,
    *,
    work_days: set[date] | None = None,
    resolved: "ResolvedShift | None" = None,
) -> tuple[datetime | None, datetime | None]:
    """
    Jadwal masuk dan pulang sebagai datetime ber-timezone.

    `work_days` boleh dioper pemanggil yang memproses banyak baris
    sekaligus (importer): tanpa itu tiap baris menghitung ulang hari
    terjadwal pegawainya, dan satu file absensi sebulan berarti ratusan
    query untuk jawaban yang bentuknya kecil.

    Hari yang **tidak** terjadwal mengembalikan `(None, None)`, bukan
    jam kerja biasa. Tap di hari libur atau di blok off bukan
    keterlambatan — dan menandainya telat berarti pegawai roster yang
    mampir ke kantor site saat off-nya dihitung terlambat delapan jam.
    """
    if work_days is None:
        work_days = scheduled_work_days(employee, work_date, work_date)

    if work_date not in work_days:
        return (None, None)

    # `resolved` dioper pemanggil yang **sudah** meresolusi shift-nya
    # (kalender). Tanpa itu tiap sel meresolusi dua kali: sekali untuk
    # kode shift-nya, sekali lagi di sini untuk jamnya.
    if resolved is None:
        resolved = resolve_shift(employee, work_date)

    if resolved is None:
        return (None, None)

    start, end, crosses = resolved.as_times()

    scheduled_in, scheduled_out = shift_span(work_date, start, end, crosses)

    return (
        scheduled_in.replace(tzinfo=WALL_CLOCK_TZ),
        scheduled_out.replace(tzinfo=WALL_CLOCK_TZ),
    )
