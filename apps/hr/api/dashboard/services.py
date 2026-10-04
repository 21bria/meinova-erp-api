from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from django.db.models import (
    BooleanField,
    CharField,
    Count,
    ExpressionWrapper,
    Q,
    Sum,
    Value,
)
from django.db.models.functions import Coalesce

from apps.accounts.permissions import view_permission_for
from apps.accounts.scoping import DataScopeService
from apps.framework.periods import trend_buckets
from apps.hr.models import (
    LEAVE_DEDUCTING_STATUSES,
    Employee,
    EmployeeAttendance,
    EmployeeEducation,
    EmployeeLeave,
    EmployeeOvertime,
    EmploymentAssignment,
    JobVacancy,
    OvertimeStatus,
    TrainingProgram,
    TrainingProgramStatus,
    VacancyStatus,
)
from apps.hr.api.attendance.classification import (
    business_trip_only_q,
    present_q,
)
from apps.hr.models.attendance.choices import AttendanceStatus


# "Masuk kerja" dan "dinas" dibaca dari
# `apps.hr.api.attendance.classification` — modul yang sama dengan HR
# Period Summary (BT-3R). Hari dinas tanpa tap bukan kehadiran fisik
# **dan** bukan mangkir, jadi ia keluar dari hitungan kehadiran sama
# sekali: tidak menambah pembilang, tidak menambah penyebut — aturan
# yang sama dengan `Present ÷ (Present + Absent)` di laporan.

# Libur dan hari off tidak dihitung sebagai peluang hadir — kalau ikut
# masuk penyebut, persentase kehadiran ikut turun setiap tanggal merah.
#
# Cuti yang sudah disetujui ikut dikecualikan, dan itu bukan kelonggaran:
# yang dijawab metrik ini adalah ketidakhadiran yang **tidak
# direncanakan**. Menghitung cuti sebagai tidak hadir membuat orang yang
# mengambil haknya menurunkan angka unitnya — dan justru unit yang
# tertib administrasinya yang terlihat paling buruk. Sakit dan izin
# sengaja **tetap** masuk penyebut: keduanya mendadak, dan itu memang
# yang perlu terlihat.
NON_WORKING_STATUSES = [
    AttendanceStatus.HOLIDAY,
    AttendanceStatus.DAY_OFF,
    AttendanceStatus.LEAVE,
]

UNASSIGNED_LABEL = "Belum Ditentukan"

MAX_CHART_SEGMENTS = 5
OTHER_LABEL = "Lainnya"


# ----------------------------------------------------------------------
# Cakupan data per baris
# ----------------------------------------------------------------------
#
# Dashboard **tidak** lewat `BaseMasterViewSet.filter_queryset()`, jadi
# penyaringan cakupan data tidak ikut sendiri seperti di layar
# daftar. Tanpa peta di bawah, admin yang hanya boleh melihat 6 pegawai
# tetap membaca "Total Pegawai 10" — dan selisih itu justru memberi tahu
# ada 4 baris yang disembunyikan darinya.
#
# Petanya sengaja disamakan persis dengan `data_scope` di viewset
# masing-masing (`apps/hr/api/*/views.py`); kalau salah satu diubah,
# yang di sini harus ikut, kalau tidak angka dashboard tidak akan cocok
# dengan isi tabelnya.

EMPLOYEE_SCOPE = {
    "company": "organization__company",
    "branch": "organization__branch",
    "location": "organization__location",
    "division": "organization__division",
    "department": "organization__department",
    "section": "organization__section",
    "own": "user_id",
}

# Attendance / Leave / Overtime: organisasinya sudah didenormalisasi ke
# record, sisanya lewat penempatan pegawai.
TRANSACTION_SCOPE = {
    "company": "company",
    "branch": "branch",
    "location": "location",
    "division": "employee__organization__division",
    "department": "employee__organization__department",
    "section": "employee__organization__section",
    "own": "employee__user_id",
}

# JobVacancy tidak menunjuk pegawai mana pun, jadi tidak punya `own`:
# lowongan bukan "data milik seseorang".
VACANCY_SCOPE = {
    "company": "company",
    "branch": "branch",
    "location": "location",
    "division": "division",
    "department": "department",
}

TRAINING_SCOPE = {
    "company": "company",
}


