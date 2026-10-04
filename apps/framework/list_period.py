"""
Rentang tanggal wajib untuk daftar transaksional.

Layar operasional membaca **periode**, bukan sejarah. Presensi satu
tenant menengah sudah menyentuh jutaan baris (5.000 pegawai x 365 hari x
beberapa tahun), dan daftar yang membuka seluruhnya lalu menyerahkan
pembatasannya ke `LIMIT/OFFSET` tetap membayar `COUNT(*)` atas seluruh
tabel setiap kali halaman dibuka — biayanya tidak terlihat di layar,
cuma terasa sebagai "halamannya lambat" yang tidak pernah bisa
dilacak ke satu filter pun.

Yang ditulis di sini cuma **kontrak rentangnya**: dari query string
jadi sepasang tanggal yang sah, atau 400 yang menyebut sebabnya.
Penyaringannya sendiri dikerjakan `PeriodScopedListMixin` di
`apps.framework.views.mixins`, dan aturan bisnis presensi tidak
disentuh sama sekali — rentang hanya membatasi **baris mana yang
ditanyakan**, bukan artinya.

**Kenapa terpisah dari `apps.framework.periods`.** Yang di sebelah
melayani dashboard: ia mengenal mode (harian/mingguan/kuartalan),
menurunkan periode pembanding, dan sengaja **tidak pernah menolak**
masukan yang aneh — satu query param salah ketik tidak boleh
menjatuhkan dashboard. Daftar transaksional butuh kebalikannya persis:
masukan yang tidak sah harus ditolak, karena yang lolos diam-diam di
sini adalah permintaan yang menyapu bertahun-tahun data.

Padanan berkas ini untuk satu pegawai ada di
`apps.self_service.services.attendance` (`resolve_range`). Keduanya
sengaja memakai nama parameter dan batas yang sama supaya "rentang
maksimal 90 hari" berarti hal yang sama di layar mana pun.
"""

from __future__ import annotations

import calendar

from dataclasses import dataclass
from datetime import date, timedelta

from decouple import config

from django.utils import timezone

from rest_framework.exceptions import ValidationError


# Nama parameter. Sama persis dengan `/api/me/attendance/`, dan itu
# disengaja: dua layar yang menanyakan hal yang sama tidak boleh
# menanyakannya dengan dua ejaan.
FROM_PARAM = "date_from"
TO_PARAM = "date_to"


# Batas atas satu permintaan daftar, bisa disetel per environment.
#
# 90 hari dipilih supaya **setiap preset muat**: preset terpanjang
# "bulan lalu" 31 hari, jadi batas ini memberi ruang tiga kali lipat
# tanpa pernah membuat preset gagal — sementara URL yang diketik tangan
# (`date_from=2000-01-01`) tetap ditolak sebelum menyentuh database.
#
# Untuk histori panjang / analisis tahunan, jalurnya Reports dan Export,
# bukan memaksa layar operasional menarik dataset raksasa.
MAX_RANGE_DAYS = config(
    "LIST_MAX_RANGE_DAYS",
    default=90,
    cast=int,
)


# Rentang bawaan saat kedua parameter kosong: tanggal 1 bulan berjalan
# sampai hari ini. Bukan "seluruh waktu", dan bukan juga jendela N hari
# ke belakang — layar presensi dibaca per bulan berjalan, dan itu yang
# ditemukan orang saat membukanya.
DEFAULT_RANGE = "current_month"


@dataclass(frozen=True)
class ListPeriod:
    start: date
    end: date

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1


def today(tz=None) -> date:
    """
    Hari ini menurut **jam dinding kantor**.

    `TIME_ZONE` aplikasi ini UTC, jadi `timezone.localdate()` tanpa
    argumen menggeser tanggalnya tujuh jam — antara 00:00 dan 07:00 WIB
    ia menjawab "kemarin", dan rentang bawaan akan kehilangan hari
    berjalan tepat pada shift malam. Alasan yang sama dengan
    `SelfAttendanceService._today()`.
    """
    if tz is None:
        # Diimpor di dalam supaya modul ini tidak menarik seluruh
        # rantai jadwal presensi hanya untuk mengetahui zona waktunya.
        from apps.hr.api.attendance.schedule import WALL_CLOCK_TZ

        tz = WALL_CLOCK_TZ

    return timezone.localdate(timezone=tz)


