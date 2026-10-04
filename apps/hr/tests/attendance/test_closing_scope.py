"""
Cakupan pegawai pada penutup hari presensi.

Yang dikunci di sini dua hal yang gampang tertukar:

**Cakupan** — pegawai mana yang dikerjakan perintahnya. Itu yang
ditambahkan `close(employees=...)`, dan ia hanya boleh **menyempitkan**.

**Kelayakan** — siapa yang sebenarnya punya kewajiban presensi. Itu
tetap milik Feature Applicability, tanggal masuk/berhenti, hari
pemulihan, dan segmen roster — dan tidak satu pun dari itu boleh
berubah karena pemanggil menyebut daftar pegawai.

Test di berkas ini karena itu dibagi dua: separuh membuktikan cakupan
bekerja, separuh lagi membuktikan kelayakan **tidak** ikut bergeser.

Satu lagi yang dikunci: cakupan kosong yang disebut bukan berarti
"semua". Itu bukan kehalusan gaya — penutup hari yang salah cakupan
menerbitkan tuduhan mangkir untuk seluruh tenant tanpa berbunyi apa
pun, dan yang menemukannya biasanya orang yang gajinya dipotong.
"""

from __future__ import annotations

from datetime import date, timedelta

from apps.core.testing.tenant import ReusableTenantTestCase

from apps.administration.models import Company, Location, RosterPolicy
from apps.administration.models.references.hr import EmployeeGroup
from apps.administration.models.references.hr_attendance import Shift
from apps.hr.api.attendance.closing import AttendanceClosingService
from apps.hr.api.attendance.schedule import scheduled_work_days
from apps.hr.models import (
    Employee,
    EmployeeAttendance,
    EmployeeShiftAssignment,
    EmploymentAssignment,
    OrganizationAssignment,
    RosterSegmentType,
    RotationPeriod,
    RotationPeriodType,
    ShiftAssignmentKind,
    ShiftAssignmentLayer,
    SiteRotation,
)
from apps.hr.models.attendance.choices import AttendanceStatus


# Senin 2026-03-02 s/d Minggu 2026-03-15. Dipatok, bukan dihitung dari
# hari ini: test yang jendelanya bergerak jadi merah karena kalender
# lewat, bukan karena kodenya berubah.
WEEK_START = date(2026, 3, 2)
WEEK_END = date(2026, 3, 13)


