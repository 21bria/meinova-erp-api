"""
HR Period Summary — laporan manajemen, READ ONLY.

Aturannya **tidak lahir di sini**. Yang dikerjakan berkas ini cuma tiga
hal: membaca sumber HR yang sudah authoritative, menjumlahkannya, lalu
menyajikannya. Setiap kali muncul godaan menulis "kalau tanggalnya
Sabtu maka…", jawabannya ada di modul sumbernya:

* hari terjadwal → `apps.hr.api.attendance.schedule.scheduled_work_days`
  (roster untuk pegawai site, WorkCalendar untuk pegawai kantor)
* hari libur → `LeaveDayCalculator.resolve_holidays`
* cuti yang dihitung → `LEAVE_DEDUCTING_STATUSES`
* hari terjadwal tanpa catatan → aturan `AttendanceClosingService`:
  tertutup dokumen cuti = cuti, selain itu mangkir
* field break → segmen `RosterSegmentType.FIELD_BREAK`
* lembur → `EmployeeOvertime` berstatus RECORDED

**Satu hasil untuk empat penyaji.** KPI, chart, tabel pegawai, dan
drill-down semuanya membaca `PeriodSummary` yang sama, dihitung sekali
per request dan disimpan di context. Kalau masing-masing merakit
querysetnya sendiri, kartu "Absent 3" bisa berdiri di atas tabel yang
barisnya berjumlah 4 tanpa satu pun pesan yang menjelaskan bedanya —
dan yang membacanya akan menyimpulkan salah satunya salah.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, time, timedelta
from decimal import Decimal

from django.db.models import Q

from apps.accounts.permissions import view_permission_for
from apps.accounts.scoping import DataScopeService
from apps.framework.periods import trend_buckets
from apps.hr.api.attendance.schedule import (
    holidays_bulk,
    scheduled_work_days_bulk,
)
from apps.hr.models import (
    LEAVE_DEDUCTING_STATUSES,
    Employee,
    EmployeeAttendance,
    EmployeeLeave,
    EmployeeOvertime,
    OvertimeStatus,
    RosterSegmentType,
    RotationPeriod,
    RotationPeriodStatus,
)
from apps.hr.models.attendance.choices import AttendanceStatus

from apps.hr.applicability import (
    HRFeature,
    applicable_features,
    exclude_none_applicable,
    is_applicable,
)

from .metrics import (
    DayType,
    LEAVE_METRICS,
    Metric,
    REPORT_FEATURES,
    day_type,
    leave_group,
    metric_feature,
)


# Status yang dihitung "masuk kerja". Disamakan persis dengan
# `HRDashboardService.PRESENT_STATUSES` — dua daftar yang harus tetap
# sama adalah cara selisih antara dashboard dan laporan lahir diam-diam.
PRESENT_STATUSES = frozenset(
    {
        AttendanceStatus.PRESENT,
        AttendanceStatus.LATE,
        AttendanceStatus.REMOTE,
        AttendanceStatus.BUSINESS_TRIP,
    }
)


# Baris presensi yang **membatalkan** hari terjadwal. Hari yang barisnya
# berbunyi libur atau off bukan peluang hadir, jadi ia keluar dari
# Scheduled alih-alih menjadi Absent — aturan yang sama dengan
# `NON_WORKING_STATUSES` di dashboard HR. Tanpa ini, satu koreksi tangan
# ("ternyata hari itu libur perusahaan") terbaca sebagai orangnya
# mangkir.
NON_WORKING_STATUSES = frozenset(
    {
        AttendanceStatus.HOLIDAY,
        AttendanceStatus.DAY_OFF,
    }
)


UNASSIGNED_LABEL = "Belum Ditentukan"

MAX_CHART_SEGMENTS = 5
OTHER_LABEL = "Lainnya"


# Cakupan data per baris. Disalin dari `EmployeeViewSet.data_scope`
# (`apps/hr/api/employee/views/employee.py`) — kalau yang di sana
# berubah, yang di sini harus ikut.
#
# **Hanya pegawai yang disaring**, dan itu disengaja: seluruh transaksi
# di laporan ini diambil dengan `employee__in=<pegawai yang lolos>`.
# Menyaring transaksi lewat snapshot organisasinya sendiri akan membuat
# tabel pegawai dan kartu KPI menghitung populasi yang berbeda begitu
# ada pegawai yang pindah lokasi di tengah periode.
EMPLOYEE_SCOPE = {
    "company": "organization__company",
    "branch": "organization__branch",
    "location": "organization__location",
    "division": "organization__division",
    "department": "organization__department",
    "section": "organization__section",
    "own": "user_id",
}


# Filter dropdown → jalur ORM dari `Employee`.
FILTER_PATHS = {
    "company": "organization__company_id",
    "branch": "organization__branch_id",
    "location": "organization__location_id",
    "department": "organization__department_id",
    "section": "organization__section_id",
    "employee_group": "employment__employee_group_id",
    "employment_type": "employment__employment_type_id",
    "employee": "id",
}


CONTEXT_KEY = "_hr_period_summary"


# ======================================================================
# Bentuk hasil
# ======================================================================


@dataclass
class LeaveDetail:
    """Satu hari cuti, dengan tipe aslinya tetap terbawa."""

    day: date
    days: Decimal
    leave_id: int | None
    leave_type_code: str
    leave_type_name: str
    document_number: str
    status: str

    # Rentang dokumen cutinya, untuk drill-down. Satu dokumen tiga hari
    # menghasilkan tiga `LeaveDetail`; tanpa rentangnya, yang membaca
    # rincian tidak bisa tahu ketiganya satu pengajuan.
    leave_start: date | None = None
    leave_end: date | None = None


@dataclass
class OvertimeDetail:
    day: date
    minutes: int
    overtime_type: str
    reason: str
    overtime_id: int | None

    # Jam yang tertulis di dokumen lembur, apa adanya. **Bukan** sumber
    # durasinya — `minutes` tetap `duration_minutes` yang disimpan.
    start_time: time | None = None
    end_time: time | None = None


@dataclass
class EmployeeSummary:
    employee_id: int
    employee_number: str
    employee_name: str
    location: str
    department: str
    section: str

    scheduled: int = 0
    present: int = 0
    absent: int = 0

    field_break: int = 0
    off_worked: int = 0
    holiday_worked: int = 0

    late: int = 0
    early: int = 0

    ot_regular_minutes: int = 0
    ot_off_minutes: int = 0
    ot_holiday_minutes: int = 0

    leave_days: dict[str, Decimal] = field(default_factory=dict)

    # Proses HR yang berlaku untuk pegawai ini (Feature Applicability).
    # Disimpan di barisnya, bukan dihitung ulang tiap kali dibutuhkan:
    # KPI, chart, tabel, dan drill-down semuanya membaca baris yang sama,
    # dan resolver yang dipanggil di empat tempat cepat atau lambat
    # dipanggil dengan pegawai yang berbeda.
    applicable: frozenset = field(default_factory=frozenset)

    # Tanggal per metrik — bahan drill-down, bukan hiasan. Yang
    # dijumlahkan dan yang ditelusuri harus berasal dari daftar yang
    # sama; kalau tidak, "Absent 3" bisa membuka rincian berisi 2 baris.
    days_by_metric: dict[str, list[date]] = field(default_factory=dict)

    leave_details: list[LeaveDetail] = field(default_factory=list)
    overtime_details: list[OvertimeDetail] = field(default_factory=list)

    # Baris presensi per tanggal, seperti yang dibaca klasifikasi di
    # bawah. Disimpan supaya drill-down Late/Early menampilkan menit
    # **yang sama** dengan yang membuat hari itu terhitung — bukan
    # query kedua yang bisa membaca baris yang sudah berubah.
    attendance_records: dict[date, dict] = field(default_factory=dict)

    def applies_to(self, feature) -> bool:
        return feature in self.applicable

    def counts(self, metric: str) -> bool:
        """
        Metrik ini boleh dihitung untuk pegawai ini?

        Metrik yang tidak terpetakan ke proses mana pun selalu boleh —
        `None` berarti "tidak bergantung applicability", bukan "tidak
        berlaku untuk siapa pun".
        """
        feature = metric_feature(metric)

        return feature is None or feature in self.applicable

    def leave(self, metric: str) -> Decimal:
        return self.leave_days.get(metric, Decimal("0"))

    @property
    def leave_total(self) -> Decimal:
        return sum(
            (self.leave_days.get(metric, Decimal("0")) for metric in LEAVE_METRICS),
            Decimal("0"),
        )

    @property
    def ot_total_minutes(self) -> int:
        return (
            self.ot_regular_minutes
            + self.ot_off_minutes
            + self.ot_holiday_minutes
        )

    def metric(self, name: str):
        """Nilai satu metrik — jalan masuk tunggal untuk KPI dan tabel."""
        if name in LEAVE_METRICS:
            return self.leave(name)

        return {
            Metric.SCHEDULED: self.scheduled,
            Metric.PRESENT: self.present,
            Metric.ABSENT: self.absent,
            Metric.FIELD_BREAK: self.field_break,
            Metric.OFF_WORKED: self.off_worked,
            Metric.HOLIDAY_WORKED: self.holiday_worked,
            Metric.LATE: self.late,
            Metric.EARLY: self.early,
            Metric.OT_REGULAR: _hours(self.ot_regular_minutes),
            Metric.OT_OFF: _hours(self.ot_off_minutes),
            Metric.OT_HOLIDAY: _hours(self.ot_holiday_minutes),
            Metric.OT_TOTAL: _hours(self.ot_total_minutes),
        }.get(name, 0)


@dataclass
class PeriodSummary:
    start: date
    end: date
    rows: list[EmployeeSummary]

    # Cacahan per hari untuk chart tren, sudah lewat klasifikasi yang
    # sama dengan tabelnya.
    daily_present: dict[date, int] = field(default_factory=dict)
    daily_late: dict[date, int] = field(default_factory=dict)
    daily_absent: dict[date, int] = field(default_factory=dict)

    daily_ot_regular: dict[date, int] = field(default_factory=dict)
    daily_ot_off: dict[date, int] = field(default_factory=dict)
    daily_ot_holiday: dict[date, int] = field(default_factory=dict)

    # Cuti per **tipe asli**, untuk chart Leave Breakdown yang tetap
    # bisa menyebut "Cuti Menikah" alih-alih menelannya jadi Other.
    leave_by_type: dict[str, Decimal] = field(default_factory=dict)

    def total(self, metric: str):
        """
        Jumlah satu metrik atas populasi metrik itu.

        Baris yang prosesnya tidak berlaku **dilewati**, bukan
        dijumlahkan sebagai nol. Untuk penjumlahan hasilnya memang sama;
        yang tidak sama adalah artinya, dan itu terbaca begitu ada rasio
        yang memakai cacah barisnya sebagai penyebut. Yang dipakai di
        situ `feature_headcount()`, dan dua-duanya harus menyaring dengan
        aturan yang sama supaya pembilang dan penyebutnya tidak pernah
        berasal dari populasi yang berbeda.
        """
        values = [
            row.metric(metric)
            for row in self.rows
            if row.counts(metric)
        ]

        if not values:
            return Decimal("0") if metric in LEAVE_METRICS else 0

        return sum(values)

    @property
    def headcount(self) -> int:
        return len(self.rows)

    def feature_rows(self, feature) -> list["EmployeeSummary"]:
        """Baris yang proses ini memang berlaku baginya."""
        return [row for row in self.rows if row.applies_to(feature)]

    def feature_headcount(self, feature) -> int:
        """
        Populasi **satu proses** — penyebut yang benar untuk rasio yang
        dibagi jumlah orang.

        `headcount` menjawab "berapa pegawai di laporan ini";
        `feature_headcount` menjawab "berapa yang diproses fitur ini".
        Keduanya sama selama seluruh group applicable, dan mulai berbeda
        begitu ada yang dimatikan — memakai yang pertama sebagai penyebut
        rasio kehadiran akan mengencerkan angkanya dengan orang yang
        memang tidak pernah diabsen.
        """
        return len(self.feature_rows(feature))


def _hours(minutes: int) -> float:
    return round((minutes or 0) / 60, 1)


def _days_between(start: date, end: date):
    current = start

    while current <= end:
        yield current
        current += timedelta(days=1)


# ======================================================================
# Service
# ======================================================================


class HRPeriodSummaryService:
    """
    Satu-satunya perakit angka laporan ini.

    Tidak ada method yang menulis. Tidak ada method yang memutuskan
    aturan HR baru — yang ada cuma pembacaan sumbernya, penggabungan,
    dan penyajian.
    """

    # ------------------------------------------------------------------
    # Periode & populasi
    # ------------------------------------------------------------------

    @staticmethod
    def bounds(context: dict) -> tuple[date, date]:
        period = context["period"]

        return period["start"], period["end"]

    @staticmethod
    def previous_bounds(context: dict) -> tuple[date, date]:
        previous = context["period"]["previous"]

        return previous["start"], previous["end"]

    @classmethod
    def employee_queryset(cls, context: dict, start: date, end: date):
        """
        Pegawai yang **berstatus kerja pada periode ini**, sesudah filter
        dropdown, cakupan data, dan Feature Applicability.

        Bukan "pegawai aktif hari ini": laporan bulan lalu harus tetap
        memuat orang yang keluar minggu ini, kalau tidak angka bulan lalu
        berubah tiap kali ada yang resign. Pegawai tanpa
        `EmploymentAssignment` ikut dihitung, sejalan dengan
        `HRDashboardService.headcount_at` — banyak klien mengisi data
        pribadi lebih dulu.

        Yang **tidak** ikut: pegawai yang keempat proses laporan ini
        (`REPORT_FEATURES`) dimatikan admin di master Employee Group.
        Mereka tidak punya satu pun angka untuk disumbangkan, dan baris
        nol di tengah tabel terbaca sebagai "orang ini tidak masuk
        sebulan penuh". Mereka tetap Employee di layar lain — yang
        hilang cuma kepesertaannya di proses yang dilaporkan di sini.
        """
        queryset = (
            Employee.objects
            .filter(is_deleted=False)
            .select_related(
                "organization__company",
                "organization__branch",
                "organization__location",
                "organization__department",
                "organization__section",
                "employment__working_calendar",
                "employment__employee_group",
                "employment__employment_type",
                "employment__roster_crew",
                "employment__roster_policy",
            )
            .filter(
                Q(employment__isnull=True)
                | Q(employment__join_date__isnull=True)
                | Q(employment__join_date__lte=end),
            )
            .filter(
                Q(employment__termination_date__isnull=True)
                | Q(employment__termination_date__gte=start),
            )
        )

        for key, path in FILTER_PATHS.items():
            value = context.get(key)

            if not value:
                continue

            if isinstance(value, (list, tuple, set)):
                queryset = queryset.filter(**{f"{path}__in": list(value)})
            else:
                queryset = queryset.filter(**{path: value})

        queryset = DataScopeService.filter(
            queryset,
            EMPLOYEE_SCOPE,
            context.get("user"),
            required_permission=view_permission_for(Employee),
        )

        # **Sesudah cakupan data, tidak pernah sebelumnya.** Dua
        # pertanyaan yang berbeda, dan urutannya yang menjaga keduanya
        # tetap terpisah:
        #
        # * cakupan data → "baris siapa yang boleh dilihat pengguna ini"
        # * applicability → "dari situ, siapa yang diproses laporan ini"
        #
        # Applicability karena itu hanya bisa **mempersempit**. Ditaruh
        # lebih dulu, ia akan terbaca seperti bisa memunculkan pegawai di
        # luar cakupan — dan kekeliruan seperti itu tidak berbunyi sampai
        # ada yang membuka laporan orang lain.
        queryset = exclude_none_applicable(queryset, REPORT_FEATURES)

        return queryset.order_by(
            "organization__location__code",
            "employee_number",
            "id",
        ).distinct()

    # ------------------------------------------------------------------
    # Perakitan
    # ------------------------------------------------------------------

    @classmethod
    def summary(cls, context: dict) -> PeriodSummary:
        """
        Hasil yang dipakai bersama KPI, chart, tabel, dan drill-down.

        Disimpan di `context` supaya satu request menghitungnya sekali.
        Dua belas resolver yang masing-masing memanggil `build()` berarti
        dua belas kali seluruh agregasi dijalankan untuk jawaban yang
        sama persis.
        """
        cached = context.get(CONTEXT_KEY)

        if cached is not None:
            return cached

        start, end = cls.bounds(context)

        result = cls.build(context, start, end)

        context[CONTEXT_KEY] = result

        return result

    @classmethod
    def build(cls, context: dict, start: date, end: date) -> PeriodSummary:
        return cls.build_for(
            cls.employee_queryset(context, start, end),
            start,
            end,
        )

    @classmethod
    def build_for(cls, employees, start: date, end: date) -> PeriodSummary:
        """
        Agregasi atas **populasi yang sudah ditentukan pemanggil**.

        Dipisah dari `build()` supaya pemanggil yang populasinya sudah
        pasti tidak perlu melewati `employee_queryset()` — dan karena
        itu tidak perlu ikut membawa cakupan data laporan manajemen.
        Satu-satunya pemanggil semacam itu Self Service: subjeknya
        selalu **pegawai yang sedang login sendiri**, sudah dipastikan
        `CurrentEmployeeService`, jadi tidak ada baris orang lain yang
        bisa lolos lewat sini.

        **Aturannya tidak dipindah dan tidak disalin.** Seluruh isi
        method ini sebelumnya badan `build()`; yang berubah cuma dari
        mana daftar pegawainya datang. Itu yang membuat angka di
        `/me/attendance` dan angka di laporan HR untuk orang yang sama
        tidak bisa berbeda — keduanya menjalankan kode yang sama persis.

        Pemanggil yang memakai cakupan data tetap wajib lewat `build()`.
        Method ini **tidak** menyaring apa pun; ia mengerjakan persis
        populasi yang diberikan.
        """
        employees = list(employees)

        rows = [cls._blank_row(employee) for employee in employees]

        summary = PeriodSummary(start=start, end=end, rows=rows)

        if not employees:
            return summary

        by_id = {row.employee_id: row for row in rows}

        scheduled = scheduled_work_days_bulk(employees, start, end)
        holidays = holidays_bulk(employees, start, end)

        # Tiap sumber ditarik hanya untuk pegawai yang prosesnya memang
        # berlaku. Menyaringnya di sini, bukan saat menjumlahkan, membuat
        # angka nol pada baris pegawai yang tidak applicable **tidak
        # pernah lahir** — bukan lahir lalu dibuang. Bedanya terlihat di
        # drill-down: `days_by_metric` ikut kosong, jadi tidak ada rincian
        # yang bisa dibuka untuk angka yang tidak dihitung.
        attendance = cls._attendance(
            cls._subject(employees, HRFeature.ATTENDANCE), start, end,
        )
        leaves = cls._leaves(
            cls._subject(employees, HRFeature.LEAVE), start, end,
        )
        field_breaks = cls._field_breaks(
            cls._subject(employees, HRFeature.FIELD_BREAK), start, end,
        )

        for employee in employees:
            row = by_id[employee.id]

            cls._fill_attendance(
                row,
                scheduled_days=scheduled.get(employee.id, set()),
                holidays=holidays.get(employee.id, set()),
                attendance=attendance.get(employee.id, {}),
                leave_days=leaves.get(employee.id, {}),
                summary=summary,
            )

            row.field_break = len(field_breaks.get(employee.id, set()))
            row.days_by_metric[Metric.FIELD_BREAK] = sorted(
                field_breaks.get(employee.id, set()),
            )

        cls._fill_overtime(
            summary,
            by_id,
            cls._subject(employees, HRFeature.OVERTIME),
            scheduled,
            holidays,
            start,
            end,
        )

        return summary

    # ------------------------------------------------------------------
    # Pengambilan sumber
    # ------------------------------------------------------------------

    @staticmethod
    def _subject(employees, feature):
        """
        Pegawai yang jadi **subjek** satu proses.

        Satu-satunya tempat penyaringan per proses ditulis di laporan
        ini; empat pemanggilnya di `build()` lewat sini semua, jadi tidak
        ada dua tafsir "siapa yang dihitung Leave" yang harus dijaga
        tetap sama.
        """
        return [
            employee
            for employee in employees
            if is_applicable(employee, feature)
        ]

    @staticmethod
    def _blank_row(employee) -> EmployeeSummary:
        organization = getattr(employee, "organization", None)

        def name_of(relation):
            value = getattr(organization, relation, None)

            return getattr(value, "name", None) or UNASSIGNED_LABEL

        return EmployeeSummary(
            employee_id=employee.id,
            employee_number=employee.employee_number or "",
            employee_name=employee.full_name,
            location=name_of("location"),
            department=name_of("department"),
            section=name_of("section"),
            # Diambil sekali di sini. `employment__employee_group` sudah
            # ikut `select_related`, jadi tidak ada query tambahan.
            applicable=applicable_features(employee),
        )

    @staticmethod
    def _attendance(employees, start: date, end: date) -> dict[int, dict]:
        rows = (
            EmployeeAttendance.objects
            .filter(
                employee__in=employees,
                work_date__gte=start,
                work_date__lte=end,
                is_deleted=False,
            )
            .values(
                "id",
                "employee_id",
                "work_date",
                "status",
                "late_minutes",
                "early_leave_minutes",
                # Bahan drill-down saja; klasifikasi tidak membacanya.
                "scheduled_check_in",
                "scheduled_check_out",
                "check_in",
                "check_out",
                "worked_minutes",
                "excused_late_minutes",
                "excused_early_leave_minutes",
            )
        )

        result: dict[int, dict] = defaultdict(dict)

        for row in rows:
            result[row["employee_id"]][row["work_date"]] = row

        return result

    @staticmethod
    def _leaves(employees, start: date, end: date) -> dict[int, dict]:
        """
        Tanggal yang tertutup dokumen cuti, per pegawai.

        Status yang dihitung mengikuti `LEAVE_DEDUCTING_STATUSES` —
        daftar yang sama dengan yang memotong `LeaveBalance.used`, jadi
        angka di laporan tidak bisa berbeda dari angka yang memotong
        saldo orangnya.

        Cuti setengah hari tetap 0,5 (`LeaveDayCalculator.calculate`);
        selain itu tiap tanggal bernilai satu, dan yang menentukan
        tanggal mana yang benar-benar dihitung adalah hari terjadwalnya
        — sama seperti `count_working_days` yang tidak memotong saldo di
        hari libur.
        """
        rows = (
            EmployeeLeave.objects
            .filter(
                employee__in=employees,
                start_date__lte=end,
                end_date__gte=start,
                status__in=LEAVE_DEDUCTING_STATUSES,
                is_deleted=False,
            )
            .select_related("leave_type")
            .values(
                "id",
                "employee_id",
                "start_date",
                "end_date",
                "is_half_day",
                "status",
                "document_number",
                "leave_type__code",
                "leave_type__name",
            )
        )

        result: dict[int, dict] = defaultdict(dict)

        for row in rows:
            for day in _days_between(
                max(row["start_date"], start),
                min(row["end_date"], end),
            ):
                result[row["employee_id"]][day] = row

        return result

    @staticmethod
    def _field_breaks(employees, start: date, end: date) -> dict[int, set]:
        """
        Blok istirahat lapangan — segmen roster tersendiri.

        **Bukan cuti**, dan sengaja tidak digabung ke Annual/Sick/Other:
        `RotationPurpose` memisahkannya justru karena field break tidak
        memotong saldo apa pun.
        """
        rows = (
            RotationPeriod.objects
            .filter(
                employee__in=employees,
                is_deleted=False,
                version_to__isnull=True,
                segment_type=RosterSegmentType.FIELD_BREAK,
                start_date__lte=end,
                end_date__gte=start,
            )
            .exclude(status=RotationPeriodStatus.CANCELLED)
            .values_list("employee_id", "start_date", "end_date")
        )

        result: dict[int, set] = defaultdict(set)

        for employee_id, period_start, period_end in rows:
            result[employee_id].update(
                _days_between(
                    max(period_start, start),
                    min(period_end, end),
                ),
            )

        return result

    # ------------------------------------------------------------------
    # Klasifikasi
    # ------------------------------------------------------------------

    @classmethod
    def _fill_attendance(
        cls,
        row: EmployeeSummary,
        *,
        scheduled_days: set,
        holidays: set,
        attendance: dict,
        leave_days: dict,
        summary: PeriodSummary,
    ) -> None:
        """
        Satu lintasan per tanggal, dan urutan pemeriksaannya adalah
        aturannya:

        **Hari terjadwal**
        1. barisnya berbunyi libur/off → hari itu keluar dari Scheduled
        2. hadir (present/late/remote/business trip) → Present
        3. tertutup dokumen cuti → Leave, dikelompokkan dari tipe aslinya
        4. sisanya → Absent

        Butir 3 dan 4 adalah aturan `AttendanceClosingService` yang sudah
        berlaku saat menutup hari, cuma dibaca alih-alih ditulis. Yang
        penting: hari terjadwal **tanpa baris presensi sama sekali**
        tetap terhitung — di sistem ini ketidakhadiran memang berupa
        baris yang tidak ada, dan laporan yang cuma menjumlahkan baris
        yang ada tidak akan pernah bisa menampilkan angka mangkir.

        **Hari tidak terjadwal** — hanya dihitung kalau orangnya benar-
        benar bekerja: libur → Holiday Worked, selain itu → Off Worked.
        Keduanya **bukan tambahan** Present; itu sebabnya keduanya punya
        kolomnya sendiri.
        """
        row.attendance_records.update(attendance)

        days = set(scheduled_days) | set(attendance.keys()) | set(leave_days.keys())

        buckets: dict[str, list[date]] = defaultdict(list)

        for day in sorted(days):
            record = attendance.get(day)
            status = record["status"] if record else None

            kind = day_type(day, scheduled_days, holidays)

            if kind == DayType.SCHEDULED:
                if status in NON_WORKING_STATUSES:
                    continue

                row.scheduled += 1
                buckets[Metric.SCHEDULED].append(day)

                if status in PRESENT_STATUSES:
                    row.present += 1
                    buckets[Metric.PRESENT].append(day)

                    cls._count_day(summary.daily_present, day)

                    if cls._is_late(record):
                        row.late += 1
                        buckets[Metric.LATE].append(day)

                        cls._count_day(summary.daily_late, day)

                    if cls._is_early(record):
                        row.early += 1
                        buckets[Metric.EARLY].append(day)

                    continue

                leave = leave_days.get(day)

                if leave is not None:
                    cls._add_leave(row, summary, day, leave, buckets)

                    continue

                row.absent += 1
                buckets[Metric.ABSENT].append(day)

                cls._count_day(summary.daily_absent, day)

                continue

            # Hari di luar jadwal. Yang tidak ada tapnya tidak
            # menghasilkan apa pun — orang yang sedang off memang tidak
            # menekan mesin, dan itu bukan informasi.
            if status not in PRESENT_STATUSES:
                continue

            metric = (
                Metric.HOLIDAY_WORKED
                if kind == DayType.HOLIDAY
                else Metric.OFF_WORKED
            )

            if metric == Metric.HOLIDAY_WORKED:
                row.holiday_worked += 1
            else:
                row.off_worked += 1

            buckets[metric].append(day)

            if cls._is_late(record):
                row.late += 1
                buckets[Metric.LATE].append(day)

            if cls._is_early(record):
                row.early += 1
                buckets[Metric.EARLY].append(day)

        for metric, values in buckets.items():
            row.days_by_metric.setdefault(metric, []).extend(values)
            row.days_by_metric[metric] = sorted(set(row.days_by_metric[metric]))

    @staticmethod
    def _is_late(record) -> bool:
        """
        `late_minutes` **atau** status — bukan salah satunya.

        `AttendancePolicyResolver` selalu menulis keduanya bersamaan
        (menit sesudah toleransi, lalu status LATE kalau menitnya tidak
        nol), tapi baris hasil import dan koreksi tangan bisa membawa
        salah satu saja.
        """
        if record is None:
            return False

        return bool(
            (record.get("late_minutes") or 0) > 0
            or record.get("status") == AttendanceStatus.LATE,
        )

    @staticmethod
    def _is_early(record) -> bool:
        if record is None:
            return False

        return (record.get("early_leave_minutes") or 0) > 0

    @staticmethod
    def _count_day(bucket: dict, day: date) -> None:
        bucket[day] = bucket.get(day, 0) + 1

    @staticmethod
    def _add_leave(
        row: EmployeeSummary,
        summary: PeriodSummary,
        day: date,
        leave: dict,
        buckets: dict,
    ) -> None:
        code = leave.get("leave_type__code") or ""
        name = leave.get("leave_type__name") or UNASSIGNED_LABEL

        metric = leave_group(code)

        days = Decimal("0.5") if leave.get("is_half_day") else Decimal("1")

        row.leave_days[metric] = row.leave_days.get(metric, Decimal("0")) + days

        buckets[metric].append(day)

        summary.leave_by_type[name] = (
            summary.leave_by_type.get(name, Decimal("0")) + days
        )

        row.leave_details.append(
            LeaveDetail(
                day=day,
                days=days,
                leave_id=leave.get("id"),
                leave_type_code=code,
                leave_type_name=name,
                document_number=leave.get("document_number") or "",
                status=leave.get("status") or "",
                leave_start=leave.get("start_date"),
                leave_end=leave.get("end_date"),
            ),
        )

    # ------------------------------------------------------------------
    # Lembur
    # ------------------------------------------------------------------

    @classmethod
    def _fill_overtime(
        cls,
        summary: PeriodSummary,
        by_id: dict,
        employees,
        scheduled: dict,
        holidays: dict,
        start: date,
        end: date,
    ) -> None:
        """
        Kategori lembur ditentukan **jenis harinya**, bukan tanggalnya.

        Resolver yang dipakai sama persis dengan yang memisahkan Present
        / Off Worked / Holiday Worked di atas: hari terjadwal → Regular
        OT, hari libur → Holiday OT, sisanya → Off OT. Satu resolver
        untuk keduanya bukan penghematan baris, tapi jaminan bahwa Off
        Worked dan Off OT tidak pernah menghitung tanggal yang berbeda.

        `OvertimeType` master (WEEKDAY/WEEKEND/HOLIDAY/CALL_OUT) sengaja
        **tidak** dipakai sebagai penentu: isinya `BaseReference` bebas
        yang boleh ditambah dan diganti nama tiap tenant, dan nilainya
        dipilih tangan saat menginput. Ia tetap dibawa ke drill-down.

        Status RECORDED saja, mengikuti `HRDashboardService`. Lembur
        belum punya alur approval di sistem ini, jadi tidak ada baris
        APPROVED yang bisa hilang karenanya.
        """
        rows = (
            EmployeeOvertime.objects
            .filter(
                employee__in=employees,
                work_date__gte=start,
                work_date__lte=end,
                status=OvertimeStatus.RECORDED,
                is_deleted=False,
            )
            .select_related("overtime_type")
            .values(
                "id",
                "employee_id",
                "work_date",
                "duration_minutes",
                "start_time",
                "end_time",
                "reason",
                "overtime_type__name",
            )
        )

        for record in rows:
            row = by_id.get(record["employee_id"])

            if row is None:
                continue

            day = record["work_date"]
            minutes = record["duration_minutes"] or 0

            kind = day_type(
                day,
                scheduled.get(record["employee_id"], set()),
                holidays.get(record["employee_id"], set()),
            )

            if kind == DayType.SCHEDULED:
                row.ot_regular_minutes += minutes
                metric = Metric.OT_REGULAR
                bucket = summary.daily_ot_regular
            elif kind == DayType.HOLIDAY:
                row.ot_holiday_minutes += minutes
                metric = Metric.OT_HOLIDAY
                bucket = summary.daily_ot_holiday
            else:
                row.ot_off_minutes += minutes
                metric = Metric.OT_OFF
                bucket = summary.daily_ot_off

            bucket[day] = bucket.get(day, 0) + minutes

            row.days_by_metric.setdefault(metric, [])

            if day not in row.days_by_metric[metric]:
                row.days_by_metric[metric].append(day)

            row.days_by_metric.setdefault(Metric.OT_TOTAL, [])

            if day not in row.days_by_metric[Metric.OT_TOTAL]:
                row.days_by_metric[Metric.OT_TOTAL].append(day)

            row.overtime_details.append(
                OvertimeDetail(
                    day=day,
                    minutes=minutes,
                    overtime_type=record["overtime_type__name"] or "",
                    reason=record["reason"] or "",
                    overtime_id=record["id"],
                    start_time=record["start_time"],
                    end_time=record["end_time"],
                ),
            )

        for row in summary.rows:
            for metric in (
                Metric.OT_REGULAR,
                Metric.OT_OFF,
                Metric.OT_HOLIDAY,
                Metric.OT_TOTAL,
            ):
                if metric in row.days_by_metric:
                    row.days_by_metric[metric].sort()


# ======================================================================
# Penyaji: KPI
# ======================================================================


def trend(current, previous, *, period: str = "dari periode sebelumnya"):
    """
    Sama persis dengan `HRDashboardService.trend` — pembanding nol tidak
    menghasilkan persentase, dan frontend menyembunyikan bagian trennya
    saat nilainya None.
    """
    if previous in (None, 0) or current is None:
        return None

    current = float(current)
    previous = float(previous)

    change = ((current - previous) / abs(previous)) * 100

    return {
        "value": round(abs(change), 2),
        "direction": "up" if change >= 0 else "down",
        "period": period,
    }


class HRPeriodSummaryPresenter:
    """
    Mengubah satu `PeriodSummary` menjadi bentuk yang dimengerti runtime
    dashboard. Tidak ada agregasi baru di sini — semuanya penjumlahan
    ulang dari baris yang sudah jadi.
    """

    service = HRPeriodSummaryService

    # ------------------------------------------------------------------

    @classmethod
    def _previous(cls, context: dict) -> PeriodSummary:
        cached = context.get(f"{CONTEXT_KEY}_previous")

        if cached is not None:
            return cached

        start, end = cls.service.previous_bounds(context)

        result = cls.service.build(context, start, end)

        context[f"{CONTEXT_KEY}_previous"] = result

        return result

    @staticmethod
    def _compare_label(context: dict) -> str:
        return context["period"].get(
            "compare_label",
            "dari periode sebelumnya",
        )

    @classmethod
    def stat(cls, context: dict, resolve, *, precision: int | None = None):
        current = resolve(cls.service.summary(context))
        previous = resolve(cls._previous(context))

        if precision is not None and current is not None:
            current = round(float(current), precision)

        return {
            "value": current,
            "trend": trend(
                current,
                previous,
                period=cls._compare_label(context),
            ),
        }

    # ------------------------------------------------------------------
    # KPI
    # ------------------------------------------------------------------

    @classmethod
    def headcount(cls, context: dict) -> dict:
        return cls.stat(context, lambda summary: summary.headcount)

    @staticmethod
    def _attendance_rate(summary: PeriodSummary) -> float | None:
        """
        Present ÷ (Present + Absent).

        Penyebutnya **bukan** Scheduled: hari terjadwal yang tertutup
        cuti bukan peluang hadir, dan memasukkannya membuat orang yang
        mengambil haknya menurunkan angka unitnya. Aturan yang sama
        dengan `HRDashboardService.attendance_rate`, cuma dihitung dari
        baris yang sudah diklasifikasi alih-alih dari status mentah.
        """
        present = summary.total(Metric.PRESENT)
        absent = summary.total(Metric.ABSENT)

        total = present + absent

        if not total:
            return None

        return round(present / total * 100, 2)

    @classmethod
    def attendance_rate(cls, context: dict) -> dict:
        return cls.stat(context, cls._attendance_rate)

    @classmethod
    def metric_stat(cls, context: dict, metric: str, **kwargs) -> dict:
        return cls.stat(
            context,
            lambda summary: float(summary.total(metric)),
            **kwargs,
        )

    @classmethod
    def leave_total(cls, context: dict) -> dict:
        """
        Keempat kelompok cuti dijumlahkan. **Field Break tidak ikut** —
        ia blok roster, bukan cuti, dan menjumlahkannya ke sini membuat
        kartu ini membaca jauh lebih besar daripada jumlah hari yang
        benar-benar memotong saldo orang.
        """
        # Lewat `total()` per kelompok, bukan `sum(row.leave_total)`:
        # yang kedua membaca `leave_days` mentah dan karena itu melewati
        # penyaring applicability. Selama Leave menyala untuk semua orang
        # hasilnya sama, dan mulai berbeda diam-diam begitu ada group
        # yang dimatikan — kartu KPI akan menyebut angka yang tidak ada
        # di kolom mana pun pada tabelnya.
        return cls.stat(
            context,
            lambda summary: float(
                sum(
                    Decimal(str(summary.total(metric)))
                    for metric in LEAVE_METRICS
                ),
            ),
            precision=1,
        )

    # ------------------------------------------------------------------
    # Chart
    # ------------------------------------------------------------------

    @staticmethod
    def _buckets(context: dict):
        period = context["period"]
        today = date.today()

        return [
            bucket
            for bucket in trend_buckets(period)
            # Bucket yang belum terjadi tidak dikirim sebagai nol —
            # batang kosong di ujung terbaca sebagai kehadiran anjlok.
            if bucket["start"] <= today
        ]

    @classmethod
    def attendance_trend(cls, context: dict) -> dict:
        summary = cls.service.summary(context)

        buckets = cls._buckets(context)

        if not buckets:
            return {"categories": [], "datasets": []}

        categories, present, late, absent = [], [], [], []

        for bucket in buckets:
            counts = [0, 0, 0]

            for day in _days_between(bucket["start"], bucket["end"]):
                day_present = summary.daily_present.get(day, 0)
                day_late = summary.daily_late.get(day, 0)

                # "Hadir" tidak mencakup yang telat — dua tumpukan yang
                # saling memuat membuat tinggi batangnya dua kali jumlah
                # orang yang benar-benar masuk.
                counts[0] += day_present - day_late
                counts[1] += day_late
                counts[2] += summary.daily_absent.get(day, 0)

            categories.append(bucket["label"])

            present.append(counts[0])
            late.append(counts[1])
            absent.append(counts[2])

        return {
            "categories": categories,
            "datasets": [
                {"label": "Hadir", "data": present, "color": "success"},
                {"label": "Telat", "data": late, "color": "warning"},
                {"label": "Tidak Hadir", "data": absent, "color": "danger"},
            ],
        }

    @classmethod
    def leave_breakdown(cls, context: dict) -> dict:
        """
        Donut per **kelompok laporan**, bukan per tipe cuti mentah.

        Field Break ikut sebagai irisan tersendiri — ia memang bukan
        cuti, tapi ia adalah hari tidak-di-lokasi yang paling besar di
        pegawai site, dan membuangnya dari chart membuat pembacanya
        menyimpulkan orangnya bekerja penuh sebulan.
        """
        summary = cls.service.summary(context)

        rows = [
            (Metric.ANNUAL, "Annual"),
            (Metric.SICK, "Sick"),
            (Metric.OTHER_LEAVE, "Other Leave"),
            (Metric.UNPAID, "Unpaid"),
            (Metric.FIELD_BREAK, "Field Break"),
        ]

        series = []

        for metric, label in rows:
            value = float(summary.total(metric))

            if not value:
                continue

            series.append({"label": label, "value": value})

        total = sum(item["value"] for item in series)

        for item in series:
            item["percentage"] = (
                round(item["value"] / total * 100, 1) if total else 0
            )

        return {"series": series, "total": total}

    @classmethod
    def overtime_trend(cls, context: dict) -> dict:
        summary = cls.service.summary(context)

        buckets = cls._buckets(context)

        if not buckets:
            return {"categories": [], "datasets": []}

        categories, regular, off, holiday = [], [], [], []

        for bucket in buckets:
            totals = [0, 0, 0]

            for day in _days_between(bucket["start"], bucket["end"]):
                totals[0] += summary.daily_ot_regular.get(day, 0)
                totals[1] += summary.daily_ot_off.get(day, 0)
                totals[2] += summary.daily_ot_holiday.get(day, 0)

            categories.append(bucket["label"])

            regular.append(_hours(totals[0]))
            off.append(_hours(totals[1]))
            holiday.append(_hours(totals[2]))

        return {
            "categories": categories,
            "datasets": [
                {"label": "Regular OT", "data": regular, "color": "primary"},
                {"label": "Off OT", "data": off, "color": "warning"},
                {"label": "Holiday OT", "data": holiday, "color": "danger"},
            ],
        }

    @classmethod
    def department_comparison(cls, context: dict) -> dict:
        """
        Hadir vs tidak hadir per department, dari baris yang sama dengan
        tabelnya. Ekornya dipotong jadi "Lainnya" mengikuti donut
        dashboard — dua puluh batang tidak terbaca, dan totalnya tetap
        utuh.
        """
        summary = cls.service.summary(context)

        totals: dict[str, list[int]] = defaultdict(lambda: [0, 0])

        for row in summary.rows:
            bucket = totals[row.department]

            bucket[0] += row.present
            bucket[1] += row.absent

        ordered = sorted(
            totals.items(),
            key=lambda item: item[1][0] + item[1][1],
            reverse=True,
        )

        head = ordered[:MAX_CHART_SEGMENTS]
        tail = ordered[MAX_CHART_SEGMENTS:]

        categories = [label for label, _ in head]

        present = [values[0] for _, values in head]
        absent = [values[1] for _, values in head]

        if tail:
            categories.append(OTHER_LABEL)

            present.append(sum(values[0] for _, values in tail))
            absent.append(sum(values[1] for _, values in tail))

        return {
            "categories": categories,
            "datasets": [
                {"label": "Present", "data": present, "color": "success"},
                {"label": "Absent", "data": absent, "color": "danger"},
            ],
        }

    # ------------------------------------------------------------------
    # Tabel
    # ------------------------------------------------------------------

    @classmethod
    def employee_table(cls, context: dict, *, page=None) -> dict:
        """
        Satu baris per pegawai, dipotong per halaman.

        Tiga angka yang sengaja dihitung dari tempat yang berbeda:

        * `items`   — hanya halaman yang diminta, sesudah kotak cari
        * `matched` — yang lolos kotak cari, untuk menghitung halaman
        * `total` + `totals` — **seluruh** pegawai yang lolos filter
          laporan, sama persis dengan yang dihitung KPI dan chart

        Baris Total karena itu tidak ikut berubah saat halaman digeser
        maupun saat ada yang diketik di kotak cari. Itu yang dimaksud
        "authoritative": angkanya menjawab "berapa seluruhnya pada filter
        ini", bukan "berapa jumlah yang kebetulan sedang terlihat" —
        pertanyaan kedua bisa dijumlahkan sendiri oleh yang membacanya,
        pertanyaan pertama tidak.
        """
        summary = cls.service.summary(context)

        totals = {
            metric: float(summary.total(metric))
            for metric in cls.TOTAL_METRICS
        }

        if page is None:
            return {
                "items": [cls.table_row(row) for row in summary.rows],
                "total": summary.headcount,
                "totals": totals,
            }

        matched = page.matching(summary.rows, text=cls.search_text)

        return page.envelope(
            items=[cls.table_row(row) for row in page.slice(matched)],
            matched=len(matched),
            total=summary.headcount,
            totals=totals,
        )

    # Kolom yang punya baris jumlah. Kolom identitas sengaja tidak ikut —
    # menjumlahkan nomor pegawai menghasilkan angka yang tidak salah
    # hitung, cuma tidak berarti apa pun.
    TOTAL_METRICS = (
        Metric.SCHEDULED,
        Metric.PRESENT,
        Metric.ABSENT,
        Metric.ANNUAL,
        Metric.SICK,
        Metric.OTHER_LEAVE,
        Metric.UNPAID,
        Metric.FIELD_BREAK,
        Metric.OFF_WORKED,
        Metric.HOLIDAY_WORKED,
        Metric.LATE,
        Metric.EARLY,
        Metric.OT_REGULAR,
        Metric.OT_OFF,
        Metric.OT_HOLIDAY,
        Metric.OT_TOTAL,
    )

    @staticmethod
    def search_text(row: EmployeeSummary) -> str:
        """
        Yang dicocokkan kotak cari: nama dan nomor pegawai.

        Bukan seluruh baris. Mengetik "3" di kotak cari yang mencocokkan
        semua kolom akan menyisakan hampir seluruh tabel — angka 3 ada di
        mana-mana — dan hasilnya terbaca seperti pencarian yang rusak.
        """
        return f"{row.employee_name} {row.employee_number}"

    @staticmethod
    def table_row(row: EmployeeSummary) -> dict:
        return {
            "id": row.employee_id,
            "employee": row.employee_name,
            "employee_number": row.employee_number,
            "location": row.location,
            "department": row.department,
            "section": row.section,
            Metric.SCHEDULED: row.scheduled,
            Metric.PRESENT: row.present,
            Metric.ABSENT: row.absent,
            Metric.ANNUAL: float(row.leave(Metric.ANNUAL)),
            Metric.SICK: float(row.leave(Metric.SICK)),
            Metric.OTHER_LEAVE: float(row.leave(Metric.OTHER_LEAVE)),
            Metric.UNPAID: float(row.leave(Metric.UNPAID)),
            Metric.FIELD_BREAK: row.field_break,
            Metric.OFF_WORKED: row.off_worked,
            Metric.HOLIDAY_WORKED: row.holiday_worked,
            Metric.LATE: row.late,
            Metric.EARLY: row.early,
            Metric.OT_REGULAR: _hours(row.ot_regular_minutes),
            Metric.OT_OFF: _hours(row.ot_off_minutes),
            Metric.OT_HOLIDAY: _hours(row.ot_holiday_minutes),
            Metric.OT_TOTAL: _hours(row.ot_total_minutes),
        }
