"""
Tap mana milik hari kerja yang mana.

Importer **tidak boleh** punya definisi hari kerja sendiri.
`timestamp.date()` terlihat benar sampai ada shift malam: tap pulang
25 Agustus 07:11 milik hari kerja 24 Agustus, dan mengelompokkannya ke
tanggal 25 memecah satu hari kerja jadi dua baris presensi yang
dua-duanya terlihat setengah.

Yang menjawab tetap `apps.hr.api.attendance.schedule` — resolver yang
sama yang dipakai penutup hari, seed presensi, dan laporan Period
Summary. Di sini cuma dibalik arahnya: bukan "jam berapa orang ini
seharusnya masuk pada tanggal X", tapi "tap pada jam ini masuk ke
tanggal berapa".

Caranya: coba tanggal lokal tap-nya, lalu sehari sebelumnya. Ambil
tanggal yang jendela jadwalnya (jam masuk - toleransi .. jam pulang +
toleransi) memuat tap tersebut. Kalau dua-duanya memuat, yang
jaraknya paling dekat menang; seri diputus ke tanggal yang lebih baru
supaya hasilnya bisa ditebak.

Tanpa jadwal sama sekali, tap tetap masuk — ke tanggal lokalnya, dengan
penanda bahwa jadwalnya tidak ketemu. Menolak tap yang tidak terjadwal
berarti kehilangan lembur akhir pekan dan hari libur nasional, dan
kehilangan data absensi selalu lebih buruk daripada baris yang
jadwalnya kosong.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

from apps.hr.api.attendance.schedule import (
    WALL_CLOCK_TZ,
    is_roster,
    scheduled_window,
    scheduled_work_days,
)


@dataclass
class ScheduleResolution:
    work_date: date

    scheduled_check_in: datetime | None = None
    scheduled_check_out: datetime | None = None

    # Jadwalnya ketemu untuk `work_date`?
    has_schedule: bool = False

    # Pegawai roster (jadwal dari RotationPeriod) atau kantor
    # (jadwal dari WorkCalendar / Work Schedule).
    roster_based: bool = False

    @property
    def label(self) -> str:
        if not self.has_schedule:
            return ""

        start = self.scheduled_check_in
        end = self.scheduled_check_out

        if start is None or end is None:
            return ""

        local_start = start.astimezone(WALL_CLOCK_TZ)
        local_end = end.astimezone(WALL_CLOCK_TZ)

        if local_end.date() != local_start.date():
            return (
                f"{local_start:%H:%M}–{local_end:%H:%M} (+1)"
            )

        return f"{local_start:%H:%M}–{local_end:%H:%M}"


def local_date(moment: datetime) -> date:
    """
    Tanggal **jam dinding** tap, bukan tanggal UTC-nya.

    `TIME_ZONE` proyek ini UTC, jadi tap jam 00:30 WIB tersimpan sebagai
    17:30 UTC hari sebelumnya — dan `.date()` mentah menaruhnya di hari
    yang salah tanpa suara.
    """
    return moment.astimezone(WALL_CLOCK_TZ).date()


def _work_days(
    employee,
    day: date,
    cache: dict[tuple[int, date], set[date]] | None,
) -> set[date]:
    """
    Hari terjadwal untuk satu tanggal, dengan ingatan.

    Satu file absensi sebulan berisi ribuan baris milik puluhan orang,
    dan tiap baris menanyakan dua tanggal. Tanpa ingatan ini, satu
    unggahan berarti ribuan query untuk jawaban yang berulang.
    """
    if cache is None:
        return scheduled_work_days(employee, day, day)

    key = (employee.id, day)

    if key not in cache:
        cache[key] = scheduled_work_days(employee, day, day)

    return cache[key]


def _window_for(
    employee,
    day: date,
    cache: dict[tuple[int, date], set[date]] | None,
) -> tuple[datetime | None, datetime | None]:
    return scheduled_window(
        employee,
        day,
        work_days=_work_days(employee, day, cache),
    )


def _distance(
    moment: datetime,
    start: datetime,
    end: datetime,
) -> timedelta:
    """Seberapa jauh tap di luar rentang jadwal; nol kalau di dalam."""
    if moment < start:
        return start - moment

    if moment > end:
        return moment - end

    return timedelta(0)


def resolve(
    *,
    employee,
    moment: datetime,
    grace_before_minutes: int,
    grace_after_minutes: int,
    caches: dict[str, Any] | None = None,
) -> ScheduleResolution:
    caches = caches if caches is not None else {}

    work_days_cache = caches.setdefault("work_days", {})

    base = local_date(moment)

    grace_before = timedelta(minutes=max(grace_before_minutes, 0))
    grace_after = timedelta(minutes=max(grace_after_minutes, 0))

    roster_based = is_roster(employee)

    best: tuple[timedelta, date, datetime, datetime] | None = None

    # Tanggal tap dulu, lalu sehari sebelumnya. Sehari **sesudahnya**
    # tidak ikut diperiksa dengan sengaja: shift yang dimulai sesudah
    # tap-nya terjadi bukan shift yang sedang dijalani orang itu.
    for candidate in (base, base - timedelta(days=1)):
        start, end = _window_for(employee, candidate, work_days_cache)

        if start is None or end is None:
            continue

        distance = _distance(
            moment,
            start - grace_before,
            end + grace_after,
        )

        if distance > timedelta(0):
            continue

        # Jarak diukur ke jadwal **tanpa** toleransi: tap yang benar-benar
        # di dalam jam kerja harus menang atas tap yang cuma masuk berkat
        # toleransinya.
        score = _distance(moment, start, end)

        if best is None or score < best[0]:
            best = (score, candidate, start, end)

    if best is not None:
        _score, day, start, end = best

        return ScheduleResolution(
            work_date=day,
            scheduled_check_in=start,
            scheduled_check_out=end,
            has_schedule=True,
            roster_based=roster_based,
        )

    return ScheduleResolution(
        work_date=base,
        has_schedule=False,
        roster_based=roster_based,
    )