class AttendanceClosingScopeTests(ReusableTenantTestCase):
    # Pilot TEST-ISO-HR-0B. Lihat catatan yang sama di
    # `apps/hr/tests/leave/test_opening_balance.py`: pondasinya wajib
    # idempoten karena schema-nya dipakai ulang.
    reusable_schema_name = "fast_attendance"

    _counter = 0

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "closing-scope"
        tenant.name = "Closing Scope"

    @classmethod
    def build_baseline(cls):
        cls.company, _ = Company.objects.get_or_create(
            code="CSC",
            is_deleted=False,
            defaults={"name": "Closing Scope Co"},
        )

        cls.site, _ = Location.objects.get_or_create(
            code="CSC-SITE",
            is_deleted=False,
            defaults={"company": cls.company, "name": "Site"},
        )

        cls.roster_policy, _ = RosterPolicy.objects.get_or_create(
            code="CSC-6-2",
            is_deleted=False,
            defaults={
                "company": cls.company,
                "location": cls.site,
                "name": "Roster 6:2",
                "cycle_work_days": 42,
                "cycle_off_days": 14,
                "default_travel_out_days": 1,
                "default_travel_in_days": 1,
                "rolling_horizon_months": 12,
            },
        )

        cls.office_shift, _ = Shift.objects.get_or_create(
            code="CSC-OFFICE",
            is_deleted=False,
            defaults={
                "name": "Office",
                "start_time": "09:00",
                "end_time": "17:00",
            },
        )

        cls.board_group, _ = EmployeeGroup.objects.get_or_create(
            code="CSC-BOARD",
            is_deleted=False,
            defaults={"name": "Board", "attendance_applicable": False},
        )

    # ------------------------------------------------------------------
    # Pabrik data
    # ------------------------------------------------------------------

    @classmethod
    def make_employee(
        cls,
        *,
        number: str | None = None,
        roster: bool = False,
        group=None,
        join_date: date | None = None,
        termination_date: date | None = None,
        is_active: bool = True,
    ) -> Employee:
        cls._counter += 1

        employee = Employee.objects.create(
            employee_number=number or f"CSC{cls._counter:04d}",
            first_name="Scope",
            last_name=f"Employee {cls._counter}",
            is_active=is_active,
        )

        OrganizationAssignment.objects.create(
            employee=employee,
            company=cls.company,
            location=cls.site,
            organization_effective_date=date(2026, 1, 1),
        )

        EmploymentAssignment.objects.create(
            employee=employee,
            join_date=join_date or date(2025, 1, 1),
            termination_date=termination_date,
            employee_group=group,
            roster_policy=cls.roster_policy if roster else None,
            shift=cls.office_shift,
        )

        return Employee.objects.get(pk=employee.pk)

    def make_segment(
        self,
        employee,
        *,
        segment_type,
        start: date,
        end: date,
        sequence: int = 1,
    ) -> RotationPeriod:
        rotation = SiteRotation.objects.create(
            employee=employee,
            company=self.company,
            location=self.site,
            cycle_work_days=(end - start).days + 1,
            cycle_off_days=14,
            cycle_travel_days=0,
            start_date=start,
            cycle_count=1,
        )

        return RotationPeriod.objects.create(
            rotation=rotation,
            employee=employee,
            sequence=sequence,
            period_type=RotationPeriodType.WORK,
            segment_type=segment_type,
            start_date=start,
            end_date=end,
            total_days=(end - start).days + 1,
            cycle_number=1,
        )

    def make_rest_day(self, employee, day: date) -> EmployeeShiftAssignment:
        return EmployeeShiftAssignment.objects.create(
            employee=employee,
            shift=None,
            kind=ShiftAssignmentKind.REST,
            layer=ShiftAssignmentLayer.BASELINE,
            start_date=day,
            end_date=day,
            reason="Jeda minimum antar shift",
        )

    # ------------------------------------------------------------------
    # Util
    # ------------------------------------------------------------------

    @staticmethod
    def close(**kwargs):
        return AttendanceClosingService.close(
            start=WEEK_START,
            end=WEEK_END,
            **kwargs,
        )

    @staticmethod
    def rows(employee):
        return (
            EmployeeAttendance.objects
            .filter(employee=employee, is_deleted=False)
            .order_by("work_date")
        )

    def absent_days(self, employee) -> list[date]:
        return list(
            self.rows(employee)
            .filter(status=AttendanceStatus.ABSENT)
            .values_list("work_date", flat=True)
        )

    # ==================================================================
    # Cakupan
    # ==================================================================

    def test_scoped_closing_processes_selected_employees(self):
        selected = self.make_employee()

        result = self.close(employees=[selected.id])

        self.assertEqual(result["employees"], 1)
        self.assertEqual(result["absent"], 10)
        self.assertEqual(len(self.absent_days(selected)), 10)

    def test_scoped_closing_leaves_unselected_employees_untouched(self):
        selected = self.make_employee()
        other = self.make_employee()

        self.close(employees=[selected.id])

        self.assertEqual(self.rows(selected).count(), 10)
        self.assertEqual(
            self.rows(other).count(),
            0,
            "Pegawai di luar cakupan tidak boleh disentuh sama sekali.",
        )

    def test_scoped_closing_cannot_create_trial_lineage_attendance(self):
        """
        Silsilah uji tetap nol walau mesinnya menjadwalkan mereka.

        `is_active=False` **tidak** menghentikan penjadwalan — itu
        keterbatasan yang disengaja dan tidak diubah di sini. Justru
        karena itu cakupan eksplisit jadi satu-satunya yang memisahkan
        keduanya: keduanya duduk di company dan lokasi yang sama, jadi
        `--company`/`--location` tidak bisa.
        """
        canonical = self.make_employee(number="CSC-HO-1")
        trial = self.make_employee(number="TRL-CSC-1", is_active=False)

        # Buktikan dulu bahwa mesinnya memang menjadwalkan si silsilah
        # uji — kalau tidak, test ini lulus karena alasan yang salah.
        self.assertEqual(
            len(scheduled_work_days(trial, WEEK_START, WEEK_END)),
            10,
        )

        self.close(employees=[canonical.id])

        self.assertEqual(self.rows(canonical).count(), 10)
        self.assertEqual(self.rows(trial).count(), 0)

    def test_empty_explicit_scope_is_not_global_scope(self):
        employee = self.make_employee()

        result = self.close(employees=[])

        self.assertEqual(result["employees"], 0)
        self.assertEqual(result["absent"], 0)
        self.assertEqual(result["scanned"], 0)
        self.assertEqual(self.rows(employee).count(), 0)

    def test_unscoped_closing_behaviour_is_unchanged(self):
        first = self.make_employee()
        second = self.make_employee()

        result = self.close()

        self.assertEqual(result["employees"], 2)
        self.assertEqual(result["absent"], 20)
        self.assertEqual(self.rows(first).count(), 10)
        self.assertEqual(self.rows(second).count(), 10)

    def test_duplicate_ids_do_not_duplicate_work(self):
        employee = self.make_employee()

        result = self.close(
            employees=[employee.id, employee.id, employee.id],
        )

        self.assertEqual(result["employees"], 1)
        self.assertEqual(result["scanned"], 10)
        self.assertEqual(result["absent"], 10)
        self.assertEqual(self.rows(employee).count(), 10)

    def test_scope_narrows_but_never_widens_company_filter(self):
        """
        Cakupan pegawai tidak bisa dipakai menembus `company`.

        Kalau ia melebar, perintah yang dibatasi ke satu perusahaan
        diam-diam menulis ke perusahaan lain begitu ada yang mengoper
        id-nya.
        """
        other_company = Company.objects.create(
            code="CSC-B",
            name="Other Co",
        )

        outsider = self.make_employee()

        OrganizationAssignment.objects.filter(employee=outsider).update(
            company=other_company,
        )

        result = self.close(
            company=self.company.id,
            employees=[outsider.id],
        )

        self.assertEqual(result["employees"], 0)
        self.assertEqual(self.rows(outsider).count(), 0)

    def test_scope_accepts_employee_instances(self):
        employee = self.make_employee()

        result = self.close(employees=[employee])

        self.assertEqual(result["employees"], 1)
        self.assertEqual(self.rows(employee).count(), 10)

    # ==================================================================
    # Kelayakan — yang TIDAK boleh bergeser
    # ==================================================================

    def test_absence_only_for_scheduled_work_days(self):
        employee = self.make_employee()

        self.close(employees=[employee.id])

        days = self.absent_days(employee)

        self.assertEqual(len(days), 10)
        self.assertTrue(
            all(day.weekday() < 5 for day in days),
            "Akhir pekan bukan hari terjadwal pegawai kantor.",
        )

    def test_recovery_day_does_not_become_absent(self):
        employee = self.make_employee(roster=True)

        self.make_segment(
            employee,
            segment_type=RosterSegmentType.WORK,
            start=WEEK_START,
            end=WEEK_START + timedelta(days=6),
        )

        recovery = WEEK_START + timedelta(days=3)

        self.make_rest_day(employee, recovery)

        self.close(employees=[employee.id])

        days = self.absent_days(employee)

        self.assertEqual(len(days), 6)
        self.assertNotIn(recovery, days)

    def test_field_break_does_not_become_absent(self):
        employee = self.make_employee(roster=True)

        self.make_segment(
            employee,
            segment_type=RosterSegmentType.WORK,
            start=WEEK_START,
            end=WEEK_START + timedelta(days=2),
        )

        self.make_segment(
            employee,
            segment_type=RosterSegmentType.FIELD_BREAK,
            start=WEEK_START + timedelta(days=3),
            end=WEEK_START + timedelta(days=9),
            sequence=2,
        )

        self.close(employees=[employee.id])

        self.assertEqual(len(self.absent_days(employee)), 3)

    def test_travel_days_do_not_become_absent(self):
        employee = self.make_employee(roster=True)

        self.make_segment(
            employee,
            segment_type=RosterSegmentType.TRAVEL_OUT,
            start=WEEK_START,
            end=WEEK_START,
        )

        self.make_segment(
            employee,
            segment_type=RosterSegmentType.WORK,
            start=WEEK_START + timedelta(days=1),
            end=WEEK_START + timedelta(days=3),
            sequence=2,
        )

        self.make_segment(
            employee,
            segment_type=RosterSegmentType.TRAVEL_IN,
            start=WEEK_START + timedelta(days=4),
            end=WEEK_START + timedelta(days=4),
            sequence=3,
        )

        self.close(employees=[employee.id])

        days = self.absent_days(employee)

        self.assertEqual(len(days), 3)
        self.assertNotIn(WEEK_START, days)
        self.assertNotIn(WEEK_START + timedelta(days=4), days)

    def test_post_termination_dates_do_not_become_absent(self):
        termination = WEEK_START + timedelta(days=2)

        employee = self.make_employee(termination_date=termination)

        self.close(employees=[employee.id])

        days = self.absent_days(employee)

        self.assertEqual(len(days), 3)
        self.assertEqual(max(days), termination)

    def test_pre_join_dates_do_not_become_absent(self):
        join = WEEK_START + timedelta(days=7)

        employee = self.make_employee(join_date=join)

        self.close(employees=[employee.id])

        days = self.absent_days(employee)

        self.assertTrue(days)
        self.assertEqual(min(days), join)

    def test_board_employees_do_not_become_absent(self):
        board = self.make_employee(group=self.board_group)
        ordinary = self.make_employee()

        result = self.close(employees=[board.id, ordinary.id])

        self.assertEqual(
            result["employees"],
            1,
            "Pegawai tanpa kewajiban presensi tidak ikut diproses.",
        )
        self.assertEqual(self.rows(board).count(), 0)
        self.assertEqual(self.rows(ordinary).count(), 10)

    def test_existing_rows_are_never_overwritten(self):
        employee = self.make_employee()

        EmployeeAttendance.objects.create(
            employee=employee,
            company=self.company,
            location=self.site,
            work_date=WEEK_START,
            status=AttendanceStatus.PRESENT,
        )

        self.close(employees=[employee.id])

        kept = self.rows(employee).get(work_date=WEEK_START)

        self.assertEqual(kept.status, AttendanceStatus.PRESENT)
        self.assertEqual(len(self.absent_days(employee)), 9)

    def test_scoped_closing_is_repeatable(self):
        employee = self.make_employee()

        first = self.close(employees=[employee.id])
        second = self.close(employees=[employee.id])

        self.assertEqual(first["absent"], 10)
        self.assertEqual(second["absent"], 0)
        self.assertEqual(self.rows(employee).count(), 10)
