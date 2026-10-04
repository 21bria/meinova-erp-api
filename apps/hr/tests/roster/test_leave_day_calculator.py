"""
Mengunci perilaku `LeaveDayCalculator` yang berlaku sekarang.

Test regresi fase 0. Yang paling penting di berkas ini bukan cabang HO,
melainkan tiga test bertanda **REGRESI ROSTER** di bagian bawah: ketiganya
merekam bagaimana hari cuti pegawai roster dihitung **sebelum** segmen
travel dimaterialisasi.

Hari travel hari ini adalah celah kalender tanpa baris `RotationPeriod`,
jadi cuti yang menyeberanginya membuat `resolve_rotation_work_days()`
mengembalikan `None` dan perhitungannya jatuh ke rumus modulo
`resolve_roster()` — yang menghitung siklus sebagai `work + off` **tanpa**
travel. Begitu segmen travel dibuat, rentangnya tertutup penuh dan cabang
baris-nyata yang dipakai, sehingga angkanya berubah.

Ketiga test itu memang akan gagal saat perubahan itu dikerjakan. Itu
tujuannya: selisihnya muncul sebagai test yang sengaja diperbarui, bukan
sebagai angka yang diam-diam berbeda di kartu cuti orang.

Tiap test memakai pegawainya sendiri, jadi hasilnya tidak bergantung pada
apakah data antar-test ikut dibersihkan.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django_tenants.test.cases import TenantTestCase

from apps.administration.models import (
    Company,
    Holiday,
    Location,
    RosterCrew,
    WorkCalendar,
    WorkSchedule,
)
from apps.hr.api.leave.calculator import LeaveDayCalculator
from apps.hr.models import (
    Employee,
    EmploymentAssignment,
    OrganizationAssignment,
    RotationPeriod,
    RotationPeriodStatus,
    RotationPeriodType,
    SiteRotation,
)


class LeaveDayCalculatorTestCase(TenantTestCase):
    """Fondasi bersama: satu company, satu site, dua kalender kerja."""

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "roster-test"
        tenant.name = "Roster Test"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.company = Company.objects.create(
            code="TST",
            name="Tenant Test",
        )

        cls.site = Location.objects.create(
            company=cls.company,
            code="GBE",
            name="Gebe",
        )

        # Kalender kantor: Senin–Jumat.
        cls.office_calendar = WorkCalendar.objects.create(
            company=cls.company,
            code="OFFICE",
            name="Office Mon-Fri",
            monday=True,
            tuesday=True,
            wednesday=True,
            thursday=True,
            friday=True,
            saturday=False,
            sunday=False,
            is_default=True,
        )

        # Kalender operasional site: tujuh hari kerja. Inilah kalender
        # yang diam-diam diwarisi pegawai kantor yang location-nya diisi
        # site — jebakan yang sudah tercatat di CLAUDE.md.
        cls.site_calendar = WorkCalendar.objects.create(
            company=cls.company,
            location=cls.site,
            code="SITE",
            name="Site 7 Days",
            monday=True,
            tuesday=True,
            wednesday=True,
            thursday=True,
            friday=True,
            saturday=True,
            sunday=True,
            is_default=True,
        )

        cls.roster_schedule = WorkSchedule.objects.create(
            code="ROS62",
            name="Roster 6:2",
            schedule_type=WorkSchedule.ScheduleType.ROSTER,
            cycle_work_days=42,
            cycle_off_days=14,
        )

        cls.crew = RosterCrew.objects.create(
            company=cls.company,
            location=cls.site,
            code="CREW-A",
            name="Crew A",
            work_schedule=cls.roster_schedule,
            cycle_start_date=date(2026, 8, 1),
        )

    # ------------------------------------------------------------------
    # Pabrik data
    # ------------------------------------------------------------------

    _counter = 0

    @classmethod
    def make_employee(
        cls,
        *,
        location=None,
        calendar=None,
        crew=None,
        roster_start_override=None,
    ) -> Employee:
        """
        Satu pegawai lengkap dengan penempatan dan data kepegawaiannya.

        Tiap test memanggilnya sendiri supaya tidak ada test yang
        bergantung pada baris yang dibuat test lain.
        """
        cls._counter += 1

        employee = Employee.objects.create(
            employee_number=f"TST{cls._counter:04d}",
            first_name="Test",
            last_name=f"Employee {cls._counter}",
        )

        OrganizationAssignment.objects.create(
            employee=employee,
            company=cls.company,
            location=location,
            organization_effective_date=date(2026, 1, 1),
        )

        EmploymentAssignment.objects.create(
            employee=employee,
            working_calendar=calendar,
            roster_crew=crew,
            roster_start_override=roster_start_override,
            work_schedule=(
                crew.work_schedule
                if crew is not None
                else None
            ),
        )

        # Relasi dibaca lewat `employee.employment` / `.organization`,
        # dan instance yang sudah di tangan tidak memuatnya sendiri.
        return Employee.objects.get(pk=employee.pk)

    @classmethod
    def make_rotation(
        cls,
        employee,
        *,
        start_date,
        work_days=42,
        off_days=14,
        travel_days=0,
        cycle_count=3,
    ) -> SiteRotation:
        """
        Dokumen roster beserta barisnya, dibuat langsung dari generator
        supaya bentuknya sama persis dengan yang dihasilkan aplikasi.
        """
        from apps.hr.api.site_rotation.generator import (
            RotationPeriodGenerator,
        )

        rotation = SiteRotation.objects.create(
            employee=employee,
            company=cls.company,
            location=cls.site,
            roster_crew=cls.crew,
            cycle_work_days=work_days,
            cycle_off_days=off_days,
            cycle_travel_days=travel_days,
            cycle_count=cycle_count,
            start_date=start_date,
        )

        rows = RotationPeriodGenerator.build(
            start_date=start_date,
            work_days=work_days,
            off_days=off_days,
            cycle_count=cycle_count,
            travel_days=travel_days,
        )

        for row in rows:
            RotationPeriod.objects.create(
                rotation=rotation,
                employee=employee,
                **row,
            )

        return rotation


class OfficeCalendarTests(LeaveDayCalculatorTestCase):
    """Cabang non-roster: hari kerja dari `WorkCalendar` + `Holiday`."""

    def test_weekend_is_not_deducted(self):
        """
        14–18 Agustus 2026 = 5 hari kalender, tapi Sabtu dan Minggu bukan
        hari kerja, jadi yang terpotong 3 hari.
        """
        employee = self.make_employee(calendar=self.office_calendar)

        self.assertEqual(
            LeaveDayCalculator.calculate(
                employee=employee,
                start=date(2026, 8, 14),
                end=date(2026, 8, 18),
            ),
            Decimal("3"),
        )

    def test_holiday_is_not_deducted(self):
        """
        Contoh yang tercatat di CLAUDE.md: rentang yang sama memotong 2
        hari begitu 17 Agustus terdaftar sebagai hari libur.
        """
        employee = self.make_employee(calendar=self.office_calendar)

        Holiday.objects.create(
            company=self.company,
            date=date(2026, 8, 17),
            code="HUT-RI-2026",
            name="Hari Kemerdekaan",
            is_national=True,
        )

        self.assertEqual(
            LeaveDayCalculator.calculate(
                employee=employee,
                start=date(2026, 8, 14),
                end=date(2026, 8, 18),
            ),
            Decimal("2"),
        )

    def test_falls_back_to_monday_friday_without_calendar(self):
        """
        Pegawai tanpa kalender dan tanpa company default tetap dihitung
        Senin–Jumat, bukan tujuh hari.
        """
        employee = Employee.objects.create(
            employee_number="TST-NOCAL",
            first_name="No",
            last_name="Calendar",
        )

        EmploymentAssignment.objects.create(employee=employee)

        employee = Employee.objects.get(pk=employee.pk)

        self.assertEqual(
            LeaveDayCalculator.calculate(
                employee=employee,
                start=date(2026, 8, 14),
                end=date(2026, 8, 18),
            ),
            Decimal("3"),
        )

    def test_calendar_with_every_day_off_falls_back(self):
        """
        Kalender yang seluruh harinya dimatikan hampir pasti salah isi.
        Memakainya apa adanya membuat setiap cuti memotong nol hari.
        """
        broken = WorkCalendar.objects.create(
            company=self.company,
            code="BROKEN",
            name="All Days Off",
            monday=False,
            tuesday=False,
            wednesday=False,
            thursday=False,
            friday=False,
            saturday=False,
            sunday=False,
        )

        employee = self.make_employee(calendar=broken)

        self.assertEqual(
            LeaveDayCalculator.calculate(
                employee=employee,
                start=date(2026, 8, 14),
                end=date(2026, 8, 18),
            ),
            Decimal("3"),
        )

    def test_site_calendar_wins_over_company_default(self):
        """
        Kalender ditentukan **location**, bukan jenis pegawai. Pegawai
        kantor yang location-nya diisi site mewarisi kalender operasional
        tujuh hari — dan cuti seminggunya memotong 7, bukan 5.

        Bukan perilaku yang diinginkan, tapi perilaku yang berlaku;
        jalan keluarnya mengisi `working_calendar` eksplisit.
        """
        employee = self.make_employee(location=self.site)

        self.assertEqual(
            LeaveDayCalculator.calculate(
                employee=employee,
                start=date(2026, 8, 14),
                end=date(2026, 8, 18),
            ),
            Decimal("5"),
        )

    def test_explicit_calendar_beats_location(self):
        employee = self.make_employee(
            location=self.site,
            calendar=self.office_calendar,
        )

        self.assertEqual(
            LeaveDayCalculator.calculate(
                employee=employee,
                start=date(2026, 8, 14),
                end=date(2026, 8, 18),
            ),
            Decimal("3"),
        )

    def test_location_specific_holiday_is_scoped(self):
        """
        Libur khusus site tidak memotong cuti pegawai yang tidak
        ditempatkan di site itu.
        """
        Holiday.objects.create(
            company=self.company,
            location=self.site,
            date=date(2026, 8, 18),
            code="SITE-OFF",
            name="Site Maintenance",
        )

        office = self.make_employee(calendar=self.office_calendar)

        self.assertEqual(
            LeaveDayCalculator.calculate(
                employee=office,
                start=date(2026, 8, 14),
                end=date(2026, 8, 18),
            ),
            Decimal("3"),
        )


class CalculateGuardTests(LeaveDayCalculatorTestCase):
    """Pagar `calculate()` — yang mengembalikan None, dan setengah hari."""

    def test_half_day_short_circuits(self):
        employee = self.make_employee(calendar=self.office_calendar)

        self.assertEqual(
            LeaveDayCalculator.calculate(
                employee=employee,
                start=date(2026, 8, 14),
                end=date(2026, 8, 18),
                is_half_day=True,
            ),
            Decimal("0.5"),
        )

    def test_missing_argument_returns_none(self):
        employee = self.make_employee(calendar=self.office_calendar)

        self.assertIsNone(
            LeaveDayCalculator.calculate(
                employee=None,
                start=date(2026, 8, 14),
                end=date(2026, 8, 18),
            ),
        )

        self.assertIsNone(
            LeaveDayCalculator.calculate(
                employee=employee,
                start=None,
                end=date(2026, 8, 18),
            ),
        )

    def test_end_before_start_returns_none(self):
        employee = self.make_employee(calendar=self.office_calendar)

        self.assertIsNone(
            LeaveDayCalculator.calculate(
                employee=employee,
                start=date(2026, 8, 18),
                end=date(2026, 8, 14),
            ),
        )

    def test_absurd_span_returns_none(self):
        """Rentang lebih dari 366 hari pasti salah ketik tahun."""
        employee = self.make_employee(calendar=self.office_calendar)

        self.assertIsNone(
            LeaveDayCalculator.calculate(
                employee=employee,
                start=date(2026, 1, 1),
                end=date(2027, 6, 1),
            ),
        )


class RosterFormulaTests(LeaveDayCalculatorTestCase):
    """
    Cabang roster **tanpa** dokumen jadwal: rumus modulo dari jangkar
    crew.
    """

    def test_leave_inside_work_block_deducts_every_calendar_day(self):
        """
        Akhir pekan dan hari libur nasional tidak dikecualikan untuk
        pegawai roster — rosternya sendiri yang jadi kalender.
        """
        employee = self.make_employee(location=self.site, crew=self.crew)

        Holiday.objects.create(
            company=self.company,
            date=date(2026, 8, 17),
            code="HUT-RI-ROSTER",
            name="Hari Kemerdekaan",
            is_national=True,
        )

        self.assertEqual(
            LeaveDayCalculator.calculate(
                employee=employee,
                start=date(2026, 8, 14),
                end=date(2026, 8, 18),
            ),
            Decimal("5"),
        )

    def test_leave_inside_off_block_deducts_nothing(self):
        """
        `total_days = 0` itu sah, bukan error: pegawai roster yang
        mengambil cuti saat blok off-nya tidak kehilangan hari kerja apa
        pun.

        Jangkar 1 Agustus, pola 42/14 → blok kerja 1 Ags–11 Sep, blok off
        12–25 Sep.
        """
        employee = self.make_employee(location=self.site, crew=self.crew)

        self.assertEqual(
            LeaveDayCalculator.calculate(
                employee=employee,
                start=date(2026, 9, 14),
                end=date(2026, 9, 20),
            ),
            Decimal("0"),
        )

    def test_leave_straddling_the_block_boundary(self):
        """
        8–15 September: 11 September hari terakhir blok kerja, jadi yang
        terpotong hanya 8–11 = 4 hari.
        """
        employee = self.make_employee(location=self.site, crew=self.crew)

        self.assertEqual(
            LeaveDayCalculator.calculate(
                employee=employee,
                start=date(2026, 9, 8),
                end=date(2026, 9, 15),
            ),
            Decimal("4"),
        )

    def test_roster_start_override_wins_over_crew_anchor(self):
        """Itu arti kata "override"."""
        employee = self.make_employee(
            location=self.site,
            crew=self.crew,
            roster_start_override=date(2026, 8, 15),
        )

        # Jangkar digeser 14 hari, jadi blok kerja jadi 15 Ags–25 Sep dan
        # rentang yang tadinya nol hari kini penuh hari kerja.
        self.assertEqual(
            LeaveDayCalculator.calculate(
                employee=employee,
                start=date(2026, 9, 14),
                end=date(2026, 9, 20),
            ),
            Decimal("7"),
        )

    def test_dates_before_the_anchor_count_backwards(self):
        """
        Modulo Python non-negatif untuk pembagi positif, jadi jangkar
        tidak harus siklus pertama.
        """
        employee = self.make_employee(location=self.site, crew=self.crew)

        # 56 hari sebelum jangkar = awal blok kerja pada siklus
        # sebelumnya.
        self.assertEqual(
            LeaveDayCalculator.calculate(
                employee=employee,
                start=date(2026, 6, 6),
                end=date(2026, 6, 10),
            ),
            Decimal("5"),
        )

    def test_crew_without_cycle_pattern_is_not_a_roster(self):
        """
        Siklus tanpa hari off bukan roster; perhitungannya jatuh kembali
        ke kalender kerja.
        """
        weekly = WorkSchedule.objects.create(
            code="WEEKLY-NO-CYCLE",
            name="Weekly",
            schedule_type=WorkSchedule.ScheduleType.WEEKLY,
        )

        crew = RosterCrew.objects.create(
            company=self.company,
            code="CREW-EMPTY",
            name="Crew Without Pattern",
            work_schedule=weekly,
            cycle_start_date=date(2026, 8, 1),
        )

        employee = self.make_employee(
            crew=crew,
            calendar=self.office_calendar,
        )

        self.assertEqual(
            LeaveDayCalculator.calculate(
                employee=employee,
                start=date(2026, 8, 14),
                end=date(2026, 8, 18),
            ),
            Decimal("3"),
        )


class RotationPeriodTests(LeaveDayCalculatorTestCase):
    """
    Cabang roster **dengan** dokumen jadwal: baris yang benar-benar
    dijadwalkan menang atas rumusnya.
    """

    def test_scheduled_rows_win_over_the_formula(self):
        """
        Baris roster boleh digeser tangan, dan begitu digeser, rumusnya
        tidak lagi menggambarkan jadwal yang berlaku.
        """
        employee = self.make_employee(location=self.site, crew=self.crew)

        rotation = self.make_rotation(employee, start_date=date(2026, 8, 1))

        # Blok kerja pertama dipendekkan tangan: berakhir 8 September,
        # bukan 11.
        first = rotation.periods.order_by("sequence").first()
        first.end_date = date(2026, 9, 8)
        first.is_manual_override = True
        first.save(update_fields=["end_date", "is_manual_override"])

        second = rotation.periods.order_by("sequence")[1]
        second.start_date = date(2026, 9, 9)
        second.save(update_fields=["start_date"])

        # 8–15 September kini cuma menyisakan 8 September sebagai hari
        # kerja; rumus modulo akan menjawab 4.
        self.assertEqual(
            LeaveDayCalculator.calculate(
                employee=employee,
                start=date(2026, 9, 8),
                end=date(2026, 9, 15),
            ),
            Decimal("1"),
        )

    def test_range_outside_generated_rows_falls_back_to_formula(self):
        """
        Cuti yang separuhnya jatuh di luar periode yang sudah digenerate
        tidak boleh diam-diam dianggap hari off.
        """
        employee = self.make_employee(location=self.site, crew=self.crew)

        self.make_rotation(
            employee,
            start_date=date(2026, 8, 1),
            cycle_count=1,
        )

        # Dokumen berakhir 25 September; rentang ini melewatinya, jadi
        # perhitungannya jatuh ke rumus siklus.
        self.assertEqual(
            LeaveDayCalculator.calculate(
                employee=employee,
                start=date(2026, 9, 20),
                end=date(2026, 10, 5),
            ),
            Decimal("10"),
        )

    def test_cancelled_periods_are_ignored(self):
        employee = self.make_employee(location=self.site, crew=self.crew)

        rotation = self.make_rotation(employee, start_date=date(2026, 8, 1))

        rotation.periods.update(status=RotationPeriodStatus.CANCELLED)

        # Tanpa satu pun baris yang terpakai, perhitungannya kembali ke
        # rumus siklus — bukan nol.
        self.assertEqual(
            LeaveDayCalculator.calculate(
                employee=employee,
                start=date(2026, 8, 14),
                end=date(2026, 8, 18),
            ),
            Decimal("5"),
        )

    def test_soft_deleted_periods_are_ignored(self):
        employee = self.make_employee(location=self.site, crew=self.crew)

        rotation = self.make_rotation(employee, start_date=date(2026, 8, 1))

        rotation.periods.update(is_deleted=True)

        self.assertEqual(
            LeaveDayCalculator.calculate(
                employee=employee,
                start=date(2026, 8, 14),
                end=date(2026, 8, 18),
            ),
            Decimal("5"),
        )


class TravelGapRegressionTests(LeaveDayCalculatorTestCase):
    """
    **REGRESI ROSTER — akan sengaja diperbarui saat segmen travel
    dimaterialisasi.**

    Ketiga test di bawah merekam akibat dari hari travel yang hari ini
    tidak punya baris `RotationPeriod`. Lihat docstring modul.
    """

    def test_leave_crossing_a_travel_gap_falls_back_to_the_formula(self):
        """
        Jadwal 42/14 dengan 2 hari travel: blok kerja 1 Ags–11 Sep, lalu
        12 September adalah hari travel **tanpa baris**, blok off mulai
        13 September.

        Cuti 10–14 September menyeberangi celah itu, jadi
        `resolve_rotation_work_days()` menyerah dan rumus modulo yang
        menjawab. Rumus itu menghitung siklus 42+14 = 56 **tanpa**
        travel, sehingga jawabannya berbeda dari jadwal yang benar-benar
        tersimpan.
        """
        employee = self.make_employee(location=self.site, crew=self.crew)

        rotation = self.make_rotation(
            employee,
            start_date=date(2026, 8, 1),
            travel_days=2,
        )

        periods = list(rotation.periods.order_by("sequence"))

        # Bentuk yang direkam: blok kerja tutup 11 Sep, blok off baru
        # mulai 13 Sep — 12 Sep tidak dimiliki baris mana pun.
        self.assertEqual(periods[0].end_date, date(2026, 9, 11))
        self.assertEqual(periods[1].start_date, date(2026, 9, 13))

        # Rumus modulo menghitung 10 dan 11 September sebagai hari kerja
        # (offset 40 dan 41 dari 42), sisanya off.
        self.assertEqual(
            LeaveDayCalculator.calculate(
                employee=employee,
                start=date(2026, 9, 10),
                end=date(2026, 9, 14),
            ),
            Decimal("2"),
        )

    def test_formula_and_schedule_drift_apart_over_cycles(self):
        """
        Rumus modulo maju 56 hari per putaran sementara jadwal yang
        tersimpan maju 58 (42 + 14 + 2 travel), jadi keduanya makin
        berjauhan setiap siklus.

        Di siklus ketiga selisihnya sudah 4 hari, dan tidak ada satu
        layar pun yang memperlihatkannya.
        """
        employee = self.make_employee(location=self.site, crew=self.crew)

        rotation = self.make_rotation(
            employee,
            start_date=date(2026, 8, 1),
            travel_days=2,
        )

        anchor = date(2026, 8, 1)

        third_work = (
            rotation.periods
            .filter(period_type=RotationPeriodType.WORK)
            .order_by("sequence")[2]
        )

        # Jadwal tersimpan: 1 Ags + 2 × 58 = 25 November.
        self.assertEqual(third_work.start_date, date(2026, 11, 25))

        # Rumus modulo: 1 Ags + 2 × 56 = 21 November — empat hari lebih
        # awal, dan ia sudah menganggap tanggal itu hari kerja padahal
        # jadwalnya masih blok off.
        formula_start = date(2026, 11, 21)

        self.assertEqual((third_work.start_date - formula_start).days, 4)

        self.assertTrue(
            LeaveDayCalculator.is_roster_working_day(
                formula_start,
                anchor,
                42,
                14,
            ),
        )

        # Yang tersimpan untuk 21 November: masih blok off.
        self.assertEqual(
            rotation.periods
            .filter(
                start_date__lte=formula_start,
                end_date__gte=formula_start,
            )
            .values_list("period_type", flat=True)
            .first(),
            RotationPeriodType.OFF,
        )

    def test_leave_fully_inside_one_block_still_uses_the_rows(self):
        """
        Selama rentangnya tidak menyentuh celah travel, baris nyatalah
        yang dipakai — dan untuk cuti di dalam satu blok, jawabannya
        kebetulan sama dengan rumusnya.
        """
        employee = self.make_employee(location=self.site, crew=self.crew)

        self.make_rotation(
            employee,
            start_date=date(2026, 8, 1),
            travel_days=2,
        )

        self.assertEqual(
            LeaveDayCalculator.calculate(
                employee=employee,
                start=date(2026, 8, 14),
                end=date(2026, 8, 18),
            ),
            Decimal("5"),
        )
