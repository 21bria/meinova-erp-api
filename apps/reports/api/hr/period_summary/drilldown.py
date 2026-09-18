"""
Drill-down: Summary → Detail → Source Record.

Angka laporan yang tidak bisa ditelusuri cuma bisa dipercaya atau tidak
dipercaya; tidak ada di antaranya. Yang dibalas di sini adalah **baris
yang dipakai menyusun angkanya**, bukan query baru yang kebetulan
mirip — daftarnya dibangun dari `PeriodSummary` yang sama dengan KPI dan
tabelnya, jadi "Absent 3" tidak mungkin membuka rincian berisi dua
baris.

**Tidak ada aturan HR yang dihitung di sini.** Menit telat dan pulang
cepat dibaca dari `late_minutes`/`early_leave_minutes` yang ditulis
`AttendancePolicyResolver` — sudah dipotong toleransi, jadi "08:00 →
08:27" boleh tercatat 12 menit, dan yang benar adalah 12. Selisih jam
jadwal dan jam tap **tidak pernah** dipakai sebagai durasi, di sini
maupun di frontend. Menit lembur adalah `duration_minutes` dokumennya.

Kontraknya aditif: kunci lama (`label`, `unit` hours/days, `source`,
`count`, `total`, `items[].value/detail/reference`) tetap terkirim.
Yang baru semuanya **kode stabil** (`source_code`, `detail_kind`,
`aggregate.unit`, `row_unit`) — frontend yang menerjemahkannya.

Tautan `link` menunjuk layar CURRENT (Attendance, Leave, Overtime, Roster
Schedule). Tidak ada dokumen sumber baru yang dibuat untuk laporan.
"""

from __future__ import annotations

from datetime import date

from django.utils import timezone

from apps.hr.api.attendance.schedule import WALL_CLOCK_TZ

from .metrics import (
    DRILLDOWN_METRICS,
    HOUR_METRICS,
    METRIC_LABELS,
    METRIC_UNITS,
    Metric,
    Unit,
    leave_group,
)
from .services import EmployeeSummary, HRPeriodSummaryService, PeriodSummary


class Source:
    """Kode sumber yang authoritative. Label tampilannya milik frontend."""

    ATTENDANCE = "attendance"
    LEAVE = "leave"
    OVERTIME = "overtime"
    ROSTER = "roster"


class DetailKind:
    """
    Bentuk baris rincian — menentukan kolom yang relevan di dialog.

    Dikirim backend supaya frontend tidak menebak kolom dari nama
    metrik; metrik baru cukup memilih salah satu bentuk ini.
    """

    LATE = "late"
    EARLY = "early"
    ATTENDANCE_DAY = "attendance_day"
    LEAVE = "leave"
    OVERTIME = "overtime"
    ROSTER = "roster"


# Label sumber lama (Inggris) tetap dikirim untuk klien lama.
SOURCE_LEGACY = {
    Source.ATTENDANCE: ("Attendance", "/hr/attendance"),
    Source.LEAVE: ("Leave Request", "/hr/leave"),
    Source.OVERTIME: ("Overtime", "/hr/overtime"),
    Source.ROSTER: ("Roster Schedule", "/hr/site-rotations"),
}


LEAVE_METRIC_SET = {
    Metric.ANNUAL,
    Metric.SICK,
    Metric.OTHER_LEAVE,
    Metric.UNPAID,
}


OVERTIME_METRIC_SET = {
    Metric.OT_REGULAR,
    Metric.OT_OFF,
    Metric.OT_HOLIDAY,
    Metric.OT_TOTAL,
}


ATTENDANCE_DAY_METRICS = {
    Metric.SCHEDULED,
    Metric.PRESENT,
    Metric.ABSENT,
    Metric.OFF_WORKED,
    Metric.HOLIDAY_WORKED,
}


def metric_source(metric: str) -> str:
    if metric in LEAVE_METRIC_SET:
        return Source.LEAVE

    if metric in OVERTIME_METRIC_SET:
        return Source.OVERTIME

    if metric == Metric.FIELD_BREAK:
        return Source.ROSTER

    return Source.ATTENDANCE


def metric_kind(metric: str) -> str:
    if metric == Metric.LATE:
        return DetailKind.LATE

    if metric == Metric.EARLY:
        return DetailKind.EARLY

    if metric in LEAVE_METRIC_SET:
        return DetailKind.LEAVE

    if metric in OVERTIME_METRIC_SET:
        return DetailKind.OVERTIME

    if metric == Metric.FIELD_BREAK:
        return DetailKind.ROSTER

    return DetailKind.ATTENDANCE_DAY


# Metrik yang durasinya fakta kedua di kepala dialog. Hari kehadiran
# sengaja tidak: jam kerja per baris tetap ditampilkan, tapi "3 hari ·
# total 24j" menaruh dua fakta yang tidak saling menjelaskan di satu
# kalimat.
DURATION_METRICS = {Metric.LATE, Metric.EARLY} | OVERTIME_METRIC_SET


