"""
Klasifikasi status presensi untuk **pelaporan** (BT-3R).

Satu sumber untuk HR Period Summary, HR Dashboard, dan — lewat Period
Summary — Self Service. Sebelum ini keduanya memegang daftar
`PRESENT_STATUSES` sendiri yang "harus tetap sama", dan keduanya
memasukkan `BUSINESS_TRIP` ke Present.

Aturannya, sejalan dengan fakta payroll BT-3
(`PayrollSourceService._collect_attendance`, yang tidak disentuh):

* **Present** = `PRESENT` / `LATE` / `REMOTE`, plus baris
  `BUSINESS_TRIP` yang punya `check_in` — tap fisik menang atas
  perjalanan, sama seperti payroll menghitungnya `attendance_days`.
  `REMOTE` sudah anggota Present sebelum BT-3R dan tetap begitu; ia di
  luar cakupan tahap ini.
* **Business Trip** = baris `BUSINESS_TRIP` **tanpa** `check_in` — hari
  kerja yang diizinkan di luar tempat kerja, bukan kehadiran fisik, dan
  bukan mangkir. Satu tanggal tidak pernah masuk keduanya.

Yang dibaca adalah **baris presensi yang sudah diresolusi**, bukan
dokumen Business Trip. Baris ABSENT yang belakangan tertutup perjalanan
tetap ABSENT di laporan; payroll yang menutupnya per tanggal.
"""

from __future__ import annotations

from django.db.models import Q

from apps.hr.models.attendance.choices import AttendanceStatus


PRESENT_STATUSES = frozenset(
    {
        AttendanceStatus.PRESENT,
        AttendanceStatus.LATE,
        AttendanceStatus.REMOTE,
    }
)


def is_business_trip_only(status, check_in) -> bool:
    """Hari dinas tanpa tap — metrik Business Trip, bukan Present."""
    return status == AttendanceStatus.BUSINESS_TRIP and check_in is None


def is_present(status, check_in) -> bool:
    """Kehadiran yang dihitung Present, termasuk tap di hari dinas."""
    return status in PRESENT_STATUSES or (
        status == AttendanceStatus.BUSINESS_TRIP and check_in is not None
    )


def business_trip_only_q() -> Q:
    """`is_business_trip_only` sebagai filter ORM."""
    return Q(status=AttendanceStatus.BUSINESS_TRIP, check_in__isnull=True)


def present_q() -> Q:
    """`is_present` sebagai filter ORM."""
    return Q(status__in=PRESENT_STATUSES) | Q(
        status=AttendanceStatus.BUSINESS_TRIP,
        check_in__isnull=False,
    )
