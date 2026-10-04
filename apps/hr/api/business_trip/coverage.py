"""
Tanggal yang **diizinkan** sebuah Business Trip — BT-3.

Satu fungsi yang dibaca tiga pemakai: penutup hari presensi
(`AttendanceClosingService`), adapter payroll (`PayrollSourceService`),
dan rekonsiliasi saat perjalanan dibatalkan atau pulang lebih awal.
Tiga salinan aturan tanggal adalah cara paling pelan untuk membuat
presensi dan gaji tidak sepakat soal satu hari.

Business Trip adalah **izin bekerja di luar lokasi yang dibayar**, bukan
kehadiran fisik. Fungsi ini hanya menjawab "tanggal mana yang diizinkan";
yang memutuskan status hari itu tetap mesin presensi (tap fisik menang),
dan yang memutuskan uangnya tetap payroll.

Aturan tanggal
--------------
* Satuannya hari kalender **inklusif** di zona jam dinding
  (`DEFAULT_TIMEZONE`), sama dengan penjagaan tumpang-tindih BT-2 —
  bukan `timezone.localdate()` yang di proyek ini UTC. Hari berangkat
  dan hari kembali ikut tertutup walaupun jamnya sore/pagi: tap fisik di
  hari itu tetap yang menang.
* Mulai: tanggal berangkat **rencana** (yang disetujui).
* Selesai: tanggal kembali rencana, atau tanggal kembali sebenarnya
  kalau lebih awal (pulang lebih awal memendekkan izinnya).
* APPROVED / ON_TRIP / COMPLETED menutup rentangnya.
* CANCELLED menutup **hanya hari sebelum tanggal pembatalan** — hari
  yang sudah dijalani tetap sah secara historis, hari sesudahnya tidak
  lagi diizinkan. Dibatalkan sebelum berangkat = tidak menutup apa pun.
* DRAFT / SUBMITTED / REJECTED tidak menutup apa pun.

Kelayakan (`EmployeeGroup.business_trip_applicable`) dinilai saat
pengajuan (BT-2). Perjalanan yang sudah disetujui tetap izin walaupun
konfigurasi grupnya berubah sesudahnya — izin yang sudah diberikan tidak
dicabut diam-diam oleh perubahan master.
"""

from __future__ import annotations

from datetime import date, timedelta

from apps.hr.api.business_trip.overlap import day_start, wall_date


def coverage_range(trip) -> tuple[date, date] | None:
    """Rentang tanggal yang diizinkan satu perjalanan, atau None."""
    from apps.hr.models import (
        BUSINESS_TRIP_COVERAGE_STATUSES,
        BusinessTripStatus,
    )

    if trip.is_deleted:
        return None

    start = wall_date(trip.departure_datetime)
    end = wall_date(trip.return_datetime)

    if trip.actual_return_datetime is not None:
        end = min(end, wall_date(trip.actual_return_datetime))

    if trip.status == BusinessTripStatus.CANCELLED:
        if trip.cancelled_at is None:
            return None

        end = min(end, wall_date(trip.cancelled_at) - timedelta(days=1))

    elif trip.status not in BUSINESS_TRIP_COVERAGE_STATUSES:
        return None

    if end < start:
        return None

    return start, end


def covered_dates(trip) -> set[date]:
    bounds = coverage_range(trip)

    if bounds is None:
        return set()

    start, end = bounds

    return {start + timedelta(days=offset) for offset in range((end - start).days + 1)}


def business_trip_days(employees, start: date, end: date) -> dict[int, dict[date, int]]:
    """
    `{employee_id: {tanggal: trip_id}}` untuk `start..end`, satu query.

    `employees` boleh queryset, daftar instance, atau id. Perjalanan yang
    bertumpuk tidak mungkin (penjagaan BT-2); kalau data lama tetap
    bertumpuk, yang berangkat lebih dulu yang dipakai — deterministik.
    """
    from apps.hr.models import (
        BUSINESS_TRIP_COVERAGE_STATUSES,
        BusinessTrip,
        BusinessTripStatus,
    )

    ids = {int(getattr(employee, "pk", employee)) for employee in employees}

    if not ids:
        return {}

    trips = (
        BusinessTrip.objects
        .filter(
            employee_id__in=ids,
            is_deleted=False,
            status__in=[
                *BUSINESS_TRIP_COVERAGE_STATUSES,
                BusinessTripStatus.CANCELLED,
            ],
            departure_datetime__lt=day_start(end + timedelta(days=1)),
            return_datetime__gte=day_start(start),
        )
        .order_by("departure_datetime", "id")
    )

    result: dict[int, dict[date, int]] = {}

    for trip in trips:
        days = result.setdefault(trip.employee_id, {})

        for day in covered_dates(trip):
            if start <= day <= end:
                days.setdefault(day, trip.pk)

    return result
