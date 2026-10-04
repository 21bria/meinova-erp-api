"""
Adapter Payroll → modul sumber.

Satu-satunya tempat di modul Payroll yang mengenal `EmployeeAttendance`,
`EmployeeLeave`, dan `EmployeeOvertime`. Mesin hitung membaca
`PeriodFacts` — sebuah dataclass berisi angka — dan tidak pernah
menyentuh ORM modul HR.

**Kenapa dipisah, bukan langsung di kalkulator.** Tahap integrasi tiap
site berbeda: ada yang absensinya sudah lewat mesin, ada yang lemburnya
masih diketik HR. Dengan adapter, "sumbernya belum siap" berarti satu
angka nol beserta temuan yang menyebutkannya — bukan payroll yang tidak
bisa dijalankan sama sekali, dan bukan pula pencabangan `if` yang
tersebar di mesin hitung.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from django.db.models import Sum

ZERO = Decimal("0.00")


@dataclass
class PeriodFacts:
    """
    Angka satu pegawai untuk satu periode, apa adanya dari modul sumber.
    """

    attendance_days: Decimal = ZERO
    absent_days: Decimal = ZERO
    late_minutes: int = 0
    leave_days: Decimal = ZERO
    unpaid_leave_days: Decimal = ZERO
    overtime_hours: Decimal = ZERO

    # Jam lembur dipecah per tanggal, di samping totalnya.
    #
    # Dua-duanya dibawa karena tingkat pengali bisa dihitung per hari
    # lembur **atau** dari total sebulan, dan keduanya menghasilkan
    # angka yang jauh berbeda. Yang memilih perusahaan lewat
    # `OvertimeGroup.tier_basis`; adapter ini menyediakan bahan untuk
    # kedua jawaban supaya keputusan itu tidak perlu menunggu
    # perombakan.
    overtime_daily_hours: list = field(default_factory=list)

    # ------------------------------------------------------------------
    # Izin kehadiran (Attendance Permission)
    # ------------------------------------------------------------------
    #
    # Angka-angka ini menjawab satu pertanyaan yang sebelumnya tidak
    # bisa dijawab payroll sama sekali: **keterlambatan ini ada izinnya
    # atau tidak.** Sebelum modul izin ada, `late_minutes` cuma satu
    # angka, dan perusahaan yang membedakan keduanya harus memilah
    # sendiri dari daftar absensi.
    #
    # `permission_minutes` bukan jumlah dari `paid + unpaid`.
    # Selisihnya adalah menit yang perlakuannya `INFORMATION_ONLY` —
    # tercatat, tidak berpengaruh ke uang. Menyatukannya berarti
    # perusahaan yang belum menetapkan kebijakan tidak bisa dibedakan
    # dari yang menetapkan bayar.
    permission_minutes: int = 0
    paid_permission_minutes: int = 0
    unpaid_permission_minutes: int = 0

    excused_late_minutes: int = 0
    unauthorized_late_minutes: int = 0

    excused_early_leave_minutes: int = 0
    unauthorized_early_leave_minutes: int = 0

    excused_absence_days: Decimal = ZERO
    unauthorized_absence_days: Decimal = ZERO

    # Tanggal yang berstatus alpa di absensi tapi sudah ditutup dokumen
    # cuti yang sah. Dihitung supaya "kenapa alpanya tiga hari tapi yang
    # dipotong cuma satu" punya jawaban berupa angka, bukan berupa
    # pembacaan ulang kode.
    absence_covered_by_leave: int = 0

    # BT-3 — hari tugas Business Trip yang dibayar, **terpisah** dari
    # `attendance_days` (hadir fisik). Satu hari tidak pernah masuk dua
    # wadah: hari dengan tap fisik tetap hadir. Isinya baris berstatus
    # `business_trip` plus baris alpa yang tanggalnya diizinkan
    # perjalanan yang disetujui (perjalanan disetujui sesudah penutup
    # hari menulis alpa) — yang kedua juga dicatat terpisah supaya
    # "kenapa alpa ini tidak dipotong" punya angka.
    business_trip_days: Decimal = ZERO
    absence_covered_by_business_trip: int = 0

    # Baris `business_trip` yang tanggalnya tidak diizinkan dokumen
    # Business Trip mana pun (diketik tangan / data lama). Tetap
    # dihitung hari dinas, tapi dilaporkan sebagai temuan.
    manual_business_trip_days: int = 0

    # Ada tidaknya baris absensi sama sekali. Nol hari hadir karena
    # datanya belum diimpor dan nol hari hadir karena orangnya memang
    # tidak masuk sebulan penuh adalah dua keadaan yang sangat berbeda,
    # dan hanya yang pertama yang layak jadi peringatan.
    has_attendance_source: bool = False
    has_overtime_source: bool = False

    notes: list[str] = field(default_factory=list)

    @property
    def paid_leave_days(self) -> Decimal:
        """
        Cuti yang **tidak** memotong gaji. Turunan, bukan kolom: satu
        angka yang bisa dihitung dari dua angka lain tidak boleh
        disimpan terpisah, karena yang ketiga akan menyimpang.
        """
        return self.leave_days - self.unpaid_leave_days


class PayrollSourceService:
    """
    Pembaca data sumber. Classmethod-only, tanpa keadaan.
    """

    # ------------------------------------------------------------------
    # Kepegawaian
    # ------------------------------------------------------------------

    @staticmethod
    def working_days(*, employee, start_date: date, end_date: date) -> int:
        """
        Hari kerja pegawai ini di dalam rentang, menurut sumber yang
        sudah dipakai modul Cuti — bukan Senin–Jumat yang ditanam di
        sini.

        `LeaveDayCalculator.count_working_days` sudah menjawab persis
        pertanyaan ini dan sudah dipakai untuk memotong saldo cuti,
        lengkap dengan urutan resolusinya: baris roster yang benar-benar
        terbit → siklus roster → `EmploymentAssignment.working_calendar`
        → `WorkCalendar` default company+location → `WorkCalendar`
        company → Senin–Jumat sebagai pilihan terakhir. Menulis versi
        kedua di Payroll berarti dua jawaban untuk satu pertanyaan, dan
        yang satu akan salah tanpa ada yang tahu — pegawai roster
        4-2 yang cutinya dihitung 4 hari akan digaji seolah kerjanya 5.

        Dipanggil dari service, **bukan dari mesin hitung**: yang masuk
        ke `CalculationInput` tetap angka jadi.
        """
        from apps.hr.api.leave.calculator import LeaveDayCalculator

        if end_date < start_date:
            return 0

        return LeaveDayCalculator.count_working_days(
            employee,
            start_date,
            end_date,
        )

    @classmethod
    def eligible_employees(
        cls,
        *,
        company,
        start_date: date,
        end_date: date,
        branch=None,
        location=None,
        department=None,
        section=None,
        payroll_group=None,
        base_queryset=None,
    ):
        """
        Pegawai yang sah dibayar untuk periode ini.

        Empat syarat, dan semuanya diperiksa terhadap **periode**, bukan
        terhadap hari ini: pegawai yang berhenti tanggal 20 tetap harus
        dibayar untuk 1–20, dan pegawai yang baru masuk bulan depan
        tidak boleh ikut.

        1. sudah bergabung sebelum periode berakhir (`join_date`);
        2. belum berhenti sebelum periode dimulai (`termination_date`);
        3. penempatan organisasinya cocok dengan cakupan run;
        4. punya `PayrollAssignment` yang berlaku — diperiksa terpisah
           oleh validasi supaya yang belum punya tetap **muncul** di
           daftar dengan temuan, bukan menghilang tanpa penjelasan.
        """
        from apps.hr.models import Employee

        queryset = base_queryset if base_queryset is not None else Employee.objects.all()

        queryset = (
            queryset
            .filter(is_deleted=False, is_active=True)
            .filter(organization__company=company)
            .select_related(
                "employment",
                "organization",
                "organization__company",
                "organization__branch",
                "organization__location",
                "organization__division",
                "organization__department",
                "organization__section",
                "organization__position",
                "organization__cost_center",
            )
        )

        if branch is not None:
            queryset = queryset.filter(organization__branch=branch)

        if location is not None:
            queryset = queryset.filter(organization__location=location)

        if department is not None:
            queryset = queryset.filter(organization__department=department)

        if section is not None:
            queryset = queryset.filter(organization__section=section)

        # `join_date` kosong tidak membuang orangnya. Data lama yang
        # tanggal masuknya belum diisi tetap harus terbayar; yang
        # menagihnya adalah temuan validasi, bukan filter yang diam.
        queryset = queryset.exclude(employment__join_date__gt=end_date)
        queryset = queryset.exclude(employment__termination_date__lt=start_date)

        if payroll_group is not None:
            # Payroll group pegawai ada di `PayrollAssignment`, bukan di
            # kartu pegawai. Yang belum punya assignment sengaja **ikut
            # tersaring masuk** — mereka justru yang harus dilihat HR.
            # `.distinct()` wajib: syaratnya menembus relasi banyak
            # (`payroll_assignments`), dan tanpa itu pegawai dengan dua
            # baris riwayat payroll muncul dua kali di daftar run.
            queryset = queryset.filter(
                models_q_payroll_group(payroll_group),
            ).distinct()

        return queryset.order_by("employee_number")

    @classmethod
    def current_assignment(cls, *, employee, on_date: date):
        """
        `PayrollAssignment` yang berlaku pada tanggal tertentu.

        Dicari lewat rentang efektif, **bukan** lewat `is_current`:
        payroll periode lalu yang dihitung ulang hari ini harus memakai
        gaji yang berlaku waktu itu, bukan gaji hasil kenaikan minggu
        kemarin.
        """
        from apps.hr.models import PayrollAssignment

        return (
            PayrollAssignment.objects
            .filter(
                employee=employee,
                is_deleted=False,
                effective_from__lte=on_date,
            )
            .filter(
                models_q_effective_to(on_date),
            )
            .select_related(
                "payroll_group",
                "salary_grade",
                "salary_level",
                "tax_status",
                "overtime_group",
                "allowance_template",
                "deduction_template",
                "payroll_policy",
                "currency",
            )
            .order_by("-effective_from")
            .first()
        )

    # ------------------------------------------------------------------
    # Absensi, cuti, lembur
    # ------------------------------------------------------------------

    @classmethod
    def collect(
        cls,
        *,
        employee,
        start_date: date,
        end_date: date,
        payroll_policy_id=None,
    ) -> PeriodFacts:
        """
        `payroll_policy_id` dioper pemanggil dari **snapshot barisnya**
        (`PayrollRunEmployee.payroll_policy_id`), bukan dari assignment
        pegawai hari ini: run Juni yang dihitung ulang di bulan Agustus
        harus memakai aturan izin yang berlaku bulan Juni. Kosong =
        aturan yang tidak menyebut kebijakan mana pun.
        """
        facts = PeriodFacts()

        # Cuti dibaca **lebih dulu**, dan urutannya bukan selera.
        # Dokumen cuti yang sudah sah mengalahkan baris absensi mentah
        # pada tanggal yang sama; supaya absensi bisa mengecualikan
        # tanggal itu, tanggal-tanggalnya harus sudah diketahui.
        leave_dates = cls._collect_leave(
            facts=facts,
            employee=employee,
            start_date=start_date,
            end_date=end_date,
        )
        cls._collect_attendance(
            facts=facts,
            employee=employee,
            start_date=start_date,
            end_date=end_date,
            leave_dates=leave_dates,
            trip_dates=cls._business_trip_dates(
                employee=employee,
                start_date=start_date,
                end_date=end_date,
            ),
            payroll_policy_id=payroll_policy_id,
        )
        cls._collect_overtime(
            facts=facts,
            employee=employee,
            start_date=start_date,
            end_date=end_date,
        )

        return facts

    @classmethod
    def _collect_attendance(
        cls,
        *,
        facts,
        employee,
        start_date,
        end_date,
        leave_dates=None,
        trip_dates=None,
        payroll_policy_id=None,
    ):
        """
        Hari hadir, hari dinas, dan hari alpa dalam rentang.

        **Business Trip bukan hadir fisik (BT-3).** Baris `business_trip`
        masuk `business_trip_days`, bukan `attendance_days`; tunjangan
        per hari hadir tidak ikut, gaji bulanan tidak dipotong, upah
        harian menambahkannya lewat `_payable_days`. Baris alpa pada
        tanggal yang diizinkan perjalanan juga jadi hari dinas —
        urutannya cuti → izin sehari penuh → perjalanan → alpa, sama
        dengan penutup hari.

        **Tanggal yang sudah ditutup dokumen cuti tidak dihitung alpa**,
        dan ini yang mencegah potongan ganda. Baris absensi terbit
        otomatis dari mesin sidik jari: pegawai yang cutinya disetujui
        tetap meninggalkan baris berstatus alpa di tanggal itu, karena
        ia memang tidak menempelkan jari. Menghitung dua-duanya berarti
        satu hari tidak masuk memotong gaji dua kali — sekali sebagai
        cuti tidak dibayar, sekali lagi sebagai alpa.

        Yang menang dokumen cutinya, bukan barisnya, karena dokumen itu
        keputusan orang sementara baris absensi cuma jejak alat. Cuti
        **dibayar** ikut menang: pegawai yang cutinya disetujui tidak
        boleh dipotong hanya karena mesin absensinya tidak tahu.
        """
        from apps.hr.models.attendance import AttendanceStatus, EmployeeAttendance
        from apps.hr.models.attendance.permission import (
            AttendancePermissionType,
        )
        from apps.payroll.services.permission_rule import (
            PayrollPermissionRuleService,
        )

        covered = leave_dates or frozenset()
        on_trip = trip_dates or frozenset()
        manual_trip_days = 0

        rules = PayrollPermissionRuleService.load(
            company_id=getattr(
                getattr(employee, "organization", None), "company_id", None,
            ),
            payroll_policy_id=payroll_policy_id,
        )

        def rule(kind):
            return PayrollPermissionRuleService.resolve(rules, kind)

        rows = (
            EmployeeAttendance.objects
            .filter(
                employee=employee,
                is_deleted=False,
                work_date__gte=start_date,
                work_date__lte=end_date,
            )
            .values_list(
                "status",
                "late_minutes",
                "work_date",
                "excused_late_minutes",
                "early_leave_minutes",
                "excused_early_leave_minutes",
                "permission_minutes",
                "is_excused_absence",
                "check_in",
            )
        )

        # Hadir **fisik**. `BUSINESS_TRIP` sengaja tidak di sini (BT-3).
        present_statuses = {
            AttendanceStatus.PRESENT,
            AttendanceStatus.LATE,
            AttendanceStatus.REMOTE,
        }

        count = 0

        for (
            status,
            late_minutes,
            work_date,
            excused_late,
            early_leave_minutes,
            excused_early,
            permission_minutes,
            is_excused_absence,
            check_in,
        ) in rows:
            count += 1

            late_minutes = int(late_minutes or 0)
            early_leave_minutes = int(early_leave_minutes or 0)
            excused_late = min(int(excused_late or 0), late_minutes)
            excused_early = min(int(excused_early or 0), early_leave_minutes)
            permission_minutes = int(permission_minutes or 0)

            # Tap fisik menang atas perjalanan: baris dinas yang punya jam
            # masuk (tap yang jadwalnya tidak bisa dihitung resolver)
            # tetap hari hadir, bukan hari dinas.
            if status in present_statuses or (
                status == AttendanceStatus.BUSINESS_TRIP
                and check_in is not None
            ):
                facts.attendance_days += Decimal("1")

            elif status == AttendanceStatus.BUSINESS_TRIP:
                facts.business_trip_days += Decimal("1")

                # Status yang diketik tangan tanpa dokumen perjalanan
                # tetap dihormati (keputusan orang), tapi disebut.
                if work_date not in on_trip:
                    manual_trip_days += 1

            elif status == AttendanceStatus.ABSENT:
                if work_date in covered:
                    # Cuti menang atas izin **dan** atas baris alpanya.
                    # Satu tanggal yang tertutup dua dokumen sekaligus
                    # dipotong sekali, dan yang dipilih dokumen yang
                    # memotong saldo — kalau tidak, hari yang sama
                    # mengurangi gaji lewat dua jalur.
                    facts.absence_covered_by_leave += 1

                elif is_excused_absence:
                    # Izin sehari penuh menang atas perjalanan: orangnya
                    # tidak sedang bertugas hari itu.
                    facts.excused_absence_days += Decimal("1")

                    # **Hanya perlakuan PAID yang mengeluarkannya dari
                    # potongan.** UNPAID memang dipotong, dan
                    # INFORMATION_ONLY mempertahankan perilaku sebelum
                    # modul izin ada — tabel aturan yang kosong tidak
                    # boleh menggeser satu rupiah pun.
                    if not rule(AttendancePermissionType.FULL_DAY).is_paid:
                        facts.absent_days += Decimal("1")

                elif work_date in on_trip:
                    # Perjalanan disetujui sesudah penutup hari menulis
                    # alpa. Barisnya tidak ditulis ulang (sama seperti
                    # cuti); payroll menutupnya berdasarkan tanggal.
                    facts.business_trip_days += Decimal("1")
                    facts.absence_covered_by_business_trip += 1

                else:
                    facts.absent_days += Decimal("1")
                    facts.unauthorized_absence_days += Decimal("1")

            facts.late_minutes += late_minutes

            facts.excused_late_minutes += excused_late
            facts.unauthorized_late_minutes += late_minutes - excused_late

            facts.excused_early_leave_minutes += excused_early
            facts.unauthorized_early_leave_minutes += (
                early_leave_minutes - excused_early
            )

            # Menit izin, dipecah dibayar/tidak per jenisnya. Dinilai
            # **per hari**, bukan atas totalnya sebulan: ambang "izin
            # keluar lebih dari 2 jam" adalah aturan tentang satu
            # kejadian, dan menilainya atas total sebulan membuat
            # empat izin setengah jam ikut terpotong.
            for kind, minutes in (
                (AttendancePermissionType.LATE_ARRIVAL, excused_late),
                (AttendancePermissionType.EARLY_LEAVE, excused_early),
                (
                    AttendancePermissionType.TEMPORARY_OUT,
                    permission_minutes,
                ),
            ):
                if not minutes:
                    continue

                paid, unpaid = rule(kind).split(minutes)

                facts.permission_minutes += minutes
                facts.paid_permission_minutes += paid
                facts.unpaid_permission_minutes += unpaid

        facts.has_attendance_source = count > 0

        facts.manual_business_trip_days = manual_trip_days

        if facts.permission_minutes or facts.excused_absence_days:
            unset = [
                kind
                for kind in (
                    AttendancePermissionType.LATE_ARRIVAL,
                    AttendancePermissionType.EARLY_LEAVE,
                    AttendancePermissionType.TEMPORARY_OUT,
                    AttendancePermissionType.FULL_DAY,
                )
                if kind not in rules
            ]

            if unset:
                # Temuan, bukan kegagalan. Perlakuan bawaannya
                # `INFORMATION_ONLY` — angkanya terbaca, uangnya tidak
                # bergerak — dan tanpa temuan ini keadaan itu tidak bisa
                # dibedakan dari kebijakan yang memang memilih begitu.
                facts.notes.append(
                    "Izin kehadiran tercatat tapi Payroll Permission "
                    "Rule belum diisi untuk: "
                    + ", ".join(sorted(unset))
                    + ". Perlakuannya sementara Information Only — "
                    "angkanya dilaporkan, gaji tidak berubah."
                )

    @staticmethod
    def _business_trip_dates(*, employee, start_date, end_date) -> frozenset:
        """
        Tanggal yang diizinkan Business Trip yang disetujui (BT-3).

        Satu fungsi dengan penutup hari presensi — presensi dan gaji
        tidak boleh berbeda pendapat soal satu tanggal.
        """
        from apps.hr.api.business_trip.coverage import business_trip_days

        return frozenset(
            business_trip_days([employee], start_date, end_date)
            .get(employee.pk, {})
        )

    @classmethod
    def _collect_leave(cls, *, facts, employee, start_date, end_date):
        """
        Hari cuti dalam periode, dipisah dibayar/tidak lewat
        `PayrollLeaveRule`.

        Cuti yang **melintasi batas periode** dihitung proporsional per
        hari yang benar-benar jatuh di dalam rentang — memakai
        `total_days` apa adanya berarti cuti 10 hari yang dimulai
        tanggal 28 memotong sepuluh hari dari bulan ini dan sepuluh
        lagi dari bulan depan.

        Mengembalikan himpunan tanggal yang ditutup dokumen cuti sah —
        dibayar maupun tidak — supaya pembacaan absensi bisa
        mengecualikannya.
        """
        from apps.hr.models import EmployeeLeave
        from apps.hr.models.leave import LEAVE_DEDUCTING_STATUSES

        from apps.payroll.models import PayrollLeaveRule

        unpaid_type_ids = set(
            PayrollLeaveRule.objects
            .filter(is_deleted=False, is_active=True, is_unpaid=True)
            .values_list("leave_type_id", flat=True)
        )

        rows = (
            EmployeeLeave.objects
            .filter(
                employee=employee,
                is_deleted=False,
                status__in=LEAVE_DEDUCTING_STATUSES,
                start_date__lte=end_date,
                end_date__gte=start_date,
            )
            .values(
                "leave_type_id",
                "start_date",
                "end_date",
                "total_days",
                "is_half_day",
            )
        )

        covered: set = set()

        for row in rows:
            overlap_start = max(row["start_date"], start_date)
            overlap_end = min(row["end_date"], end_date)

            span_days = (row["end_date"] - row["start_date"]).days + 1
            overlap_days = (overlap_end - overlap_start).days + 1

            total = Decimal(row["total_days"] or 0)

            if span_days > 0 and overlap_days < span_days:
                total = (
                    total * Decimal(overlap_days) / Decimal(span_days)
                ).quantize(Decimal("0.01"))

            facts.leave_days += total

            if row["leave_type_id"] in unpaid_type_ids:
                facts.unpaid_leave_days += total

            # Tanggal yang ditutup dokumen ini, dipakai absensi untuk
            # tidak menghitung alpa dua kali. Cuti setengah hari ikut
            # menutup tanggalnya penuh: potongan setengah hari sudah
            # dihitung dari `total_days`, dan menambahkan potongan alpa
            # sehari penuh di atasnya justru yang salah.
            covered.update(
                overlap_start + timedelta(days=offset)
                for offset in range(overlap_days)
            )

        return covered

    @classmethod
    def _collect_overtime(cls, *, facts, employee, start_date, end_date):
        from apps.hr.models import EmployeeOvertime
        from apps.hr.models.overtime import OvertimeStatus

        # Hanya lembur yang **sah menurut modul sumber**: berbayar dan
        # sudah tercatat/disetujui. Payroll tidak menghitung sendiri
        # jam mana yang lembur dari jam masuk-keluar, dan tidak
        # membuat alur persetujuan kedua — jam yang sah ditentukan
        # HR/Attendance, harga per jamnya ditentukan di sini.
        rows = (
            EmployeeOvertime.objects
            .filter(
                employee=employee,
                is_deleted=False,
                is_paid=True,
                status__in=[
                    OvertimeStatus.RECORDED,
                    OvertimeStatus.APPROVED,
                ],
                work_date__gte=start_date,
                work_date__lte=end_date,
            )
            .values("work_date")
            .annotate(minutes=Sum("duration_minutes"))
            .order_by("work_date")
        )

        total_minutes = 0

        for row in rows:
            minutes = int(row["minutes"] or 0)

            if minutes <= 0:
                continue

            total_minutes += minutes

            # Dijumlahkan per tanggal lebih dulu, baru diubah ke jam:
            # dua lembur di hari yang sama adalah **satu** hari lembur,
            # dan menghitungnya sebagai dua akan memberi tarif jam
            # pertama dua kali pada perusahaan yang bertingkat harian.
            facts.overtime_daily_hours.append(
                (Decimal(minutes) / Decimal("60")).quantize(
                    Decimal("0.01"),
                ),
            )

        facts.has_overtime_source = total_minutes > 0

        # Total dihitung dari menit, bukan dari penjumlahan jam yang
        # sudah dibulatkan — dua kali 100 menit adalah 3,33 jam, bukan
        # 1,67 + 1,67 = 3,34.
        facts.overtime_hours = (
            Decimal(total_minutes) / Decimal("60")
        ).quantize(Decimal("0.01"))


def models_q_payroll_group(payroll_group):
    """
    Pegawai yang payroll group-nya cocok **atau** belum punya assignment.

    Ditulis sebagai fungsi, bukan inline, supaya niatnya terbaca: yang
    belum dikonfigurasi sengaja ikut masuk daftar, karena merekalah yang
    harus diperbaiki HR sebelum Finalize.
    """
    from django.db.models import Q

    return (
        Q(payroll_assignments__payroll_group=payroll_group,
          payroll_assignments__is_deleted=False)
        | Q(payroll_assignments__isnull=True)
    )


def models_q_effective_to(on_date: date):
    from django.db.models import Q

    return Q(effective_to__isnull=True) | Q(effective_to__gte=on_date)
