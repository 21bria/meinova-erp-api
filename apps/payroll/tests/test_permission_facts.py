"""
Fakta izin kehadiran yang sampai ke Payroll.

Dua hal yang dijaga berkas ini, dan yang kedua justru yang paling
penting:

1. **Payroll bisa membedakan keterlambatan karena izin dari
   keterlambatan tanpa izin.** Sebelum modul izin ada, `late_minutes`
   cuma satu angka.

2. **Tabel aturan yang kosong tidak menggeser satu rupiah pun.**
   Perlakuan bawaannya `INFORMATION_ONLY` — angkanya dilaporkan, gaji
   tidak berubah. Itu bukan kelalaian: "disetujui = dibayar" persis
   yang dilarang spesifikasinya, dan bawaan apa pun selain ini membuat
   payroll yang sudah berjalan bergeser hanya karena sebuah tabel lahir.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django_tenants.test.cases import TenantTestCase

from apps.administration.models import (
    Company,
    Location,
    WorkCalendar,
)
from apps.administration.models.references.hr_attendance import Shift
from apps.hr.api.attendance.services import EmployeeAttendanceService
from apps.hr.api.attendance_permission.services import (
    AttendancePermissionService,
)
from apps.hr.models import (
    AttendancePermissionStatus,
    AttendancePermissionType,
    AttendanceStatus,
    Employee,
    EmploymentAssignment,
    OrganizationAssignment,
)
from apps.payroll.models import (
    PayrollPermissionRule,
    PermissionPayTreatment,
)
from apps.payroll.services.sources import PayrollSourceService


WALL = ZoneInfo("Asia/Jakarta")

JOIN_DATE = date(2020, 1, 6)

# Selasa.
WORK_DATE = date(2026, 9, 8)

PERIOD_START = date(2026, 9, 1)
PERIOD_END = date(2026, 9, 30)


def at(day: date, hour: int, minute: int = 0) -> datetime:
    """Jam dinding Asia/Jakarta pada sebuah tanggal."""
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=WALL)


class PermissionFactsTestCase(TenantTestCase):
    _counter = 0

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "permission-facts"
        tenant.name = "Permission Facts"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.shift = Shift.objects.create(
            code="PFC-DAY",
            name="Day 08-17",
            start_time=time(8, 0),
            end_time=time(17, 0),
        )

    def setUp(self):
        """
        **Satu company per test, bukan satu per kelas.**

        `TenantTestCase` tidak melakukan rollback per-test, jadi baris
        `PayrollPermissionRule` yang dibuat satu test tetap hidup di
        test berikutnya — dan aturan yang bocor mengubah persis angka
        yang diuji test sebelahnya, dengan hasil yang bergantung pada
        urutan eksekusi. Cakupan aturan adalah company; company yang
        berbeda karena itu sekaligus jadi pemisahnya.
        """
        super().setUp()

        type(self)._counter += 1

        suffix = type(self)._counter

        self.company = Company.objects.create(
            code=f"PFC{suffix}",
            name=f"Facts Co {suffix}",
        )

        self.location = Location.objects.create(
            company=self.company,
            code=f"PFC{suffix}-HO",
            name="Head Office",
        )

        self.calendar = WorkCalendar.objects.create(
            company=self.company,
            code=f"PFC{suffix}-OFFICE",
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

    # ------------------------------------------------------------------

    def make_employee(self) -> Employee:
        type(self)._counter += 1

        employee = Employee.objects.create(
            employee_number=f"PFC{type(self)._counter:04d}",
            first_name="Facts",
            last_name=f"Employee {type(self)._counter}",
        )

        OrganizationAssignment.objects.create(
            employee=employee,
            company=self.company,
            location=self.location,
            organization_effective_date=JOIN_DATE,
        )

        EmploymentAssignment.objects.create(
            employee=employee,
            join_date=JOIN_DATE,
            working_calendar=self.calendar,
            shift=self.shift,
        )

        return Employee.objects.get(pk=employee.pk)

    def approve(self, permission):
        AttendancePermissionService._set_status(
            permission=permission,
            status=AttendancePermissionStatus.APPROVED,
        )

        AttendancePermissionService.recalculate_attendance(
            permission=permission,
        )

        return permission

    def make_permission(self, employee, **kwargs):
        kwargs.setdefault("date", WORK_DATE)
        kwargs.setdefault("reason", "Urusan keluarga")

        return AttendancePermissionService.create(
            data={"employee": employee, **kwargs},
        )

    def make_attendance(self, employee, *, work_date=WORK_DATE, **kwargs):
        data = {
            "employee": employee,
            "work_date": work_date,
            "shift": self.shift,
            "scheduled_check_in": at(work_date, 8, 0),
            "scheduled_check_out": at(work_date, 17, 0),
            **kwargs,
        }

        return EmployeeAttendanceService.create(data=data)

    def facts_for(self, employee):
        return PayrollSourceService.collect(
            employee=employee,
            start_date=PERIOD_START,
            end_date=PERIOD_END,
        )

    def rule(self, permission_type, treatment, **kwargs):
        return PayrollPermissionRule.objects.create(
            company=self.company,
            permission_type=permission_type,
            treatment=treatment,
            **kwargs,
        )

    # ------------------------------------------------------------------
    # Fakta dasar
    # ------------------------------------------------------------------

    def test_late_with_and_without_permission_are_reported_separately(self):
        employee = self.make_employee()

        permission = self.make_permission(
            employee,
            permission_type=AttendancePermissionType.LATE_ARRIVAL,
            end_time=time(10, 0),
        )

        self.approve(permission)

        self.make_attendance(
            employee,
            check_in=at(WORK_DATE, 10, 30),
            check_out=at(WORK_DATE, 17, 0),
        )

        facts = self.facts_for(employee)

        # Total keterlambatannya utuh, dan pecahannya menjumlah kembali
        # ke total itu. Kalau tidak, laporan "telat tanpa izin" dan
        # kolom `late_minutes` di layar akan berbeda tanpa ada yang
        # bisa menjelaskan selisihnya.
        self.assertEqual(facts.late_minutes, 150)
        self.assertEqual(facts.excused_late_minutes, 120)
        self.assertEqual(facts.unauthorized_late_minutes, 30)

    def test_early_leave_is_split_the_same_way(self):
        employee = self.make_employee()

        permission = self.make_permission(
            employee,
            permission_type=AttendancePermissionType.EARLY_LEAVE,
            start_time=time(15, 0),
        )

        self.approve(permission)

        self.make_attendance(
            employee,
            check_in=at(WORK_DATE, 8, 0),
            check_out=at(WORK_DATE, 14, 0),
        )

        facts = self.facts_for(employee)

        self.assertEqual(facts.excused_early_leave_minutes, 120)
        self.assertEqual(facts.unauthorized_early_leave_minutes, 60)

    def test_excused_and_unauthorized_absence_are_counted_apart(self):
        employee = self.make_employee()

        permission = self.make_permission(
            employee,
            permission_type=AttendancePermissionType.FULL_DAY,
        )

        self.approve(permission)

        self.make_attendance(employee, status=AttendanceStatus.ABSENT)

        other_day = WORK_DATE + timedelta(days=1)

        self.make_attendance(
            employee,
            work_date=other_day,
            status=AttendanceStatus.ABSENT,
        )

        facts = self.facts_for(employee)

        self.assertEqual(facts.excused_absence_days, Decimal("1"))
        self.assertEqual(facts.unauthorized_absence_days, Decimal("1"))

    # ------------------------------------------------------------------
    # Perlakuan payroll
    # ------------------------------------------------------------------

    def test_without_a_rule_nothing_moves(self):
        """
        Bawaan `INFORMATION_ONLY`: angkanya dilaporkan, potongannya
        persis seperti sebelum modul izin ada.
        """
        employee = self.make_employee()

        permission = self.make_permission(
            employee,
            permission_type=AttendancePermissionType.FULL_DAY,
        )

        self.approve(permission)

        self.make_attendance(employee, status=AttendanceStatus.ABSENT)

        facts = self.facts_for(employee)

        self.assertEqual(facts.excused_absence_days, Decimal("1"))

        # Tetap terpotong — belum ada yang memutuskan sebaliknya.
        self.assertEqual(facts.absent_days, Decimal("1"))

        # Dan keadaan itu **disebutkan**, bukan didiamkan.
        self.assertTrue(
            any("Payroll Permission Rule" in note for note in facts.notes),
            facts.notes,
        )

    def test_paid_full_day_permission_removes_the_deduction(self):
        employee = self.make_employee()

        self.rule(
            AttendancePermissionType.FULL_DAY,
            PermissionPayTreatment.PAID,
        )

        permission = self.make_permission(
            employee,
            permission_type=AttendancePermissionType.FULL_DAY,
        )

        self.approve(permission)

        self.make_attendance(employee, status=AttendanceStatus.ABSENT)

        facts = self.facts_for(employee)

        self.assertEqual(facts.excused_absence_days, Decimal("1"))
        self.assertEqual(facts.absent_days, Decimal("0.00"))

    def test_unpaid_full_day_permission_keeps_the_deduction(self):
        employee = self.make_employee()

        self.rule(
            AttendancePermissionType.FULL_DAY,
            PermissionPayTreatment.UNPAID,
        )

        permission = self.make_permission(
            employee,
            permission_type=AttendancePermissionType.FULL_DAY,
        )

        self.approve(permission)

        self.make_attendance(employee, status=AttendanceStatus.ABSENT)

        facts = self.facts_for(employee)

        self.assertEqual(facts.excused_absence_days, Decimal("1"))
        self.assertEqual(facts.absent_days, Decimal("1"))

    def test_paid_temporary_out_is_reported_as_paid_minutes(self):
        employee = self.make_employee()

        self.rule(
            AttendancePermissionType.TEMPORARY_OUT,
            PermissionPayTreatment.PAID,
        )

        permission = self.make_permission(
            employee,
            permission_type=AttendancePermissionType.TEMPORARY_OUT,
            start_time=time(13, 0),
            end_time=time(15, 0),
        )

        self.approve(permission)

        self.make_attendance(
            employee,
            check_in=at(WORK_DATE, 8, 0),
            check_out=at(WORK_DATE, 17, 0),
        )

        facts = self.facts_for(employee)

        self.assertEqual(facts.permission_minutes, 120)
        self.assertEqual(facts.paid_permission_minutes, 120)
        self.assertEqual(facts.unpaid_permission_minutes, 0)

    def test_threshold_only_deducts_the_excess(self):
        """
        "Izin keluar > 2 jam tidak dibayar" memotong **kelebihannya**,
        bukan seluruh durasinya. Memotong dua jam pertama juga membuat
        ambangnya jadi hukuman: orang yang izin 2 jam 1 menit dipotong
        sama dengan yang izin sehari.
        """
        employee = self.make_employee()

        self.rule(
            AttendancePermissionType.TEMPORARY_OUT,
            PermissionPayTreatment.PAID,
            unpaid_over_minutes=120,
        )

        permission = self.make_permission(
            employee,
            permission_type=AttendancePermissionType.TEMPORARY_OUT,
            start_time=time(13, 0),
            end_time=time(16, 0),
        )

        self.approve(permission)

        self.make_attendance(
            employee,
            check_in=at(WORK_DATE, 8, 0),
            check_out=at(WORK_DATE, 17, 0),
        )

        facts = self.facts_for(employee)

        self.assertEqual(facts.permission_minutes, 180)
        self.assertEqual(facts.paid_permission_minutes, 120)
        self.assertEqual(facts.unpaid_permission_minutes, 60)

    def test_information_only_reports_minutes_without_splitting_them(self):
        """
        `permission_minutes` bukan jumlah `paid + unpaid`. Selisihnya
        adalah menit yang perlakuannya belum ditetapkan — dan itu
        keadaan yang harus bisa dibedakan dari "sudah diputuskan tidak
        dibayar".
        """
        employee = self.make_employee()

        self.rule(
            AttendancePermissionType.TEMPORARY_OUT,
            PermissionPayTreatment.INFORMATION_ONLY,
        )

        permission = self.make_permission(
            employee,
            permission_type=AttendancePermissionType.TEMPORARY_OUT,
            start_time=time(13, 0),
            end_time=time(15, 0),
        )

        self.approve(permission)

        self.make_attendance(
            employee,
            check_in=at(WORK_DATE, 8, 0),
            check_out=at(WORK_DATE, 17, 0),
        )

        facts = self.facts_for(employee)

        self.assertEqual(facts.permission_minutes, 120)
        self.assertEqual(facts.paid_permission_minutes, 0)
        self.assertEqual(facts.unpaid_permission_minutes, 0)

    def test_leave_still_wins_over_permission(self):
        """
        Satu tanggal yang tertutup cuti **dan** izin dipotong sekali,
        dan yang dipilih dokumen yang memotong saldo. Kalau tidak, hari
        yang sama mengurangi gaji lewat dua jalur.
        """
        from apps.administration.models import LeaveType
        from apps.hr.models import EmployeeLeave, LeaveStatus

        employee = self.make_employee()

        leave_type = LeaveType.objects.create(
            code=f"PFC-LV{employee.pk}",
            name="Cuti Tahunan",
        )

        EmployeeLeave.objects.create(
            employee=employee,
            leave_type=leave_type,
            start_date=WORK_DATE,
            end_date=WORK_DATE,
            total_days=Decimal("1.0"),
            status=LeaveStatus.APPROVED,
        )

        permission = self.make_permission(
            employee,
            permission_type=AttendancePermissionType.FULL_DAY,
        )

        self.approve(permission)

        self.make_attendance(employee, status=AttendanceStatus.ABSENT)

        facts = self.facts_for(employee)

        self.assertEqual(facts.absence_covered_by_leave, 1)
        self.assertEqual(facts.absent_days, Decimal("0.00"))
        self.assertEqual(facts.excused_absence_days, Decimal("0.00"))

    # ------------------------------------------------------------------
    # Resolusi berjenjang aturan
    # ------------------------------------------------------------------

    def test_company_rule_beats_the_global_one(self):
        from apps.payroll.services.permission_rule import (
            PayrollPermissionRuleService,
        )

        global_rule = PayrollPermissionRule.objects.create(
            company=None,
            permission_type=AttendancePermissionType.FULL_DAY,
            treatment=PermissionPayTreatment.UNPAID,
        )

        # Baris global tidak terikat company mana pun, jadi ia satu-
        # satunya di berkas ini yang bisa bocor ke test lain.
        # Dibersihkan di sini, bukan diandalkan pada rollback yang
        # memang tidak ada pada `TenantTestCase`.
        self.addCleanup(global_rule.delete)

        self.rule(
            AttendancePermissionType.FULL_DAY,
            PermissionPayTreatment.PAID,
        )

        rules = PayrollPermissionRuleService.load(company_id=self.company.pk)

        resolved = PayrollPermissionRuleService.resolve(
            rules,
            AttendancePermissionType.FULL_DAY,
        )

        self.assertTrue(resolved.is_paid)

    def test_unknown_type_falls_back_to_information_only(self):
        from apps.payroll.services.permission_rule import (
            PayrollPermissionRuleService,
        )

        resolved = PayrollPermissionRuleService.resolve(
            {},
            AttendancePermissionType.LATE_ARRIVAL,
        )

        self.assertTrue(resolved.is_information_only)
