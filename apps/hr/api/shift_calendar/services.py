"""
Shift Calendar — satu jawaban per tanggal, dirakit dari domain yang sudah ada.

Tiga pertanyaan, tiga sumber, dan tidak satu pun dihitung ulang di sini:

1. **Bekerja atau tidak?** `RotationPeriod` untuk pegawai roster,
   `WorkCalendar` untuk pegawai kantor — keduanya lewat
   `apps.hr.api.attendance.schedule`.
2. **Kalau bekerja, shift apa?** `resolve_shift()` — override lalu
   baseline lalu shift permanen lalu `WorkScheduleDay`. Hari pemulihan
   (`kind=REST`) menjawab "tidak ada", dan itu jawaban, bukan
   kekosongan data.
3. **Jam berapa?** master `Shift` / `WorkScheduleDay`, lewat
   `scheduled_window()` yang **sama** dengan yang dipakai importer dan
   penutup hari.

Yang penting dari berkas ini justru apa yang **tidak** ada di dalamnya:
tidak ada rumus siklus, tidak ada tabel jam, tidak ada satu pun kode
shift yang ditulis tangan. Kalender adalah penyaji, bukan penghitung
kedua — kalau ia menghitung sendiri, layar dan presensi bisa berbeda
tanpa satu pun dari keduanya terlihat salah.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.core.exceptions import ValidationError

from apps.core.services.base import BaseService
from apps.hr.api.attendance.schedule import (
    SHIFT_SOURCE_LABELS,
    ShiftSource,
    employment_bounds,
    is_roster,
    planned_work_days,
    rest_days,
    resolve_shift,
    rotation_states,
    scheduled_window,
    shift_assignments_for,
)
from apps.hr.api.leave.calculator import LeaveDayCalculator
from apps.hr.api.shift_calendar.scope import assert_adjustable
from apps.hr.applicability import HRFeature, is_applicable
from apps.hr.models import (
    EmployeeShiftAssignment,
    RosterSegmentType,
    ShiftAssignmentLayer,
)


# Keadaan sebuah tanggal di kalender. Empat yang pertama datang apa
# adanya dari `RosterSegmentType`; tiga sisanya menjawab tanggal yang
# tidak disentuh satu segmen roster pun.
class CalendarState:
    WORK = RosterSegmentType.WORK.value
    FIELD_BREAK = RosterSegmentType.FIELD_BREAK.value
    TRAVEL_OUT = RosterSegmentType.TRAVEL_OUT.value
    TRAVEL_IN = RosterSegmentType.TRAVEL_IN.value

    # Pegawai kantor: hari yang bukan hari kerja kalendernya.
    OFF = "off"
    HOLIDAY = "holiday"

    # Hari kerja menurut roster yang **sengaja dikosongkan**: jeda
    # istirahat minimum antar pergantian shift tidak terpenuhi, jadi
    # generator menyisipkan hari pemulihan. Sengaja dibedakan dari
    # `FIELD_BREAK` dan `OFF` — rosternya tidak berubah, dan yang
    # membaca kalender harus bisa melihat kenapa satu hari di tengah
    # blok kerja tidak punya shift.
    RECOVERY = "recovery"

    # Pegawai roster yang tanggalnya belum tersentuh rencana mana pun,
    # dan pegawai di luar masa kerjanya. Sengaja dibedakan dari `OFF`:
    # "belum dijadwalkan" adalah pekerjaan yang belum dilakukan HR,
    # sedangkan "off" adalah jadwal yang memang begitu.
    UNPLANNED = "unplanned"

    # Attendance dimatikan Employee Group-nya. Bukan off, bukan absen —
    # prosesnya memang tidak berlaku.
    NOT_APPLICABLE = "not_applicable"


STATE_LABELS = {
    CalendarState.WORK: "On Site",
    CalendarState.FIELD_BREAK: "Field Break",
    CalendarState.TRAVEL_OUT: "Travel Out",
    CalendarState.TRAVEL_IN: "Travel In",
    CalendarState.OFF: "Off",
    CalendarState.HOLIDAY: "Holiday",
    CalendarState.RECOVERY: "Recovery",
    CalendarState.UNPLANNED: "Unplanned",
    CalendarState.NOT_APPLICABLE: "Not Applicable",
}


MAX_RANGE_DAYS = 366


def _days(start: date, end: date):
    current = start

    while current <= end:
        yield current
        current += timedelta(days=1)


class ShiftCalendarService:
    """Kalender shift satu pegawai untuk sebuah rentang tanggal."""

    @staticmethod
    def month_range(year: int, month: int) -> tuple[date, date]:
        start = date(year, month, 1)

        if month == 12:
            end = date(year, 12, 31)
        else:
            end = date(year, month + 1, 1) - timedelta(days=1)

        return start, end

    @classmethod
    def build(
        cls,
        *,
        employee,
        start: date,
        end: date,
    ) -> dict:
        if end < start:
            raise ValidationError(
                {"end": "End date tidak boleh sebelum start date."},
            )

        span = (end - start).days + 1

        if span > MAX_RANGE_DAYS:
            # Pagar dipegang service, bukan view: perintah dan test
            # memanggil jalur yang sama, dan rentang sepuluh tahun
            # membangun tiga ribu sel yang tidak dilihat siapa pun.
            raise ValidationError(
                {
                    "end": (
                        f"Rentang maksimal {MAX_RANGE_DAYS} hari; "
                        f"diminta {span}."
                    ),
                },
            )

        applicable = is_applicable(employee, HRFeature.ATTENDANCE)

        roster = is_roster(employee)

        states = rotation_states(employee, start, end) if roster else {}

        holidays: set[date] = set()

        if not roster:
            holidays = LeaveDayCalculator.resolve_holidays(
                employee,
                start,
                end,
            )

        join_date, termination_date = employment_bounds(employee)

        # Sekali query untuk seluruh rentang. Tanpa ini, kalender
        # sebulan berarti tiga puluh query untuk jawaban yang bentuknya
        # kecil dan isinya berulang.
        assignments = shift_assignments_for(employee, start, end)

        # Satu jawaban authoritative untuk seluruh rentang, bukan satu
        # per tanggal: fungsi yang sama yang dipakai penutup hari.
        #
        # Dipecah dua karena layar butuh **selisihnya**. `planned`
        # adalah hari kerja menurut roster/kalender; `recovery` adalah
        # yang di antaranya sengaja dikosongkan aturan jeda minimum.
        # Merendernya sebagai "Off" akan terbaca seperti roster yang
        # berubah — padahal yang berubah rencana shift-nya, dan blok
        # kerjanya utuh.
        planned = planned_work_days(employee, start, end)

        recovery = rest_days(employee, start, end, rows=assignments)

        work_days = planned - recovery

        cells = []

        for day in _days(start, end):
            cells.append(
                cls._cell(
                    employee=employee,
                    day=day,
                    applicable=applicable,
                    roster=roster,
                    states=states,
                    holidays=holidays,
                    work_days=work_days,
                    planned=planned,
                    recovery=recovery,
                    join_date=join_date,
                    termination_date=termination_date,
                    assignments=assignments,
                ),
            )

        return {
            "employee": cls._employee_header(employee),
            "range": {
                "start": start,
                "end": end,
                "days": span,
            },
            "is_roster": roster,
            "attendance_applicable": applicable,
            "scheduled_days": len(work_days),
            # Hari kerja yang dikosongkan aturan jeda minimum. Dikirim
            # sebagai angka supaya kepala kalender bisa menyebutkannya
            # tanpa layar menghitung ulang sel satu per satu — dan
            # supaya "kenapa bulan ini hari kerjanya kurang" punya
            # jawaban di layar yang sama.
            "recovery_days": len(recovery & planned),
            "days": cells,
        }

    # ------------------------------------------------------------------
    # Satu sel
    # ------------------------------------------------------------------

    @classmethod
    def _cell(
        cls,
        *,
        employee,
        day: date,
        applicable: bool,
        roster: bool,
        states: dict,
        holidays: set,
        work_days: set,
        planned: set,
        recovery: set,
        join_date,
        termination_date,
        assignments,
    ) -> dict:
        outside = bool(
            (join_date and day < join_date)
            or (termination_date and day > termination_date)
        )

        if not applicable:
            state = CalendarState.NOT_APPLICABLE
        elif outside:
            state = CalendarState.UNPLANNED
        elif day in recovery and day in planned:
            # Syarat keduanya perlu: baris pemulihan boleh saja
            # membentang melewati blok off — sama seperti baris shift —
            # dan pada tanggal itu ia tidak berarti apa-apa. Field break
            # yang tiba-tiba berbunyi "Recovery" akan terbaca seperti
            # rosternya berubah.
            state = CalendarState.RECOVERY
        elif roster:
            state = states.get(day, CalendarState.UNPLANNED)
        elif day in work_days:
            state = CalendarState.WORK
        elif day in holidays:
            state = CalendarState.HOLIDAY
        else:
            state = CalendarState.OFF

        cell = {
            "date": day,
            "weekday": day.isoweekday(),
            "rotation_state": state,
            "rotation_state_label": STATE_LABELS.get(state, state),
            "is_scheduled": day in work_days,
            "shift_code": "",
            "shift_name": "",
            "shift_id": None,
            "scheduled_start": None,
            "scheduled_end": None,
            "scheduled_check_in": None,
            "scheduled_check_out": None,
            "crosses_midnight": False,
            "scheduled_label": "",
            "shift_source": None,
            # Label dirakit backend, sama alasannya dengan
            # `rotation_state_label`: kalau frontend memetakannya
            # sendiri, ada dua daftar istilah yang harus tetap sama.
            "shift_source_label": "",
            "is_override": False,
            "assignment_id": None,
            "assignment_reason": "",
        }

        if day not in work_days:
            # Hari yang tidak dijadwalkan tidak membawa jam, dan itu
            # bukan kekurangan data: tap di blok off bukan
            # keterlambatan, jadi tidak ada jendela untuk dibandingkan.
            return cell

        resolved = resolve_shift(employee, day, assignments=assignments)

        if resolved is None:
            return cell

        check_in, check_out = scheduled_window(
            employee,
            day,
            work_days=work_days,
            resolved=resolved,
        )

        crosses = bool(
            resolved.crosses_midnight
            or resolved.end_time <= resolved.start_time
        )

        cell.update(
            {
                "shift_code": resolved.shift_code,
                "shift_name": resolved.shift_name,
                "shift_id": getattr(resolved.shift, "id", None),
                "scheduled_start": resolved.start_time,
                "scheduled_end": resolved.end_time,
                "scheduled_check_in": check_in,
                "scheduled_check_out": check_out,
                "crosses_midnight": crosses,
                # Label dirakit **backend**. Kalau frontend
                # menyusunnya sendiri dari dua kolom jam, tanda `(+1)`
                # jadi aturan kedua tentang lewat tengah malam — dan
                # aturan kedua cepat atau lambat berbeda dari yang
                # pertama.
                "scheduled_label": (
                    f"{resolved.start_time:%H:%M}–"
                    f"{resolved.end_time:%H:%M}"
                    + (" (+1)" if crosses else "")
                ),
                "shift_source": resolved.source,
                "shift_source_label": SHIFT_SOURCE_LABELS.get(
                    resolved.source,
                    resolved.source,
                ),
                "is_override": resolved.source == ShiftSource.OVERRIDE,
                "assignment_id": resolved.assignment_id,
                "assignment_reason": resolved.assignment_reason,
            },
        )

        return cell

    # ------------------------------------------------------------------
    # Kepala kalender
    # ------------------------------------------------------------------

    @staticmethod
    def _employee_header(employee) -> dict:
        employment = getattr(employee, "employment", None)
        organization = getattr(employee, "organization", None)

        policy = getattr(employment, "roster_policy", None)
        crew = getattr(employment, "roster_crew", None)

        return {
            "id": employee.id,
            "employee_number": employee.employee_number,
            "name": employee.full_name,
            "company": getattr(
                getattr(organization, "company", None), "name", "",
            ),
            "location": getattr(
                getattr(organization, "location", None), "name", "",
            ),
            "roster_policy": getattr(policy, "name", "") or "",
            "roster_crew": getattr(crew, "name", "") or "",
            "employee_group": getattr(
                getattr(employment, "employee_group", None), "name", "",
            ),
        }


class EmployeeShiftAssignmentService(BaseService):
    """
    Tulis-baca penugasan shift.

    Tumpang tindih sesama lapis ditolak `clean()` model, bukan di sini:
    jalur seed dan jalur API sama-sama harus kena, dan aturan yang
    ditulis di service hanya menjaga yang lewat service.
    """

    model = EmployeeShiftAssignment

    @classmethod
    def get_queryset(cls):
        return (
            EmployeeShiftAssignment.objects
            .select_related("employee", "shift")
            .filter(is_deleted=False)
        )

    # ------------------------------------------------------------------
    # Cakupan pada jalur tulis
    # ------------------------------------------------------------------
    #
    # `filter_queryset()` menjaga baca, ubah, dan hapus — `get_object()`
    # DRF memanggilnya, jadi baris di luar cakupan sudah jadi 404. Yang
    # **tidak** dilewatinya adalah `create`: `perform_create()` menulis
    # apa pun yang lolos serializer, dan `employee` di payload boleh
    # berisi id mana pun yang diketik tangan.
    #
    # Cakupannya sengaja **tanpa** garis pelaporan: memantau jadwal tim
    # adalah pekerjaan atasan, mengubahnya bukan. Lihat
    # `apps.hr.api.shift_calendar.scope`.

    @classmethod
    def create(cls, *, data, user=None, **kwargs):
        assert_adjustable(employee=data.get("employee"), user=user)

        return super().create(data=data, user=user, **kwargs)

    @classmethod
    def update(cls, *, instance, data, user=None, **kwargs):
        # Dua-duanya diperiksa, dan yang kedua yang gampang terlewat:
        # memindahkan baris ke pegawai lain adalah penerbitan yang
        # menyamar jadi penyuntingan.
        assert_adjustable(employee=instance.employee, user=user)

        if data.get("employee") is not None:
            assert_adjustable(employee=data["employee"], user=user)

        return super().update(instance=instance, data=data, user=user, **kwargs)

    @classmethod
    def assign(
        cls,
        *,
        employees,
        shift,
        start: date,
        end: date,
        layer: str = ShiftAssignmentLayer.BASELINE,
        reason: str = "",
        notes: str = "",
        user=None,
    ) -> list[EmployeeShiftAssignment]:
        """
        Satu shift untuk banyak pegawai sekaligus — bentuk yang dipakai
        supervisor: "crew ini malam, 8–14 Agustus".

        Tetap satu baris per pegawai. Menyimpannya per crew terlihat
        lebih ringkas sampai ada satu orang yang shift-nya berbeda, dan
        sejak itu setiap pengecualian jadi kasus khusus permanen.
        """
        rows = []

        for employee in employees:
            rows.append(
                cls.create(
                    data={
                        "employee": employee,
                        "shift": shift,
                        "layer": layer,
                        "start_date": start,
                        "end_date": end,
                        "reason": reason,
                        "notes": notes,
                    },
                    user=user,
                ),
            )

        return rows
