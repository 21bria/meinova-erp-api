from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from apps.administration.services.calendar_resolver import CalendarResolver
from apps.administration.models import WorkCalendar
from apps.hr.models import RotationPeriod, RotationPeriodStatus, RotationPeriodType


# Urutan sesuai `date.weekday()`: 0 = Senin.
WEEKDAY_FIELDS = (
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
)

# Dipakai kalau pegawai belum punya WorkCalendar sama sekali. Senin–Jumat
# adalah pola yang berlaku untuk mayoritas kantor; menganggap tujuh hari
# sebagai hari kerja akan memotong saldo cuti orang HO dua hari ekstra
# setiap minggu.
DEFAULT_WORKING_WEEKDAYS = frozenset({0, 1, 2, 3, 4})

MAX_LEAVE_SPAN_DAYS = 366


class LeaveDayCalculator:
    """
    Menghitung berapa hari cuti yang benar-benar terpotong dari saldo.

    Yang dipotong hanya **hari kerja** menurut kalender kerja pegawai:
    akhir pekan dan hari libur tidak dihitung. Untuk HO dengan
    WorkCalendar Senin–Jumat, cuti Jumat–Senin memotong 2 hari, bukan 4.

    Ada dua cara menghitung, dipilih dari pola kerja pegawai — bukan
    dari jenis cutinya, dan bukan dari form yang berbeda:

    **Pegawai roster** (punya `EmploymentAssignment.roster_crew`):
    dihitung dari siklus kerja/off-nya. Akhir pekan dan hari libur
    nasional tidak dikecualikan — rosternya sendiri yang jadi kalender.
    Kalau pegawainya sudah punya dokumen `SiteRotation` yang barisnya
    menutupi seluruh rentang cuti, baris itulah yang dipakai — bukan
    rumus siklusnya. Baris roster boleh digeser tangan (swing mundur
    karena cuaca, pesawat ditunda), dan begitu digeser, rumusnya tidak
    lagi menggambarkan jadwal yang sebenarnya berlaku.

    **Selain itu** (HO dan sejenisnya): dihitung dari WorkCalendar dan
    Holiday lewat `CalendarResolver`
    (`apps/administration/services/calendar_resolver.py`) — satu-satunya
    tempat urutan resolusinya ditulis:

    1. `EmploymentAssignment.working_calendar` milik pegawai
    2. WorkCalendar bercakupan LOCATION (company + location pegawai)
    3. WorkCalendar bercakupan COMPANY
    4. WorkCalendar bercakupan GLOBAL (berlaku seluruh perusahaan)
    5. Senin–Jumat — diputuskan **di sini**, bukan di resolver

    Hari libur **digabung**, bukan dipilih: GLOBAL + COMPANY +
    SELECTED_COMPANIES + LOCATION yang cocok. Libur nasional tetap
    berlaku di lokasi yang juga punya libur lokalnya sendiri.
    """

    # ------------------------------------------------------------------
    # Resolusi kalender
    # ------------------------------------------------------------------

    @staticmethod
    def get_employment(employee):
        return getattr(employee, "employment", None)

    @staticmethod
    def get_organization(employee):
        return getattr(employee, "organization", None)

    @classmethod
    def resolve_calendar(cls, employee) -> WorkCalendar | None:
        """
        Delegasi ke `CalendarResolver` — **bukan** salinan urutannya.

        Presedennya (override pegawai → LOCATION → COMPANY → GLOBAL)
        tinggal di `apps/administration/services/calendar_resolver.py`.
        Method ini dipertahankan karena empat modul sudah memanggilnya
        dengan nama ini, dan mengganti nama di tempat pemanggilan bukan
        bagian dari task ini.
        """
        return CalendarResolver.resolve_for_employee(employee)

    @staticmethod
    def working_weekdays(calendar: WorkCalendar | None) -> frozenset[int]:
        if calendar is None:
            return DEFAULT_WORKING_WEEKDAYS

        days = {
            index
            for index, field in enumerate(WEEKDAY_FIELDS)
            if getattr(calendar, field, False)
        }

        # Kalender yang semua harinya dimatikan hampir pasti salah isi.
        # Memakainya apa adanya membuat setiap cuti memotong nol hari.
        return frozenset(days) if days else DEFAULT_WORKING_WEEKDAYS

    @classmethod
    def resolve_holidays(
        cls,
        employee,
        start: date,
        end: date,
    ) -> set[date]:
        """
        Delegasi ke `CalendarResolver`. Cakupan hari libur **digabung**,
        bukan dipilih yang paling spesifik — lihat alasannya di sana.
        """
        return CalendarResolver.resolve_holidays_for_employee(
            employee,
            start,
            end,
        )

    # ------------------------------------------------------------------
    # Perhitungan
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Roster
    # ------------------------------------------------------------------

    @classmethod
    def resolve_roster(cls, employee) -> tuple[date, int, int] | None:
        """
        Mengembalikan `(jangkar, hari_kerja, hari_off)` kalau pegawai
        memang memakai roster, selain itu None.

        Jangkarnya `roster_start_override` dulu, baru
        `RosterCrew.cycle_start_date` — itu arti "override".
        """
        employment = cls.get_employment(employee)

        if employment is None or not employment.roster_crew_id:
            return None

        crew = employment.roster_crew
        schedule = crew.work_schedule

        work_days = schedule.cycle_work_days or 0
        off_days = schedule.cycle_off_days or 0

        # Siklus tanpa hari kerja atau tanpa hari off bukan roster;
        # membaginya akan membuat setiap hari terhitung sama.
        if not work_days or not off_days:
            return None

        anchor = employment.roster_start_override or crew.cycle_start_date

        if anchor is None:
            return None

        return anchor, work_days, off_days

    @staticmethod
    def resolve_rotation_work_days(
        employee,
        start: date,
        end: date,
    ) -> int | None:
        """
        Menghitung hari kerja dari baris `RotationPeriod` yang nyata.

        Mengembalikan None kalau barisnya tidak ada atau tidak menutupi
        seluruh rentang — dan itu disengaja. Cuti yang separuhnya jatuh
        di luar periode yang sudah digenerate akan terhitung kurang
        kalau bagian yang tidak tertutup diam-diam dianggap hari off.
        Lebih baik jatuh kembali ke rumus siklus, yang setidaknya
        berlaku untuk seluruh rentang.
        """
        periods = list(
            RotationPeriod.objects
            .filter(
                employee=employee,
                is_deleted=False,
                start_date__lte=end,
                end_date__gte=start,
            )
            .exclude(status=RotationPeriodStatus.CANCELLED)
            .order_by("start_date")
            .values("period_type", "start_date", "end_date")
        )

        if not periods:
            return None

        covered_until = start
        total = 0

        for period in periods:
            # Ada lubang di antara dua periode: rentangnya tidak
            # tertutup penuh, jadi hasilnya tidak bisa dipercaya.
            if period["start_date"] > covered_until:
                return None

            if period["period_type"] != RotationPeriodType.WORK:
                covered_until = max(
                    covered_until,
                    period["end_date"] + timedelta(days=1),
                )

                continue

            # Potong ke rentang cuti, dan buang bagian yang sudah
            # dihitung periode sebelumnya kalau ada tumpang tindih.
            block_start = max(period["start_date"], covered_until, start)
            block_end = min(period["end_date"], end)

            if block_end >= block_start:
                total += (block_end - block_start).days + 1

            covered_until = max(
                covered_until,
                period["end_date"] + timedelta(days=1),
            )

        if covered_until <= end:
            return None

        return total

    @staticmethod
    def is_roster_working_day(
        target: date,
        anchor: date,
        work_days: int,
        off_days: int,
    ) -> bool:
        # Modulo Python selalu mengembalikan nilai non-negatif untuk
        # pembagi positif, jadi tanggal sebelum jangkar ikut terhitung
        # mundur dengan benar — jangkar tidak harus siklus pertama.
        offset = (target - anchor).days % (work_days + off_days)

        return offset < work_days

    # ------------------------------------------------------------------
    # Perhitungan hari kerja
    # ------------------------------------------------------------------

    @classmethod
    def count_working_days(
        cls,
        employee,
        start: date,
        end: date,
    ) -> int:
        # Jadwal yang benar-benar dijadwalkan menang atas rumusnya.
        # Kalau belum ada dokumen roster yang menutupi rentang ini,
        # jatuh ke perhitungan siklus di bawah.
        scheduled = cls.resolve_rotation_work_days(employee, start, end)

        if scheduled is not None:
            return scheduled

        roster = cls.resolve_roster(employee)

        if roster is not None:
            anchor, work_days, off_days = roster

            # Akhir pekan dan hari libur nasional sengaja TIDAK
            # dikecualikan di sini: pegawai roster tetap bekerja saat
            # blok kerjanya jatuh di hari Minggu atau tanggal merah —
            # rosternya sendiri yang jadi kalender. Konsekuensi yang
            # diinginkan: cuti yang diambil saat blok off memotong nol
            # hari, jadi tidak perlu diajukan sama sekali.
            total = 0
            current = start

            while current <= end:
                if cls.is_roster_working_day(
                    current,
                    anchor,
                    work_days,
                    off_days,
                ):
                    total += 1

                current += timedelta(days=1)

            return total

        working_weekdays = cls.working_weekdays(
            cls.resolve_calendar(employee),
        )

        holidays = cls.resolve_holidays(employee, start, end)

        total = 0
        current = start

        while current <= end:
            if (
                current.weekday() in working_weekdays
                and current not in holidays
            ):
                total += 1

            current += timedelta(days=1)

        return total

    @classmethod
    def calculate(
        cls,
        *,
        employee,
        start: date | None,
        end: date | None,
        is_half_day: bool = False,
    ) -> Decimal | None:
        if employee is None or start is None or end is None:
            return None

        if end < start:
            return None

        if is_half_day:
            return Decimal("0.5")

        # Pagar kewarasan: rentang selebar ini pasti salah ketik tahun,
        # dan loop harian di bawah tidak perlu ikut menanggungnya.
        if (end - start).days > MAX_LEAVE_SPAN_DAYS:
            return None

        return Decimal(
            cls.count_working_days(employee, start, end),
        )
