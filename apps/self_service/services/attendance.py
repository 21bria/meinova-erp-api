"""
Kehadiran Saya — presentasi periode, bukan pemilik aturan.

Tidak satu pun aturan kehadiran lahir di berkas ini. Yang mengklasifikasi
hari (terjadwal / hadir / terlambat / cuti / mangkir) tetap
`HRPeriodSummaryService` milik Reports; yang menentukan hari terjadwal
tetap `scheduled_work_days_bulk`; yang menghitung menit terlambat tetap
`AttendancePolicyResolver` yang sudah menuliskannya ke barisnya. Yang
dikerjakan di sini cuma tiga hal:

1. mengubah query string jadi rentang tanggal yang sah,
2. memanggil perhitungan kanonik untuk **satu** pegawai — yang sedang
   login — lalu membaca hasilnya,
3. mengambil barisnya sendiri, terurut dan terpotong **di database**.

**Kenapa lewat `HRPeriodSummaryService.build_for()` dan bukan
`build()`.** `build()` menyaring populasinya dengan `DataScopeService`
plus `hr.view_employee`; pegawai biasa tidak punya izin itu, jadi lewat
sana ia tidak akan menemukan barisnya sendiri. `build_for()` mengerjakan
populasi yang diberikan pemanggil — dan populasi yang diberikan di sini
selalu tepat satu orang, hasil `CurrentEmployeeService`. Identitasnya
karena itu tidak pernah datang dari permintaan.

**Kenapa angka lembur di sini bisa berbeda dari kartu Lembur `/me`.**
Keduanya membaca `EmployeeOvertime`, tapi dengan saringan status yang
berbeda: halaman ini memakai aturan Reports (`RECORDED`), kartu `/me`
memakai aturan Payroll (`RECORDED` + `APPROVED` dan `is_paid`). Selisih
itu **sudah ada sebelum halaman ini** dan sengaja tidak diselesaikan
sepihak di sini — memilih aturan ketiga berarti menambah tafsir, bukan
mengurangi. Catatannya ada di `docs/claude/self-service.md`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

from django.core.paginator import Paginator
from django.db.models import Sum
from django.utils import timezone

from rest_framework.exceptions import ValidationError

from apps.hr.api.attendance.schedule import WALL_CLOCK_TZ
from apps.hr.models import EmployeeAttendance
from apps.reports.api.hr.period_summary.metrics import LEAVE_METRICS, Metric
from apps.reports.api.hr.period_summary.services import HRPeriodSummaryService


# ----------------------------------------------------------------------
# Kontrak rentang
# ----------------------------------------------------------------------

# Tanpa parameter: seminggu terakhir, hari ini ikut. Bukan "bulan ini" —
# awal bulan halaman ini akan terbuka dengan satu baris, dan bukan
# seluruh histori, yang justru pertanyaan yang tidak pernah ditanyakan
# siapa pun.
DEFAULT_RANGE_DAYS = 7

# Batas atas satu permintaan. Angkanya dipilih supaya **setiap preset
# muat**: preset terpanjang 30 hari, bulan terpanjang 31 hari, jadi 90
# memberi ruang tiga kali lipat tanpa pernah membuat preset gagal.
#
# Batas ini bukan soal performa satu pegawai — 90 baris presensi tidak
# berat. Ia menjaga **bentuk permintaannya**: tanpa batas, satu URL yang
# diketik tangan (`date_from=2000-01-01`) menarik seluruh histori,
# menghitung roster dua puluh tahun, lalu mengembalikannya sebagai satu
# balasan. Yang menolaknya harus backend; frontend tidak pernah jadi
# batas.
MAX_RANGE_DAYS = 90

DEFAULT_PAGE_SIZE = 10
PAGE_SIZES = (10, 25, 50)


# ----------------------------------------------------------------------
# Hasil per hari
# ----------------------------------------------------------------------

# Nilai `outcome` yang boleh muncul di deret harian. Dibaca frontend
# sebagai kode — labelnya ada di katalog i18n, bukan di sini.
PRESENT = "present"
LATE = "late"
ABSENT = "absent"
LEAVE = "leave"
# Hari dinas tanpa tap (BT-3R) — bukan hadir, bukan mangkir.
BUSINESS_TRIP = "business_trip"
EXTRA = "extra"
OFF = "off"


@dataclass(frozen=True)
class DateRange:
    start: date
    end: date

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def shifted(self, direction: int) -> "DateRange":
        """
        Periode sebelum/sesudah, **selebar periode ini**.

        Bukan "bulan sebelumnya": rentang 14 hari yang digeser mundur
        harus tetap 14 hari, kalau tidak tombol panah diam-diam
        mengubah pertanyaannya.
        """
        span = timedelta(days=self.days)

        return DateRange(
            start=self.start + direction * span,
            end=self.end + direction * span,
        )


def _today() -> date:
    """
    Hari ini menurut **jam dinding kantor**.

    `TIME_ZONE` aplikasi ini UTC, jadi `timezone.localdate()` tanpa
    argumen menggeser tanggal tujuh jam — dan antara pukul 00:00 dan
    07:00 WIB ia menjawab "kemarin". Alasan yang sama dengan
    `SelfWorkspaceService.today()`.
    """
    return timezone.localdate(timezone=WALL_CLOCK_TZ)


def _parse(value, field: str) -> date | None:
    if value in (None, ""):
        return None

    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        raise ValidationError({field: "Gunakan format tanggal YYYY-MM-DD."})


def _wall_clock(value) -> str | None:
    return timezone.localtime(value, WALL_CLOCK_TZ).strftime("%H:%M") if value else None


class SelfAttendanceService:
    """
    Perakit `GET /api/me/attendance/`.

    Tidak punya method yang menulis, dan tidak punya satu pun cabang yang
    membaca identitas dari permintaan — pegawainya selalu diterima
    sebagai argumen dari pemanggil yang sudah menyelesaikannya.
    """

    # ------------------------------------------------------------------
    # Rentang
    # ------------------------------------------------------------------

    @classmethod
    def resolve_range(cls, *, date_from=None, date_to=None) -> DateRange:
        """
        Query string jadi rentang yang sah, atau 400 yang menyebut
        sebabnya.

        Rentang yang tidak lengkap **tidak** dilengkapi diam-diam dengan
        hari ini: `date_from` sendirian akan membuat halaman menjawab
        pertanyaan yang tidak diajukan. Yang boleh kosong cuma keduanya
        sekaligus, dan itu berarti "pakai bawaan".
        """
        start = _parse(date_from, "date_from")
        end = _parse(date_to, "date_to")

        if start is None and end is None:
            today = _today()

            return DateRange(
                start=today - timedelta(days=DEFAULT_RANGE_DAYS - 1),
                end=today,
            )

        if start is None or end is None:
            raise ValidationError(
                "Isi date_from dan date_to sekaligus, atau kosongkan "
                "keduanya untuk memakai rentang bawaan.",
            )

        if start > end:
            raise ValidationError(
                {"date_from": "Tanggal awal melewati tanggal akhir."},
            )

        span = (end - start).days + 1

        if span > MAX_RANGE_DAYS:
            raise ValidationError(
                {
                    "date_to": (
                        f"Rentang maksimal {MAX_RANGE_DAYS} hari per "
                        f"permintaan; yang diminta {span} hari."
                    ),
                },
            )

        return DateRange(start=start, end=end)

    @classmethod
    def resolve_page_size(cls, value) -> int:
        if value in (None, ""):
            return DEFAULT_PAGE_SIZE

        try:
            size = int(value)
        except (TypeError, ValueError):
            raise ValidationError({"page_size": "Harus berupa angka."})

        # Daftar tertutup, bukan batas atas. Halaman ini menawarkan tiga
        # pilihan; menerima `page_size=90` berarti menerima permintaan
        # yang tidak pernah bisa datang dari layarnya sendiri.
        if size not in PAGE_SIZES:
            raise ValidationError(
                {
                    "page_size": (
                        "Pilihan yang tersedia: "
                        + ", ".join(str(n) for n in PAGE_SIZES)
                        + "."
                    ),
                },
            )

        return size

    # ------------------------------------------------------------------
    # Perakitan
    # ------------------------------------------------------------------

    @classmethod
    def build(
        cls,
        *,
        employee,
        date_from=None,
        date_to=None,
        page=None,
        page_size=None,
    ) -> tuple[dict, dict]:
        """
        Satu jawaban berisi rentang, ringkasan, deret harian, dan satu
        halaman riwayat — plus `meta` paginasinya.

        Ringkasan dan tabel dirakit dari **satu** perhitungan untuk
        rentang yang sama. Membelahnya jadi dua endpoint membuat kartu
        "Tidak Hadir 3" bisa berdiri di atas tabel yang periodenya sudah
        berganti, tanpa satu pun tanda bahwa keduanya menjawab
        pertanyaan berbeda.
        """
        span = cls.resolve_range(date_from=date_from, date_to=date_to)
        size = cls.resolve_page_size(page_size)

        summary = HRPeriodSummaryService.build_for(
            [employee],
            span.start,
            span.end,
        )

        row = summary.rows[0]

        history, meta = cls._history(
            employee=employee,
            span=span,
            page=page,
            page_size=size,
            overtime_by_day=cls._overtime_by_day(row),
        )

        return (
            {
                "range": cls._range(span),
                "summary": cls._summary(employee, row, span),
                "daily": cls._daily(row, span),
                "history": history,
            },
            meta,
        )

    # ------------------------------------------------------------------
    # Rentang → payload
    # ------------------------------------------------------------------

    @classmethod
    def _range(cls, span: DateRange) -> dict:
        today = _today()

        previous = span.shifted(-1)

        # Tidak ada tombol "berikutnya" saat periodenya sudah menyentuh
        # hari ini. Presensi besok belum ada dan tidak akan ada; panah
        # yang membuka halaman kosong berulang kali terbaca seperti
        # data yang hilang.
        forward = span.shifted(1) if span.end < today else None

        return {
            "date_from": span.start.isoformat(),
            "date_to": span.end.isoformat(),
            "days": span.days,
            "max_days": MAX_RANGE_DAYS,
            "page_sizes": list(PAGE_SIZES),
            "previous": {
                "date_from": previous.start.isoformat(),
                "date_to": previous.end.isoformat(),
            },
            "next": {
                "date_from": forward.start.isoformat(),
                "date_to": forward.end.isoformat(),
            } if forward else None,
        }

    # ------------------------------------------------------------------
    # Ringkasan
    # ------------------------------------------------------------------

    @classmethod
    def _summary(cls, employee, row, span: DateRange) -> dict:
        """
        Delapan angka, masing-masing membawa **apakah ia berlaku**.

        `available: false` bukan sinonim nol. Pegawai yang Employee
        Group-nya mematikan proses Attendance tidak punya angka hadir —
        bukan punya angka hadir yang kebetulan nol — dan layar yang
        menerima nol untuk keduanya akan menampilkan "Tidak Hadir 0"
        kepada orang yang memang tidak pernah diabsen.
        """
        attendance = row.counts(Metric.SCHEDULED)

        return {
            "work_days": cls._value(row, Metric.SCHEDULED),
            "present": cls._value(row, Metric.PRESENT),
            "late": cls._value(row, Metric.LATE),
            "absent": cls._value(row, Metric.ABSENT),
            # Aditif (BT-3R): sejak dinas tidak lagi dihitung `present`,
            # harinya punya angkanya sendiri.
            "business_trip": cls._value(row, Metric.BUSINESS_TRIP),
            "leave_days": {
                # `leave_total` menjumlahkan keempat kelompok cuti
                # laporan (tahunan, sakit, lainnya, tanpa bayar) dengan
                # setengah hari tetap 0,5 — sama persis dengan yang
                # memotong saldo orangnya.
                "value": float(row.leave_total),
                "available": row.counts(LEAVE_METRICS[0]),
            },
            "worked_minutes": {
                "value": cls._worked_minutes(employee, span) if attendance else 0,
                "available": attendance,
            },
            "overtime_minutes": {
                "value": row.ot_total_minutes,
                "available": row.counts(Metric.OT_TOTAL),
            },
        }

    @staticmethod
    def _value(row, metric: str) -> dict:
        return {
            "value": row.metric(metric) if row.counts(metric) else 0,
            "available": row.counts(metric),
        }

    @staticmethod
    def _worked_minutes(employee, span: DateRange) -> int:
        """
        Jumlah `worked_minutes` seluruh baris di rentang ini.

        **Penjumlahan, bukan perhitungan.** Angkanya sudah dituliskan
        `AttendancePolicyResolver` saat baris presensinya dihitung; yang
        dikerjakan di sini cuma `SUM`, dan `SUM`-nya dikerjakan
        PostgreSQL — bukan Python atas baris yang ditarik dulu.

        Sengaja **tidak** disaring status: jam yang benar-benar dijalani
        di hari libur tetap jam yang dijalani. Yang menyaring per jenis
        hari adalah kolom lembur, dan itu punya sumbernya sendiri.
        """
        return (
            EmployeeAttendance.objects
            .filter(
                employee=employee,
                is_deleted=False,
                work_date__gte=span.start,
                work_date__lte=span.end,
            )
            .aggregate(total=Sum("worked_minutes"))
            ["total"]
            or 0
        )

    # ------------------------------------------------------------------
    # Deret harian
    # ------------------------------------------------------------------

    @classmethod
    def _daily(cls, row, span: DateRange) -> list[dict]:
        """
        Satu entri per tanggal di rentang, dibaca **dari hasil
        klasifikasi yang sama** dengan kartu ringkasannya.

        `days_by_metric` adalah daftar tanggal yang dipakai laporan HR
        untuk drill-down; membacanya di sini berarti strip harian dan
        angka di atasnya tidak mungkin menghitung hari yang berbeda.
        Merakit ulang klasifikasinya dari baris presensi — betapapun
        mudahnya kelihatan — adalah salinan aturan kedua.
        """
        if not row.counts(Metric.SCHEDULED):
            return []

        outcome: dict[date, str] = {}

        for metric in LEAVE_METRICS:
            for day in row.days_by_metric.get(metric, ()):
                outcome[day] = LEAVE

        for day in row.days_by_metric.get(Metric.ABSENT, ()):
            outcome[day] = ABSENT

        for day in row.days_by_metric.get(Metric.PRESENT, ()):
            outcome[day] = PRESENT

        for day in row.days_by_metric.get(Metric.BUSINESS_TRIP, ()):
            outcome[day] = BUSINESS_TRIP

        # Hari kerja di luar jadwal. `setdefault`, bukan penetapan: hari
        # yang sudah punya klasifikasi terjadwal tidak boleh ditimpa.
        for metric in (Metric.OFF_WORKED, Metric.HOLIDAY_WORKED):
            for day in row.days_by_metric.get(metric, ()):
                outcome.setdefault(day, EXTRA)

        # Terlambat adalah **lapisan di atas hadir**, bukan penggantinya
        # — persis seperti di laporannya, di mana satu hari terlambat
        # ikut terhitung Present. Karena itu ia ditimpakan terakhir, dan
        # hanya pada hari yang memang tercatat bekerja.
        for day in row.days_by_metric.get(Metric.LATE, ()):
            if outcome.get(day) in (PRESENT, EXTRA):
                outcome[day] = LATE

        days = []
        current = span.start

        while current <= span.end:
            days.append(
                {
                    "date": current.isoformat(),
                    "outcome": outcome.get(current, OFF),
                },
            )

            current += timedelta(days=1)

        return days

    # ------------------------------------------------------------------
    # Riwayat
    # ------------------------------------------------------------------

    @staticmethod
    def _overtime_by_day(row) -> dict[date, int]:
        """
        Menit lembur per tanggal, dari dokumen lembur yang sudah ditarik
        `HRPeriodSummaryService` untuk rentang ini.

        Nol query tambahan, dan — yang lebih penting — **sumber yang
        sama dengan kartu Lembur di atasnya**. `EmployeeAttendance.
        overtime_minutes` sengaja tidak dipakai: ia menit kerja melewati
        jadwal menurut mesin, bukan lembur yang tercatat, dan payroll
        pun tidak membacanya. Menampilkannya di kolom bernama "Lembur"
        akan membuat pegawai menghitung upah yang tidak pernah diajukan.
        """
        result: dict[date, int] = {}

        for detail in row.overtime_details:
            result[detail.day] = result.get(detail.day, 0) + detail.minutes

        return result

    @classmethod
    def _history(
        cls,
        *,
        employee,
        span: DateRange,
        page,
        page_size: int,
        overtime_by_day: dict[date, int],
    ) -> tuple[list[dict], dict]:
        """
        Satu halaman baris presensi — disaring, diurutkan, dan dipotong
        **di database**.

        `Paginator` menerjemahkan nomor halaman jadi `LIMIT`/`OFFSET`;
        yang pernah masuk Python cuma baris halaman ini. Menarik seluruh
        rentang lalu memotongnya di sini akan terlihat benar di layar
        dan salah di setiap hal lain.
        """
        queryset = (
            EmployeeAttendance.objects
            .filter(
                employee=employee,
                is_deleted=False,
                work_date__gte=span.start,
                work_date__lte=span.end,
            )
            .select_related("shift")
            .only(
                "id",
                "work_date",
                "status",
                "source",
                "check_in",
                "check_out",
                "worked_minutes",
                "late_minutes",
                "early_leave_minutes",
                "permission_state",
                "shift__name",
            )
            # `id` sebagai pemecah seri: dua baris bertanggal sama tidak
            # seharusnya ada (ada unique constraint-nya), tapi urutan
            # tanpa pemecah seri membuat paginasi boleh mengembalikan
            # baris yang sama di dua halaman kalau constraint itu pernah
            # dilonggarkan.
            .order_by("-work_date", "-id")
        )

        paginator = Paginator(queryset, page_size)

        number = page or 1

        try:
            number = int(number)
        except (TypeError, ValueError):
            raise ValidationError({"page": "Harus berupa angka."})

        # Halaman di luar jangkauan jatuh ke halaman terakhir alih-alih
        # 404: rentangnya baru saja diperkecil pengguna, dan halaman 4
        # yang tadi sah tidak boleh berubah jadi galat.
        number = max(1, min(number, paginator.num_pages))

        current = paginator.page(number)

        rows = [
            cls._row(record, overtime_by_day)
            for record in current.object_list
        ]

        return rows, {
            "count": paginator.count,
            "total_pages": paginator.num_pages,
            "page": current.number,
            "page_size": page_size,
        }

    @staticmethod
    def _row(record, overtime_by_day: dict[date, int]) -> dict:
        """
        Daftar putih eksplisit, dan pendek.

        Yang **tidak** ikut, semuanya disengaja: `approval_status` dan
        `review_*` (keputusan HR atas barisnya, bukan informasi
        pegawainya), `leave_required_*` termasuk pembebasan dan alasan
        tertulisnya, koordinat check-in/check-out, `first_check_in`/
        `last_check_out` mentah, snapshot organisasi, serta seluruh
        metadata audit. Tabel ini bukan versi kecil tabel HR Attendance
        — ia daftar hari kerja seseorang.
        """
        return {
            "id": record.id,
            "work_date": record.work_date.isoformat(),
            "shift": record.shift.name if record.shift_id else None,
            "status": record.status,
            "status_label": record.get_status_display(),
            "source": record.source,
            "source_label": record.get_source_display(),
            "check_in": _wall_clock(record.check_in),
            "check_out": _wall_clock(record.check_out),
            "worked_minutes": record.worked_minutes,
            "late_minutes": record.late_minutes,
            "early_leave_minutes": record.early_leave_minutes,
            "overtime_minutes": overtime_by_day.get(record.work_date, 0),
            # Kosong = tidak ada pengecualian yang perlu dijelaskan.
            # Diikutkan karena inilah satu-satunya yang membedakan
            # "terlambat 59 menit" dari "terlambat 59 menit dan sudah
            # ada izinnya" — tanpanya barisnya terbaca sebagai tuduhan.
            "permission_state": record.permission_state or None,
        }