def default_period(*, anchor: date | None = None) -> ListPeriod:
    """Tanggal 1 bulan berjalan sampai hari ini."""
    anchor = anchor or today()

    return ListPeriod(
        start=anchor.replace(day=1),
        end=anchor,
    )


def parse_date(value, field: str) -> date | None:
    if value in (None, ""):
        return None

    try:
        return date.fromisoformat(str(value).strip())
    except (TypeError, ValueError):
        raise ValidationError(
            {field: "Use the date format YYYY-MM-DD."},
        )


def resolve_period(
    params,
    *,
    max_days: int | None = None,
    anchor: date | None = None,
) -> ListPeriod:
    """
    `?date_from=&date_to=` jadi rentang yang sah, atau 400.

    Rentang yang **setengah** terisi tidak dilengkapi diam-diam dengan
    hari ini: `date_from` sendirian akan membuat daftar menjawab
    pertanyaan yang tidak diajukan, dan yang membacanya tidak punya cara
    tahu batas satunya datang dari mana. Yang boleh kosong cuma keduanya
    sekaligus, dan itu berarti "pakai bawaan".
    """
    limit = MAX_RANGE_DAYS if max_days is None else max_days

    start = parse_date(params.get(FROM_PARAM), FROM_PARAM)
    end = parse_date(params.get(TO_PARAM), TO_PARAM)

    if start is None and end is None:
        return default_period(anchor=anchor)

    if start is None or end is None:
        raise ValidationError(
            f"Fill in {FROM_PARAM} and {TO_PARAM} together, or leave "
            "both empty to use the default period.",
        )

    if start > end:
        raise ValidationError(
            {FROM_PARAM: "The start date is later than the end date."},
        )

    span = (end - start).days + 1

    if limit and span > limit:
        raise ValidationError(
            {
                TO_PARAM: (
                    f"The maximum range is {limit} days per request; "
                    f"{span} days were requested. Use Reports or Export "
                    "for longer histories."
                ),
            },
        )

    return ListPeriod(start=start, end=end)


# ----------------------------------------------------------------------
# Preset — dipakai schema UI, dihitung ulang di frontend
# ----------------------------------------------------------------------
#
# Kodenya yang dikirim ke frontend, bukan tanggalnya: schema di-cache
# dan sebuah "hari ini" yang ikut ter-cache akan basi diam-diam. Yang
# menghitung tanggalnya komponen pemilih rentang, tiap kali dibuka.

PRESET_TODAY = "today"
PRESET_LAST_7_DAYS = "last_7_days"
PRESET_THIS_MONTH = "this_month"
PRESET_LAST_MONTH = "last_month"
PRESET_CUSTOM = "custom"

DEFAULT_PRESETS = (
    PRESET_TODAY,
    PRESET_LAST_7_DAYS,
    PRESET_THIS_MONTH,
    PRESET_LAST_MONTH,
    PRESET_CUSTOM,
)


def preset_period(code: str, *, anchor: date | None = None) -> ListPeriod:
    """
    Padanan backend untuk preset di layar.

    Ada supaya test bisa menanyakan "apa yang dikirim tombol Bulan Lalu"
    tanpa menjalankan browser, dan supaya kedua sisi tidak menurunkan
    tanggal preset yang sama dengan dua aturan berbeda.
    """
    anchor = anchor or today()

    if code == PRESET_TODAY:
        return ListPeriod(start=anchor, end=anchor)

    if code == PRESET_LAST_7_DAYS:
        return ListPeriod(start=anchor - timedelta(days=6), end=anchor)

    if code == PRESET_THIS_MONTH:
        return default_period(anchor=anchor)

    if code == PRESET_LAST_MONTH:
        first = anchor.replace(day=1) - timedelta(days=1)

        return ListPeriod(
            start=first.replace(day=1),
            end=first.replace(
                day=calendar.monthrange(first.year, first.month)[1],
            ),
        )

    return default_period(anchor=anchor)
