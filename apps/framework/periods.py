"""
Periode dashboard: satu tempat untuk mengubah query string jadi rentang
tanggal yang bisa dipakai resolver widget.

Sebelumnya dashboard hanya mengenal `?year=&month=`, jadi seluruh angka
terkunci ke satu bulan penuh. Sekarang periodenya berupa **rentang** —
harian, mingguan, bulanan, kuartalan, tahunan, atau tanggal bebas — dan
resolver cukup membaca `period["start"]`/`period["end"]` tanpa perlu tahu
mode mana yang sedang aktif.

`year`/`month` tetap ikut dikembalikan supaya pemanggil lama (dan chart
yang memang berpikir per tahun) tidak perlu ikut diubah.

Awal minggu = Senin, mengikuti kebiasaan kalender kerja di Indonesia.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta


PERIOD_MODES = (
    "day",
    "week",
    "month",
    "quarter",
    "year",
    "custom",
)

DEFAULT_PERIOD_MODES = ("day", "week", "month", "custom")

MONTH_NAMES = [
    "Januari",
    "Februari",
    "Maret",
    "April",
    "Mei",
    "Juni",
    "Juli",
    "Agustus",
    "September",
    "Oktober",
    "November",
    "Desember",
]

MONTH_ABBR = [
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "Mei",
    "Jun",
    "Jul",
    "Agu",
    "Sep",
    "Okt",
    "Nov",
    "Des",
]

DAY_ABBR = ["Sen", "Sel", "Rab", "Kam", "Jum", "Sab", "Min"]

ROMAN_QUARTER = ["I", "II", "III", "IV"]

# Kalimat pembanding pada kartu KPI ("Naik 4% dari bulan lalu").
COMPARE_LABELS = {
    "day": "dari hari sebelumnya",
    "week": "dari minggu lalu",
    "month": "dari bulan lalu",
    "quarter": "dari kuartal lalu",
    "year": "dari tahun lalu",
    "custom": "dari periode sebelumnya",
}

MIN_YEAR = 2000
MAX_YEAR = 2100

# Rentang bebas dibatasi supaya satu request tidak menyapu data
# bertahun-tahun tanpa sengaja (mis. salah ketik tahun).
MAX_CUSTOM_DAYS = 366 * 3


# ----------------------------------------------------------------------
# Helper tanggal
# ----------------------------------------------------------------------


def month_bounds(year: int, month: int) -> tuple[date, date]:
    last_day = calendar.monthrange(year, month)[1]

    return date(year, month, 1), date(year, month, last_day)


def add_months(anchor: date, months: int) -> date:
    """
    Geser bulan sambil menjaga tanggalnya tetap valid — 31 Maret mundur
    satu bulan jadi 28/29 Februari, bukan error.
    """
    total = anchor.year * 12 + (anchor.month - 1) + months
    year, month = divmod(total, 12)
    month += 1

    last_day = calendar.monthrange(year, month)[1]

    return date(year, month, min(anchor.day, last_day))


def week_bounds(anchor: date) -> tuple[date, date]:
    start = anchor - timedelta(days=anchor.weekday())

    return start, start + timedelta(days=6)


def quarter_bounds(anchor: date) -> tuple[date, date]:
    index = (anchor.month - 1) // 3
    start_month = index * 3 + 1

    start = date(anchor.year, start_month, 1)
    _, end = month_bounds(anchor.year, start_month + 2)

    return start, end


def clamp_year(year: int) -> int:
    return max(MIN_YEAR, min(MAX_YEAR, year))


def parse_date(raw: str | None) -> date | None:
    if not raw:
        return None

    try:
        value = date.fromisoformat(str(raw)[:10])
    except (TypeError, ValueError):
        return None

    if not (MIN_YEAR <= value.year <= MAX_YEAR):
        return None

    return value


# ----------------------------------------------------------------------
# Rentang
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class PeriodRange:
    mode: str
    start: date
    end: date

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def as_dict(self) -> dict:
        return {
            "mode": self.mode,
            "start": self.start,
            "end": self.end,
            "label": label_for(self),
            "days": self.days,
        }


def bounds_for(mode: str, anchor: date) -> PeriodRange:
    if mode == "day":
        return PeriodRange("day", anchor, anchor)

    if mode == "week":
        start, end = week_bounds(anchor)

        return PeriodRange("week", start, end)

    if mode == "quarter":
        start, end = quarter_bounds(anchor)

        return PeriodRange("quarter", start, end)

    if mode == "year":
        return PeriodRange(
            "year",
            date(anchor.year, 1, 1),
            date(anchor.year, 12, 31),
        )

    start, end = month_bounds(anchor.year, anchor.month)

    return PeriodRange("month", start, end)


def previous_of(period: PeriodRange) -> PeriodRange:
    """
    Periode pembanding. Untuk mode kalender (bulan/kuartal/tahun) yang
    dipakai adalah periode kalender sebelumnya — bukan "geser sekian
    hari" — supaya Februari dibandingkan dengan Januari penuh, bukan
    dengan 28 hari terakhir bulan Januari.
    """
    if period.mode == "day":
        anchor = period.start - timedelta(days=1)

        return bounds_for("day", anchor)

    if period.mode == "week":
        return bounds_for("week", period.start - timedelta(days=7))

    if period.mode == "month":
        return bounds_for("month", add_months(period.start, -1))

    if period.mode == "quarter":
        return bounds_for("quarter", add_months(period.start, -3))

    if period.mode == "year":
        return bounds_for("year", date(period.start.year - 1, 1, 1))

    # Rentang bebas: jendela sepanjang yang sama tepat sebelum start.
    end = period.start - timedelta(days=1)
    start = end - timedelta(days=period.days - 1)

    return PeriodRange("custom", start, end)


def label_for(period: PeriodRange) -> str:
    start, end = period.start, period.end

    if period.mode == "day":
        return f"{start.day} {MONTH_NAMES[start.month - 1]} {start.year}"

    if period.mode == "month":
        return f"{MONTH_NAMES[start.month - 1]} {start.year}"

    if period.mode == "quarter":
        index = (start.month - 1) // 3

        return f"Kuartal {ROMAN_QUARTER[index]} {start.year}"

    if period.mode == "year":
        return str(start.year)

    # Minggu & rentang bebas: bagian yang sama (bulan/tahun) tidak
    # diulang supaya labelnya tidak sepanjang kalimat.
    if start.year != end.year:
        return (
            f"{start.day} {MONTH_ABBR[start.month - 1]} {start.year} – "
            f"{end.day} {MONTH_ABBR[end.month - 1]} {end.year}"
        )

    if start.month != end.month:
        return (
            f"{start.day} {MONTH_ABBR[start.month - 1]} – "
            f"{end.day} {MONTH_ABBR[end.month - 1]} {end.year}"
        )

    if start == end:
        return f"{start.day} {MONTH_NAMES[start.month - 1]} {start.year}"

    return (
        f"{start.day} – {end.day} "
        f"{MONTH_NAMES[start.month - 1]} {start.year}"
    )


# ----------------------------------------------------------------------
# Resolusi dari query string
# ----------------------------------------------------------------------


def resolve_period(
    params,
    *,
    default_mode: str = "month",
    allowed_modes: tuple[str, ...] | None = None,
    today: date | None = None,
) -> dict:
    """
    Membaca `?mode=&start=&end=` (dengan `?year=&month=` sebagai jalur
    lama) menjadi satu dict periode.

    Nilai yang tidak masuk akal diabaikan dan jatuh ke default, bukan
    dibalas error — dashboard tidak boleh mati gara-gara satu query
    param salah ketik.
    """
    today = today or date.today()
    allowed = tuple(allowed_modes or PERIOD_MODES)

    mode = (params.get("mode") or "").strip().lower()

    if mode not in allowed:
        mode = default_mode if default_mode in allowed else allowed[0]

    start = parse_date(params.get("start"))
    end = parse_date(params.get("end"))

    if mode == "custom":
        if start and end:
            if end < start:
                start, end = end, start

            span = (end - start).days + 1

            if span > MAX_CUSTOM_DAYS:
                end = start + timedelta(days=MAX_CUSTOM_DAYS - 1)

            period = PeriodRange("custom", start, end)
        else:
            # Tanpa tanggal yang jelas, "kustom" tidak punya arti —
            # jatuh ke bulan berjalan daripada menebak.
            period = bounds_for("month", today)
    else:
        anchor = start or _legacy_anchor(params, today)
        period = bounds_for(mode, anchor)

    previous = previous_of(period)

    data = period.as_dict()
    data.update(
        {
            "year": period.start.year,
            "month": period.start.month,
            "previous": previous.as_dict(),
            "compare_label": COMPARE_LABELS.get(
                period.mode,
                COMPARE_LABELS["custom"],
            ),
        }
    )

    return data


def _legacy_anchor(params, today: date) -> date:
    """
    Jalur `?year=&month=` dipertahankan karena frontend yang belum
    diregenerate masih mengirimnya.
    """

    def read_int(name, default, minimum, maximum):
        raw = params.get(name)

        if raw in (None, ""):
            return default

        try:
            value = int(raw)
        except (TypeError, ValueError):
            return default

        if value < minimum or value > maximum:
            return default

        return value

    year = read_int("year", today.year, MIN_YEAR, MAX_YEAR)
    month = read_int("month", today.month, 1, 12)

    last_day = calendar.monthrange(year, month)[1]

    return date(year, month, min(today.day, last_day))


# ----------------------------------------------------------------------
# Bucket untuk chart tren
# ----------------------------------------------------------------------


def trend_buckets(period: dict, *, count: int = 12) -> list[dict]:
    """
    Deret titik untuk chart tren: selalu berakhir di periode terpilih dan
    mundur `count` langkah dengan satuan yang mengikuti mode.

    Dibuat begini supaya chart tetap berisi walau periodenya satu hari —
    "tren" satu titik tidak memberi tahu apa-apa. Untuk rentang bebas,
    satuannya dipilih dari panjang rentang: harian untuk rentang pendek,
    mingguan untuk menengah, bulanan untuk yang panjang.
    """
    mode = period.get("mode", "month")
    end = period["end"]
    start = period["start"]

    if mode == "custom":
        span = (end - start).days + 1

        if span <= 31:
            unit = "day"
        elif span <= 180:
            unit = "week"
        else:
            unit = "month"

        return _buckets_within(unit, start, end)

    unit = {
        "day": "day",
        "week": "week",
        "month": "month",
        "quarter": "quarter",
        "year": "month",
    }.get(mode, "month")

    if mode == "year":
        # Satu tahun penuh dibaca per bulan — dua belas titik, persis
        # jumlah bulannya.
        return _buckets_within("month", start, end)

    return _buckets_backwards(unit, end, count)


def _bucket(unit: str, anchor: date) -> tuple[date, date, str]:
    if unit == "day":
        return (
            anchor,
            anchor,
            f"{DAY_ABBR[anchor.weekday()]} {anchor.day}",
        )

    if unit == "week":
        start, end = week_bounds(anchor)

        return start, end, f"{start.day} {MONTH_ABBR[start.month - 1]}"

    if unit == "quarter":
        start, end = quarter_bounds(anchor)
        index = (start.month - 1) // 3

        return start, end, f"Q{index + 1} {str(start.year)[-2:]}"

    start, end = month_bounds(anchor.year, anchor.month)

    return start, end, MONTH_ABBR[start.month - 1]


def _step_back(unit: str, anchor: date, steps: int) -> date:
    if unit == "day":
        return anchor - timedelta(days=steps)

    if unit == "week":
        return anchor - timedelta(days=7 * steps)

    if unit == "quarter":
        return add_months(anchor, -3 * steps)

    return add_months(anchor.replace(day=1), -steps)


def _buckets_backwards(unit: str, end: date, count: int) -> list[dict]:
    buckets = []

    for step in range(count - 1, -1, -1):
        anchor = _step_back(unit, end, step)
        start, stop, label = _bucket(unit, anchor)

        buckets.append({"label": label, "start": start, "end": stop})

    return _disambiguate_years(unit, buckets)


def _disambiguate_years(unit: str, buckets: list[dict]) -> list[dict]:
    """
    Deret mundur 12 bulan bisa melewati pergantian tahun, dan "Agu" di
    ujung kiri lalu "Agu" lagi di ujung kanan terbaca seperti dua titik
    untuk bulan yang sama. Tahunnya ditempelkan hanya kalau memang ada
    lebih dari satu tahun di deret itu.
    """
    if unit not in ("month", "week"):
        return buckets

    years = {item["start"].year for item in buckets}

    if len(years) < 2:
        return buckets

    for item in buckets:
        item["label"] = f"{item['label']} '{str(item['start'].year)[-2:]}"

    return buckets


def _buckets_within(unit: str, start: date, end: date) -> list[dict]:
    buckets = []
    cursor = start

    while cursor <= end:
        bucket_start, bucket_end, label = _bucket(unit, cursor)

        buckets.append(
            {
                "label": label,
                # Bucket pertama dan terakhir dipotong ke rentangnya
                # supaya angkanya tidak memasukkan tanggal di luar
                # periode yang diminta.
                "start": max(bucket_start, start),
                "end": min(bucket_end, end),
            }
        )

        cursor = bucket_end + timedelta(days=1)

    return buckets