def trend(current, previous, *, period: str = "dari periode sebelumnya"):
    """
    Perubahan relatif terhadap periode sebelumnya.

    Mengembalikan None kalau pembandingnya nol — persentase perubahan
    dari nol tidak punya arti, dan menampilkan "naik 100%" untuk data
    yang baru mulai terisi lebih menyesatkan daripada tidak menampilkan
    apa-apa. Frontend menyembunyikan bagian tren saat nilainya None.
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


class HRDashboardService:
    """
    Seluruh angka dashboard HR dihitung di sini dari data transaksi —
    tidak ada nilai yang di-hardcode. Widget yang datanya belum ada
    modelnya sengaja tidak dibuat, bukan diisi angka contoh.
    """

    # ------------------------------------------------------------------
    # Periode
    # ------------------------------------------------------------------
    #
    # Resolver tidak pernah menghitung sendiri batas bulan: rentangnya
    # sudah ditentukan `apps.framework.periods` dari query string, jadi
    # widget yang sama melayani mode harian, mingguan, bulanan, maupun
    # rentang tanggal bebas tanpa cabang khusus.

    @staticmethod
    def bounds(context: dict) -> tuple[date, date]:
        period = context["period"]

        return period["start"], period["end"]

    @staticmethod
    def previous_bounds(context: dict) -> tuple[date, date]:
        previous = context["period"]["previous"]

        return previous["start"], previous["end"]

    @staticmethod
    def compare_label(context: dict) -> str:
        return context["period"].get(
            "compare_label",
            "dari periode sebelumnya",
        )

    # ------------------------------------------------------------------
    # Penyaringan organisasi
    # ------------------------------------------------------------------

    @staticmethod
    def apply_filters(queryset, context: dict, *, prefix: str = ""):
        """
        Filter dropdown yang **dipilih** pengguna di toolbar.

        Ditulis sekali untuk ketiga queryset (pegawai, transaksi,
        lowongan) karena yang membedakan cuma awalan relasinya —
        `organization__company` vs `company`. Tiga salinan yang harus
        tetap sama adalah cara filter baru diam-diam cuma berlaku di
        sebagian widget, dan selisih itu tidak berbunyi: angkanya tetap
        keluar, cuma tidak menyempit.

        Ketiganya di-AND-kan, dan itu jawaban untuk "kalau pilih Jakarta
        HO saja": Location adalah sumbu tersendiri, bukan turunan
        Company — memilih lokasi tanpa memilih company menampilkan
        pegawai **semua** company yang ditempatkan di sana.

        Nilai boleh berupa daftar (filter bercentang banyak); sesama
        nilai di satu filter di-OR-kan lewat `__in`. Tidak ada yang
        dicentang = tanpa penyaringan, bukan tanpa hasil.
        """
        for key in ("company", "branch", "location"):
            value = context.get(key)

            if not value:
                continue

            if isinstance(value, (list, tuple, set)):
                queryset = queryset.filter(
                    **{f"{prefix}{key}_id__in": list(value)},
                )
            else:
                queryset = queryset.filter(
                    **{f"{prefix}{key}_id": value},
                )

        return queryset

    @classmethod
    def employee_queryset(cls, context: dict):
        queryset = cls.apply_filters(
            Employee.objects.filter(
                is_active=True,
                is_deleted=False,
            ),
            context,
            prefix="organization__",
        )

        return DataScopeService.filter(
            queryset,
            EMPLOYEE_SCOPE,
            context.get("user"),
            required_permission=view_permission_for(queryset.model),
        )

    @classmethod
    def scoped(cls, queryset, context: dict):
        """
        Untuk model transaksi yang sudah membawa company/branch/location
        hasil denormalisasi (attendance, leave, overtime).

        Dua penyaringan bertumpuk di sini, dan keduanya perlu: filter
        dropdown yang **dipilih** pengguna di layar, lalu cakupan data
        yang **tidak bisa** ia lepas.
        """
        # Izin diturunkan dari **model yang sedang dibaca**, bukan
        # ditulis satu per satu di tiap widget: helper ini melayani
        # absensi, cuti, lembur, dan perjalanan sekaligus, dan daftar
        # manual di sini akan menyimpang begitu widget baru ditambahkan.
        return DataScopeService.filter(
            cls.apply_filters(queryset, context),
            TRANSACTION_SCOPE,
            context.get("user"),
            required_permission=view_permission_for(queryset.model),
        )

    # ------------------------------------------------------------------
    # Headcount
    # ------------------------------------------------------------------

    @classmethod
    def headcount_at(cls, context: dict, at: date) -> int:
        """
        Jumlah pegawai per satu tanggal. Pegawai tanpa
        EmploymentAssignment tetap dihitung — banyak klien mengisi data
        pribadi lebih dulu, dan menghilangkannya dari headcount membuat
        angkanya terbaca lebih kecil dari kenyataan.
        """
        return (
            cls.employee_queryset(context)
            .filter(
                Q(employment__isnull=True)
                | Q(employment__join_date__isnull=True)
                | Q(employment__join_date__lte=at),
            )
            .filter(
                Q(employment__termination_date__isnull=True)
                | Q(employment__termination_date__gt=at),
            )
            .distinct()
            .count()
        )

    # ------------------------------------------------------------------
    # Kehadiran
    # ------------------------------------------------------------------

    @classmethod
    def attendance_rate(
        cls,
        context: dict,
        start: date,
        end: date,
    ) -> float | None:
        queryset = cls.scoped(
            EmployeeAttendance.objects.filter(
                work_date__gte=start,
                work_date__lte=end,
                is_deleted=False,
            ),
            context,
        ).exclude(status__in=NON_WORKING_STATUSES).exclude(business_trip_only_q())

        totals = queryset.aggregate(
            total=Count("id"),
            present=Count(
                "id",
                filter=present_q(),
            ),
        )

        total = totals.get("total") or 0

        if not total:
            return None

        return round((totals.get("present") or 0) / total * 100, 2)

    # ------------------------------------------------------------------
    # Widget: kartu KPI
    # ------------------------------------------------------------------

    @classmethod
    def total_employees(cls, context: dict) -> dict:
        _, end = cls.bounds(context)
        _, prev_end = cls.previous_bounds(context)

        current = cls.headcount_at(context, end)
        previous = cls.headcount_at(context, prev_end)

        return {
            "value": current,
            "trend": trend(
                current,
                previous,
                period=cls.compare_label(context),
            ),
        }

    @classmethod
    def attendance_rate_widget(cls, context: dict) -> dict:
        start, end = cls.bounds(context)
        prev_start, prev_end = cls.previous_bounds(context)

        current = cls.attendance_rate(context, start, end)
        previous = cls.attendance_rate(context, prev_start, prev_end)

        return {
            "value": current,
            "trend": trend(
                current,
                previous,
                period=cls.compare_label(context),
            ),
        }

    @classmethod
    def leave_count(cls, context: dict, start: date, end: date) -> int:
        # Cuti dihitung kalau rentangnya beririsan dengan periode, bukan
        # hanya kalau mulainya di dalam periode — cuti panjang yang
        # melintasi bulan tetap terhitung sebagai cuti aktif.
        #
        # **RECORDED dan APPROVED, bukan RECORDED saja.** Sejak cuti
        # bisa diajukan sendiri lewat engine workflow, cuti yang lolos
        # seluruh meja berhenti di APPROVED dan tidak pernah menjadi
        # RECORDED. Menyaring satu status membuat kartu ini membaca nol
        # di tenant yang seluruh cutinya lewat pengajuan — dan nol itu
        # tidak bisa dibedakan dari "memang tidak ada yang cuti".
        # Daftarnya dipakai bersama `LeaveBalance.used`, jadi angka di
        # dashboard dan angka yang memotong saldo tidak bisa berbeda.
        return cls.scoped(
            EmployeeLeave.objects.filter(
                start_date__lte=end,
                end_date__gte=start,
                status__in=LEAVE_DEDUCTING_STATUSES,
                is_deleted=False,
            ),
            context,
        ).count()

    @classmethod
    def active_leaves(cls, context: dict) -> dict:
        start, end = cls.bounds(context)
        prev_start, prev_end = cls.previous_bounds(context)

        current = cls.leave_count(context, start, end)
        previous = cls.leave_count(context, prev_start, prev_end)

        return {
            "value": current,
            "trend": trend(
                current,
                previous,
                period=cls.compare_label(context),
            ),
        }

    @classmethod
    def overtime_total_hours(
        cls,
        context: dict,
        start: date,
        end: date,
    ) -> float:
        minutes = (
            cls.scoped(
                EmployeeOvertime.objects.filter(
                    work_date__gte=start,
                    work_date__lte=end,
                    status=OvertimeStatus.RECORDED,
                    is_deleted=False,
                ),
                context,
            )
            .aggregate(total=Sum("duration_minutes"))
            .get("total")
        ) or 0

        return round(minutes / 60, 1)

    @classmethod
    def overtime_hours(cls, context: dict) -> dict:
        start, end = cls.bounds(context)
        prev_start, prev_end = cls.previous_bounds(context)

        current = cls.overtime_total_hours(context, start, end)
        previous = cls.overtime_total_hours(context, prev_start, prev_end)

        return {
            "value": current,
            "trend": trend(
                current,
                previous,
                period=cls.compare_label(context),
            ),
        }

    @classmethod
    def turnover_for(
        cls,
        context: dict,
        start: date,
        end: date,
    ) -> float | None:
        employees = cls.employee_queryset(context)

        leavers = (
            EmploymentAssignment.objects
            .filter(
                employee__in=employees,
                termination_date__gte=start,
                termination_date__lte=end,
                is_deleted=False,
            )
            .count()
        )

        opening = cls.headcount_at(context, start)
        closing = cls.headcount_at(context, end)

        average = (opening + closing) / 2

        if not average:
            return None

        return round(leavers / average * 100, 2)

    @classmethod
    def turnover_rate(cls, context: dict) -> dict:
        start, end = cls.bounds(context)
        prev_start, prev_end = cls.previous_bounds(context)

        current = cls.turnover_for(context, start, end)
        previous = cls.turnover_for(context, prev_start, prev_end)

        return {
            "value": current,
            "trend": trend(
                current,
                previous,
                period=cls.compare_label(context),
            ),
        }

    @classmethod
    def vacancy_queryset(cls, context: dict):
        queryset = cls.apply_filters(
            JobVacancy.objects.filter(is_deleted=False),
            context,
        )

        return DataScopeService.filter(
            queryset,
            VACANCY_SCOPE,
            context.get("user"),
            required_permission=view_permission_for(JobVacancy),
        )

    @classmethod
    def open_vacancies(cls, context: dict) -> dict:
        _, end = cls.bounds(context)
        _, prev_end = cls.previous_bounds(context)

        base = cls.vacancy_queryset(context).filter(
            status=VacancyStatus.OPEN,
        )

        current = base.filter(
            open_date__lte=end,
        ).filter(
            Q(close_date__isnull=True) | Q(close_date__gte=end),
        ).count()

        previous = base.filter(
            open_date__lte=prev_end,
        ).filter(
            Q(close_date__isnull=True) | Q(close_date__gte=prev_end),
        ).count()

        return {
            "value": current,
            "trend": trend(
                current,
                previous,
                period=cls.compare_label(context),
            ),
        }

    # ------------------------------------------------------------------
    # Widget: chart
    # ------------------------------------------------------------------

    @classmethod
    def attendance_trend(cls, context: dict) -> dict:
        """
        Cacahan hadir / telat / tidak hadir per satuan periode.

        **Bukan persentase.** Rata-rata kehadiran di perusahaan yang
        sehat duduk di 97–99% sepanjang tahun, jadi garisnya tidak
        pernah keluar dari 3% teratas sumbunya dan riak setengah persen
        tergambar seperti jurang. Yang ditindaklanjuti HR tiap pagi
        adalah cacahannya. Persentasenya tetap dikirim kartu KPI
        `attendance_rate_widget`.

        Satuan titiknya mengikuti mode periode: harian saat user memilih
        satu hari, mingguan saat memilih minggu, bulanan saat memilih
        bulan. Tanpa ini, memilih "hari ini" menghasilkan chart satu
        batang yang tidak memberi tahu apa-apa.

        Cuti, libur, dan hari off tidak masuk hitungan sama sekali —
        ketiganya bukan peluang hadir. Hari dinas tanpa tap juga tidak:
        ia bukan kehadiran fisik dan bukan mangkir (BT-3R); dinas yang
        punya tap terhitung hadir. Sisanya yang bukan hadir (absent,
        sakit, izin, incomplete) masuk "Tidak Hadir": memberi masing-
        masing warnanya sendiri menghasilkan enam tumpukan yang tidak
        terbaca, dan membuangnya diam-diam membuat batangnya tidak
        pernah setinggi jumlah pegawai yang dijadwalkan.
        """
        period = context["period"]
        today = date.today()

        buckets = [
            bucket
            for bucket in trend_buckets(period)
            # Bucket yang belum terjadi tidak dikirim sebagai nol —
            # batang kosong di ujung terbaca sebagai kehadiran anjlok,
            # padahal datanya memang belum ada.
            if bucket["start"] <= today
        ]

        if not buckets:
            return {
                "categories": [],
                "datasets": [],
                "year": period["year"],
            }

        # Satu query untuk seluruh chart, bukan satu per bucket:
        # dua belas bucket berarti dua belas agregasi untuk jawaban yang
        # sumbernya tabel yang sama.
        rows = (
            cls.scoped(
                EmployeeAttendance.objects.filter(
                    work_date__gte=buckets[0]["start"],
                    work_date__lte=buckets[-1]["end"],
                    is_deleted=False,
                ),
                context,
            )
            .exclude(status__in=NON_WORKING_STATUSES)
            .exclude(business_trip_only_q())
            .annotate(is_present=ExpressionWrapper(
                present_q(),
                output_field=BooleanField(),
            ))
            .values("work_date", "status", "is_present")
            .annotate(total=Count("id"))
        )

        # {tanggal: {(status, hadir?): jumlah}}
        by_day: dict[date, dict[tuple[str, bool], int]] = {}

        for row in rows:
            key = (row["status"], row["is_present"])

            by_day.setdefault(row["work_date"], {})[key] = row["total"]

        present = []
        late = []
        absent = []
        categories = []

        for bucket in buckets:
            counts = {"present": 0, "late": 0, "absent": 0}

            current = bucket["start"]

            while current <= bucket["end"]:
                for (status, physical), total in by_day.get(current, {}).items():
                    if status == AttendanceStatus.LATE:
                        counts["late"] += total
                    elif physical:
                        counts["present"] += total
                    else:
                        counts["absent"] += total

                current += timedelta(days=1)

            categories.append(bucket["label"])

            present.append(counts["present"])
            late.append(counts["late"])
            absent.append(counts["absent"])

        # Warnanya **nama semantik**, bukan hex. Alasannya sama dengan
        # `icon`/`color` di katalog aplikasi: hex yang terbaca jelas di
        # latar putih lazimnya kusam di mode gelap, dan yang tahu mode
        # apa yang sedang dipakai cuma frontend. Nama yang tidak dikenal
        # jatuh ke rotasi warna bawaan, tidak error.
        return {
            "categories": categories,
            "datasets": [
                {"label": "Hadir", "data": present, "color": "success"},
                {"label": "Telat", "data": late, "color": "warning"},
                {"label": "Tidak Hadir", "data": absent, "color": "danger"},
            ],
            "year": period["year"],
        }

    @classmethod
    def _grouped_distribution(cls, rows, total: int) -> dict:
        """
        Memotong ekor distribusi jadi "Lainnya". Donut dengan 20 irisan
        tidak terbaca; angka totalnya tetap utuh.
        """
        segments = []
        tail = 0

        for index, (label, count) in enumerate(rows):
            if index < MAX_CHART_SEGMENTS:
                segments.append(
                    {
                        "label": label,
                        "value": count,
                        "percentage": (
                            round(count / total * 100, 1)
                            if total
                            else 0
                        ),
                    }
                )
            else:
                tail += count

        if tail:
            segments.append(
                {
                    "label": OTHER_LABEL,
                    "value": tail,
                    "percentage": (
                        round(tail / total * 100, 1) if total else 0
                    ),
                }
            )

        return {
            "series": segments,
            "total": total,
        }

    @classmethod
    def employees_by_unit(cls, context: dict) -> dict:
        """
        Sebaran pegawai per unit kerja.

        **Department dulu, division sebagai jatuhannya** — dan urutan itu
        bukan selera. Di struktur ini hanya Company yang wajib, sisanya
        boleh dilompati, dan yang paling lazim terisi di lapangan justru
        department: penempatan pegawai diturunkan dari jabatannya, dan
        `Position` menunjuk department, bukan division. Versi lamanya
        mengelompokkan lewat `organization__division` saja, sehingga di
        tenant peragaan **kesebelas** pegawai jatuh ke satu irisan
        "Belum Ditentukan" — donut satu warna yang terbaca seperti
        widget yang gagal memuat, bukan seperti data yang memang belum
        diisi.

        Jatuhannya tetap dipertahankan supaya tenant yang justru mengisi
        division dan melompati department tidak kena bug yang sama
        secara terbalik.
        """
        employees = cls.employee_queryset(context)

        counts = (
            employees
            .values(
                unit=Coalesce(
                    "organization__department__name",
                    "organization__division__name",
                    Value(UNASSIGNED_LABEL),
                    output_field=CharField(),
                ),
            )
            .annotate(total=Count("id", distinct=True))
            .order_by("-total")
        )

        rows = [(item["unit"], item["total"]) for item in counts]

        total = sum(count for _, count in rows)

        return cls._grouped_distribution(rows, total)

    @classmethod
    def employees_by_education(cls, context: dict) -> dict:
        """
        Sebaran jenjang pendidikan tertinggi.

        Pegawai yang **belum punya** baris pendidikan ikut dihitung,
        sebagai "Belum Ditentukan". Kalau dibuang diam-diam, batang di
        layar menjumlahkan angka yang lebih kecil daripada Total Pegawai
        di kartu sebelahnya, dan selisih itu tidak punya penjelasan di
        mana pun — pembacanya menyimpulkan salah satu dari dua angka itu
        salah. Yang belum diisi memang informasi tersendiri: itu
        pekerjaan HR yang tertunda, bukan ketiadaan data.
        """
        employees = cls.employee_queryset(context)

        headcount = employees.distinct().count()

        counts = (
            EmployeeEducation.objects
            .filter(
                employee__in=employees,
                is_highest_education=True,
                is_deleted=False,
            )
            .values("education__name")
            .annotate(total=Count("employee_id", distinct=True))
            .order_by("-total")
        )

        series = [
            {
                "label": item["education__name"] or UNASSIGNED_LABEL,
                "value": item["total"],
            }
            for item in counts
        ]

        # Sisa yang tidak tercakup satu pun baris pendidikan tertinggi.
        # `max(0, ...)` menjaga dari data ganda (dua baris bertanda
        # tertinggi untuk satu orang): yang muncul cukup pembagiannya,
        # bukan angka negatif yang menjatuhkan chart-nya.
        unassigned = max(
            0,
            headcount - sum(item["value"] for item in series),
        )

        if unassigned:
            series.append(
                {
                    "label": UNASSIGNED_LABEL,
                    "value": unassigned,
                }
            )

        return {
            "series": series,
            "total": sum(item["value"] for item in series),
        }

    # ------------------------------------------------------------------
    # Widget: daftar
    # ------------------------------------------------------------------

    @classmethod
    def leave_recap(cls, context: dict) -> dict:
        start, end = cls.bounds(context)

        rows = (
            cls.scoped(
                EmployeeLeave.objects.filter(
                    start_date__lte=end,
                    end_date__gte=start,
                    status__in=LEAVE_DEDUCTING_STATUSES,
                    is_deleted=False,
                ),
                context,
            )
            .values("leave_type__name", "leave_type__code")
            .annotate(
                count=Count("id"),
                days=Sum("total_days"),
                # Berapa **orang**, bukan berapa dokumen. Lima catatan
                # cuti milik satu orang dan milik lima orang adalah dua
                # keadaan yang sangat berbeda, dan kolom Jumlah tidak
                # pernah bisa membedakannya.
                people=Count("employee_id", distinct=True),
            )
            .order_by("-count")
        )

        items = [
            {
                "label": row["leave_type__name"] or UNASSIGNED_LABEL,
                # Keterangan di bawah judul baris. Kodenya dilewati
                # kalau jenis cutinya memang belum diisi — "None · 2
                # pegawai" lebih buruk daripada tanpa kode sama sekali.
                "hint": " · ".join(
                    part
                    for part in (
                        row["leave_type__code"],
                        f"{row['people']} pegawai",
                    )
                    if part
                ),
                "count": row["count"],
                "days": float(row["days"] or Decimal("0.0")),
            }
            for row in rows
        ]

        return {
            "items": items,
            "total": sum(item["count"] for item in items),
        }

    @classmethod
    def recent_leaves(cls, context: dict, limit: int = 5) -> dict:
        """
        Cuti terbaru **pada periode terpilih** — rincian baris dari
        angka yang dijumlahkan Rekap Cuti di sebelahnya.

        **Dulu tidak ikut periode sama sekali**, dan itu satu-satunya
        widget yang begitu. Akibatnya dua kartu bersebelahan menjawab
        pertanyaan yang berbeda tanpa satu pun tanda di layar: Rekap
        Cuti berbunyi "1 cuti bulan ini" sementara daftar di kanannya
        memuat lima baris bertanggal November, Oktober, dan September.
        Yang membaca menyimpulkan salah satu dari keduanya salah — dan
        keduanya benar, cuma tidak menjawab pertanyaan yang sama.

        Sekarang keduanya menyaring rentang **dan** status yang sama,
        jadi jumlah baris di sini rekonsiliasi persis dengan kolom
        Jumlah di sebelah (sampai batas `limit`; sisanya lewat "Lihat
        Semua"). Pengajuan yang masih menunggu keputusan sengaja tidak
        ikut — tempatnya kotak masuk workflow, dan mencampurnya di sini
        membuat "cuti terbaru" berarti dua hal sekaligus.
        """
        start, end = cls.bounds(context)

        rows = (
            cls.scoped(
                EmployeeLeave.objects.filter(
                    start_date__lte=end,
                    end_date__gte=start,
                    status__in=LEAVE_DEDUCTING_STATUSES,
                    is_deleted=False,
                ),
                context,
            )
            .select_related("employee", "leave_type")
            .order_by("-created_at", "-id")[:limit]
        )

        return {
            "items": [
                {
                    "id": row.id,
                    "name": row.employee.full_name,
                    "type": (
                        row.leave_type.name
                        if row.leave_type_id
                        else UNASSIGNED_LABEL
                    ),
                    "date": row.start_date,
                    "days": float(row.total_days or Decimal("0.0")),
                    "status": row.status,
                }
                for row in rows
            ],
        }

    @classmethod
    def upcoming_trainings(cls, context: dict, limit: int = 5) -> dict:
        today = date.today()

        queryset = TrainingProgram.objects.filter(
            start_date__gte=today,
            is_deleted=False,
        ).exclude(
            status=TrainingProgramStatus.CANCELLED,
        )

        company = context.get("company")

        if company:
            # Program tanpa company berlaku lintas company, jadi ikut
            # ditampilkan — bukan disaring keluar.
            #
            # Nilainya boleh berupa daftar, mengikuti bentuk filter
            # bercentang banyak — kalau tidak, satu filter yang besok
            # dijadikan multi-select membuat widget ini melempar
            # `int() argument must be...` sementara sebelas widget lain
            # tetap jalan.
            values = (
                list(company)
                if isinstance(company, (list, tuple, set))
                else [company]
            )

            queryset = queryset.filter(
                Q(company_id__in=values) | Q(company__isnull=True),
            )

        # Branch dan Location **tidak** ikut, dan itu bukan kelalaian:
        # `TrainingProgram` memang tidak menyimpan keduanya (tempatnya
        # `venue`, teks bebas — pelatihan lazim di hotel atau kantor
        # vendor yang tidak ada di master lokasi kerja). Menyaringnya
        # lewat peserta akan membuang program yang pesertanya belum
        # didaftarkan, dan justru program yang belum terisi itu yang
        # perlu terlihat di daftar "mendatang".

        # `allow_null=True` dengan alasan yang sama: di model ini kolom
        # company yang kosong berarti "berlaku untuk semua", bukan
        # "belum diisi". Program induksi K3 yang dipakai seluruh grup
        # tidak boleh hilang dari layar admin site.
        queryset = DataScopeService.filter(
            queryset,
            TRAINING_SCOPE,
            context.get("user"),
            allow_null=True,
            required_permission=view_permission_for(queryset.model),
        )

        rows = (
            queryset
            # Bukan `participants` — nama itu sudah dipakai related_name
            # TrainingParticipant, dan Django menolak anotasi yang
            # bentrok dengan field model.
            .annotate(
                participant_total=Count(
                    "participants",
                    filter=Q(participants__is_deleted=False),
                    distinct=True,
                ),
            )
            .order_by("start_date")[:limit]
        )

        return {
            "items": [
                {
                    "id": row.id,
                    "name": row.name,
                    "code": row.code,
                    "date": row.start_date,
                    "participants": row.participant_total,
                    "quota": row.quota,
                }
                for row in rows
            ],
        }
