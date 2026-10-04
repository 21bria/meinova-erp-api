"""
Tumpang-tindih Business Trip dengan dokumen lain milik pegawai yang sama.

Kontrak BT-0B §5.3 dan keputusan final #2 (penjagaan timbal balik):

* Business Trip yang diajukan ditolak kalau tanggalnya bertabrakan dengan
  cuti, Business Trip lain, Travel Request, atau izin sehari penuh yang
  sudah **mengklaim** tanggalnya.
* Travel Request yang diajukan ditolak kalau bertabrakan dengan Business
  Trip yang sudah mengklaim tanggalnya. Hasilnya tidak bergantung pada
  dokumen mana yang diajukan lebih dulu.
* Di kedua arah, yang dibandingkan dari Travel Request adalah **perjalanan
  fisiknya** (`TravelRequest.journey_dates` — etape keluar s/d etape
  pulang), bukan blok off `start_date..end_date`; tanpa itinerary jatuh ke
  blok off (TR/BT POLICY-1).

**Satuannya hari kalender, inklusif, di zona jam dinding.**
`departure_datetime`/`return_datetime` disimpan UTC; tanggalnya dibaca
di `DEFAULT_TIMEZONE`, bukan `timezone.localdate()` yang di proyek ini
UTC (temuan BT-1 #3). Perjalanan 05–09 dan dokumen yang mulai tanggal 09
dianggap bertabrakan — hari yang sama tidak bisa dimiliki dua dokumen.

**Draf bukan klaim.** Di kedua sisi yang dihitung hanya dokumen yang
sudah diajukan atau sesudahnya.

Kedua penjagaan mengunci baris `Employee` lebih dulu
(`select_for_update`), jadi dua pengajuan bersamaan untuk orang yang sama
berjalan berurutan dan yang kedua melihat yang pertama.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.core.constants.common import DEFAULT_TIMEZONE


WALL_CLOCK = ZoneInfo(DEFAULT_TIMEZONE)


def wall_date(value: datetime) -> date:
    """Tanggal kalender sebuah waktu, di zona jam dinding."""
    return timezone.localtime(value, WALL_CLOCK).date()


def wall_today() -> date:
    return timezone.localtime(timezone.now(), WALL_CLOCK).date()


def day_start(day: date) -> datetime:
    """Pukul 00:00 jam dinding pada `day`, sebagai waktu ber-zona."""
    return datetime.combine(day, time.min, tzinfo=WALL_CLOCK)


def trip_dates(trip) -> tuple[date, date]:
    """Rentang tanggal yang diklaim sebuah perjalanan (rencana)."""
    return wall_date(trip.departure_datetime), wall_date(trip.return_datetime)


def lock_employee(employee):
    from apps.hr.models import Employee

    return Employee.objects.select_for_update().get(pk=employee.pk)


def claiming_trips(employee, start: date, end: date, *, exclude_pk=None):
    """Business Trip yang sudah mengklaim salah satu hari di `start..end`."""
    from apps.hr.models import BUSINESS_TRIP_CLAIMING_STATUSES, BusinessTrip

    return (
        BusinessTrip.objects
        .filter(
            employee=employee,
            is_deleted=False,
            status__in=BUSINESS_TRIP_CLAIMING_STATUSES,
            departure_datetime__lt=day_start(end + timedelta(days=1)),
            return_datetime__gte=day_start(start),
        )
        .exclude(pk=exclude_pk)
        .order_by("departure_datetime", "id")
    )


def claiming_travel_request(employee, start: date, end: date):
    """
    Travel Request SUBMITTED/APPROVED yang **perjalanan fisiknya**
    (`TravelRequest.journey_dates`: etape keluar s/d etape pulang, jatuh
    ke blok off kalau itinerary belum ada) menyentuh `start..end`.

    Dinilai di Python, bukan di SQL: rentangnya gabungan kolom kepala dan
    baris etape. Jumlah TR aktif satu pegawai kecil, dan etapenya
    di-prefetch sekali.
    """
    from apps.hr.models import TravelRequest, TravelRequestStatus

    candidates = (
        TravelRequest.objects
        .filter(
            employee=employee,
            is_deleted=False,
            status__in=[
                TravelRequestStatus.SUBMITTED,
                TravelRequestStatus.APPROVED,
            ],
        )
        .prefetch_related("travels")
        .order_by("start_date", "id")
    )

    for travel in candidates:
        travel_start, travel_end = travel.journey_dates

        if travel_start <= end and travel_end >= start:
            return travel

    return None


def _label(document) -> str:
    return document.document_number or f"#{document.pk}"


def assert_trip_has_no_overlap(trip) -> None:
    """Penjagaan saat Business Trip diajukan."""
    from apps.hr.models import (
        AttendancePermission,
        AttendancePermissionStatus,
        AttendancePermissionType,
        EmployeeLeave,
        LeaveStatus,
    )

    employee = lock_employee(trip.employee)
    start, end = trip_dates(trip)

    def reject(message):
        raise ValidationError({"departure_datetime": message})

    leave = (
        EmployeeLeave.objects
        .filter(
            employee=employee,
            is_deleted=False,
            status__in=[
                LeaveStatus.SUBMITTED,
                LeaveStatus.APPROVED,
                LeaveStatus.RECORDED,
            ],
            start_date__lte=end,
            end_date__gte=start,
        )
        .order_by("start_date", "id")
        .first()
    )

    if leave is not None:
        reject(
            f"Bertabrakan dengan cuti {_label(leave)} "
            f"({leave.start_date} — {leave.end_date}, "
            f"{leave.get_status_display()}). Sesuaikan tanggal "
            "perjalanan atau cutinya lebih dulu."
        )

    other = claiming_trips(employee, start, end, exclude_pk=trip.pk).first()

    if other is not None:
        other_start, other_end = trip_dates(other)

        reject(
            f"Bertabrakan dengan Business Trip {_label(other)} "
            f"({other_start} — {other_end}, "
            f"{other.get_status_display()})."
        )

    travel = claiming_travel_request(employee, start, end)

    if travel is not None:
        travel_start, travel_end = travel.journey_dates

        reject(
            f"Bertabrakan dengan Travel Request {_label(travel)} "
            f"(perjalanan {travel_start} — {travel_end}, "
            f"{travel.get_status_display()})."
        )

    permission = (
        AttendancePermission.objects
        .filter(
            employee=employee,
            is_deleted=False,
            permission_type=AttendancePermissionType.FULL_DAY,
            status__in=[
                AttendancePermissionStatus.SUBMITTED,
                AttendancePermissionStatus.IN_REVIEW,
                AttendancePermissionStatus.APPROVED,
            ],
            date__gte=start,
            date__lte=end,
        )
        .order_by("date", "id")
        .first()
    )

    if permission is not None:
        reject(
            f"Bertabrakan dengan izin sehari penuh {_label(permission)} "
            f"pada {permission.date} "
            f"({permission.get_status_display()})."
        )


def assert_travel_request_has_no_business_trip(request) -> None:
    """
    Penjagaan timbal balik saat **Travel Request** diajukan.

    Satu-satunya perubahan perilaku Travel Request di BT-2. Yang diperiksa
    hanya Business Trip — penjagaan TR lainnya tetap milik TR sendiri.

    Rentangnya **perjalanan fisik** TR (`journey_dates`, TR/BT POLICY-1),
    bukan blok off. Penjagaan ini tetap jalan apa pun dokumen perjalanan
    yang berlaku untuk group pegawainya: `BOTH`, dokumen lama, dan
    pegawai yang group-nya berganti di antara dua pengajuan adalah
    keadaan yang sah dan justru yang membutuhkannya.
    """
    if request.start_date is None or request.end_date is None:
        return

    employee = lock_employee(request.employee)

    journey_start, journey_end = request.journey_dates

    trip = claiming_trips(
        employee,
        journey_start,
        journey_end,
    ).first()

    if trip is None:
        return

    start, end = trip_dates(trip)

    raise ValidationError(
        {
            "start_date": (
                f"Bertabrakan dengan Business Trip {_label(trip)} "
                f"({start} — {end}, {trip.get_status_display()}). "
                "Satu hari tidak bisa dimiliki dua dokumen perjalanan."
            ),
        },
    )