# Kolom menit per metrik (menit mentah, excused).
ATTENDANCE_MINUTE_FIELDS = {
    Metric.LATE: (
        "scheduled_check_in",
        "check_in",
        "late_minutes",
        "excused_late_minutes",
    ),
    Metric.EARLY: (
        "scheduled_check_out",
        "check_out",
        "early_leave_minutes",
        "excused_early_leave_minutes",
    ),
}


class UnknownMetric(ValueError):
    pass


class InvalidEmployee(ValueError):
    pass


class EmployeeNotVisible(LookupError):
    """
    Pegawai yang diminta tidak ada di populasi laporan pemanggil.

    Satu jawaban untuk "tidak ada", "di luar cakupan data", dan "di luar
    filter" — membedakannya berarti memberi tahu bahwa id itu ada.
    """


class HRPeriodSummaryDrilldown:
    service = HRPeriodSummaryService

    @classmethod
    def resolve(
        cls,
        context: dict,
        *,
        metric: str,
        employee_id: int | None = None,
        limit: int = 500,
    ) -> dict:
        if metric not in DRILLDOWN_METRICS:
            raise UnknownMetric(
                f"Metrik '{metric}' tidak bisa ditelusuri. "
                f"Pilihan: {', '.join(sorted(DRILLDOWN_METRICS))}.",
            )

        summary: PeriodSummary = cls.service.summary(context)

        subject = None

        if employee_id is not None:
            subject = next(
                (row for row in summary.rows if row.employee_id == employee_id),
                None,
            )

            # Populasi laporan sudah melewati cakupan data. Pegawai yang
            # tidak ada di sana tidak dibalas sebagai daftar kosong —
            # daftar kosong terbaca "orang ini tidak punya catatan",
            # yang juga sebuah informasi tentang orang itu.
            if subject is None:
                raise EmployeeNotVisible(employee_id)

        # Aturan yang sama dengan `PeriodSummary.total()`: baris yang
        # prosesnya tidak berlaku dilewati. Sumber angkanya dan sumber
        # rinciannya harus satu daftar — kalau tidak, "Absent 3" bisa
        # membuka rincian berisi 4 baris, dan yang membacanya akan
        # menyimpulkan salah satunya salah.
        rows = [
            row
            for row in summary.rows
            if (employee_id is None or row.employee_id == employee_id)
            and row.counts(metric)
        ]

        items: list[dict] = []

        for row in rows:
            items.extend(cls._rows_for(row, metric))

        items.sort(key=lambda item: (item["date"], item["employee"]))

        source_code = metric_source(metric)
        source, link = SOURCE_LEGACY[source_code]
        unit = METRIC_UNITS[metric]

        # **Accessor yang sama dengan tabel dan baris Total**, atas
        # baris yang sama. Bukan penjumlahan ulang nilai per item:
        # jam lembur dibulatkan per pegawai di tabel, dan menjumlahkan
        # jam per dokumen yang sudah dibulatkan menghasilkan 0,99 untuk
        # angka yang di tabel tertulis 1,0.
        aggregate = float(
            PeriodSummary(start=summary.start, end=summary.end, rows=rows)
            .total(metric),
        )

        duration_minutes = None
        duration_complete = True

        if metric in DURATION_METRICS:
            known = [
                item["duration_minutes"]
                for item in items
                if item["duration_minutes"] is not None
            ]
            duration_minutes = sum(known)
            duration_complete = len(known) == len(items)

        return {
            "metric": metric,
            "label": METRIC_LABELS.get(metric, metric),
            # Kunci lama, dipertahankan untuk klien yang sudah ada.
            "unit": "hours" if metric in HOUR_METRICS else "days",
            "source": source,
            "link": link,
            "period": {"start": summary.start, "end": summary.end},
            "count": len(items),
            "total": aggregate,
            "truncated": len(items) > limit,
            "items": items[:limit],
            # ---- kontrak audit (aditif) ----
            "source_code": source_code,
            "detail_kind": metric_kind(metric),
            "aggregate": {"value": aggregate, "unit": unit},
            "occurrences": len(items),
            # Dijumlahkan dari **seluruh** baris, bukan halaman yang
            # terpotong `limit`.
            "duration_minutes": duration_minutes,
            # False = ada kejadian yang terhitung (mis. status LATE dari
            # import) tanpa menit yang tercatat. Totalnya tidak ditebak.
            "duration_complete": duration_complete,
            "employee": (
                {
                    "id": subject.employee_id,
                    "name": subject.employee_name,
                    "number": subject.employee_number,
                }
                if subject is not None
                else None
            ),
        }

    # ------------------------------------------------------------------

    @staticmethod
    def _base(row: EmployeeSummary, day: date, metric: str) -> dict:
        return {
            "employee": row.employee_name,
            "employee_id": row.employee_id,
            "employee_number": row.employee_number,
            "location": row.location,
            "date": day,
            "source_code": metric_source(metric),
            "status": "",
            "reference": "",
            "record_id": None,
            "scheduled_time": None,
            "actual_time": None,
            "start_time": None,
            "end_time": None,
            "duration_minutes": None,
        }

    @classmethod
    def _rows_for(cls, row: EmployeeSummary, metric: str) -> list[dict]:
        if metric in LEAVE_METRIC_SET:
            return [
                {
                    **cls._base(row, detail.day, metric),
                    "value": float(detail.days),
                    "quantity": float(detail.days),
                    "row_unit": Unit.DAY,
                    # Tipe cuti **aslinya**, bukan kelompok laporannya.
                    # "Other Leave" tidak pernah menjadi jawaban di
                    # layar rincian — yang dicari orang justru cuti apa.
                    "detail": detail.leave_type_name,
                    "detail_code": detail.leave_type_code,
                    "reference": detail.document_number,
                    "status": detail.status,
                    "record_id": detail.leave_id,
                    "range_start": detail.leave_start,
                    "range_end": detail.leave_end,
                }
                for detail in row.leave_details
                if leave_group(detail.leave_type_code) == metric
            ]

        if metric in OVERTIME_METRIC_SET:
            days = set(row.days_by_metric.get(metric, []))

            return [
                {
                    **cls._base(row, detail.day, metric),
                    "value": round(detail.minutes / 60, 2),
                    "quantity": round(detail.minutes / 60, 2),
                    "row_unit": Unit.HOUR,
                    "detail": detail.overtime_type,
                    "detail_code": "",
                    # `reference` lama berisi alasan; dipertahankan.
                    # Lembur belum punya nomor dokumen maupun approval.
                    "reference": detail.reason,
                    "reason": detail.reason,
                    "record_id": detail.overtime_id,
                    "start_time": _clock(detail.start_time),
                    "end_time": _clock(detail.end_time),
                    "duration_minutes": detail.minutes,
                }
                for detail in row.overtime_details
                if detail.day in days
            ]

        if metric in ATTENDANCE_MINUTE_FIELDS:
            scheduled_field, actual_field, minutes_field, excused_field = (
                ATTENDANCE_MINUTE_FIELDS[metric]
            )

            items = []

            for day in row.days_by_metric.get(metric, []):
                record = row.attendance_records.get(day) or {}
                minutes = record.get(minutes_field) or 0

                items.append({
                    **cls._base(row, day, metric),
                    "value": 1.0,
                    "quantity": 1,
                    "row_unit": Unit.OCCURRENCE,
                    "detail": METRIC_LABELS.get(metric, metric),
                    "detail_code": metric,
                    "status": record.get("status") or "",
                    "record_id": record.get("id"),
                    "scheduled_time": _wall_clock(record.get(scheduled_field)),
                    "actual_time": _wall_clock(record.get(actual_field)),
                    # `None`, bukan 0: status LATE hasil import tanpa
                    # menit tetap satu kejadian, tapi durasinya tidak
                    # terbukti dan tidak boleh ditebak dari jam tap.
                    "duration_minutes": minutes or None,
                    "excused_minutes": record.get(excused_field) or 0,
                })

            return items

        if metric in ATTENDANCE_DAY_METRICS:
            items = []

            for day in row.days_by_metric.get(metric, []):
                record = row.attendance_records.get(day) or {}

                items.append({
                    **cls._base(row, day, metric),
                    "value": 1.0,
                    "quantity": 1,
                    "row_unit": Unit.DAY,
                    "detail": METRIC_LABELS.get(metric, metric),
                    "detail_code": metric,
                    "status": record.get("status") or "",
                    "record_id": record.get("id"),
                    "start_time": _wall_clock(record.get("check_in")),
                    "end_time": _wall_clock(record.get("check_out")),
                    "duration_minutes": record.get("worked_minutes") or None,
                })

            return items

        return [
            {
                **cls._base(row, day, metric),
                "value": 1.0,
                "quantity": 1,
                "row_unit": Unit.DAY,
                "detail": METRIC_LABELS.get(metric, metric),
                "detail_code": metric,
            }
            for day in row.days_by_metric.get(metric, [])
        ]


def _wall_clock(value) -> str | None:
    """Jam dinding zona jadwal — sama dengan `/me/attendance`."""
    return timezone.localtime(value, WALL_CLOCK_TZ).strftime("%H:%M") if value else None


def _clock(value) -> str | None:
    return value.strftime("%H:%M") if value else None


def parse_date(raw: str | None) -> date | None:
    if not raw:
        return None

    try:
        return date.fromisoformat(str(raw))
    except ValueError:
        return None


def parse_employee_id(raw) -> int | None:
    """
    `None` kalau tidak disebut; `InvalidEmployee` kalau disebut tapi
    bukan id. Dulu nilai rusak diam-diam dibaca "seluruh pegawai".
    """
    if raw in (None, ""):
        return None

    text = str(raw).strip()

    if not text.isdigit():
        raise InvalidEmployee(text)

    return int(text)
