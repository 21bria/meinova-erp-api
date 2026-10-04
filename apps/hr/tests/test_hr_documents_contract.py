"""
Kontrak tiga dokumen yang menjelaskan pengecualian presensi.

Yang dikunci di sini bukan angka data peragaan melainkan **aturan
bisnisnya**, dan tiga aturan itu yang paling gampang hilang tanpa
berbunyi:

1. **Saldo cuti adalah penjumlahan ulang, bukan penambahan.** Yang
   disetujui dan yang dicatat memotong; yang masih diajukan, masih
   draf, ditolak, atau dibatalkan tidak meninggalkan potongan apa pun.
   Kalau ini pecah, orang kehilangan jatah karena pernah mengajukan.

2. **Izin tidak menyentuh jam tap.** `late_minutes` tetap angka
   menurut mesin; yang ditulis izin cuma berapa bagiannya yang
   dimaafkan. Kalau ini pecah, "jam berapa sebenarnya dia datang" tidak
   punya jawaban lagi.

3. **Lembur yang tidak dibayar dan yang dibatalkan tidak dibaca
   payroll.** Kalau ini pecah, jam yang sudah diganti libur dibayar
   dua kali.

Plus satu perilaku yang paling sering disalahpahami: **cuti yang
disetujui tidak menulis ulang baris presensi yang sudah ada.** Hari
yang sudah terbit sebagai mangkir tetap mangkir; yang berubah
pembacaannya di lapisan fakta payroll. Penutup hari hanya menulis
`leave` untuk hari yang **belum punya baris**.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from django_tenants.test.cases import TenantTestCase

from apps.administration.models import Company, Location
from apps.administration.models.references.hr import LeaveType
from apps.administration.models.references.hr_attendance import Shift
from apps.administration.models.references.leave_policy import LeavePolicy
from apps.hr.api.attendance.closing import AttendanceClosingService
from apps.hr.api.attendance.permission_effect import (
    AttendancePermissionEffectService,
)
from apps.hr.api.attendance.services import EmployeeAttendanceService
from apps.hr.api.leave.services import EmployeeLeaveService
from apps.hr.api.overtime.services import EmployeeOvertimeService
from apps.hr.models import (
    AttendancePermission,
    Employee,
    EmployeeAttendance,
    EmployeeLeave,
    EmployeeOvertime,
    EmploymentAssignment,
    LeaveBalance,
    OrganizationAssignment,
)
from apps.hr.models.attendance.choices import AttendanceStatus
from apps.hr.models.attendance.permission import (
    AttendancePermissionStatus,
    AttendancePermissionType,
)
from apps.hr.models.leave import LeaveStatus
from apps.payroll.models.permission_rule import PermissionPayTreatment
from apps.payroll.services.permission_rule import ResolvedPermissionRule
from apps.payroll.services.sources import PayrollSourceService


WALL = ZoneInfo("Asia/Jakarta")

# Senin 2026-03-02 .. Jumat 2026-03-13. Dipatok, bukan dihitung dari
# hari ini: test yang jendelanya bergerak jadi merah karena kalender
# lewat, bukan karena kodenya berubah.
MONDAY = date(2026, 3, 2)


class HRDocumentContractTests(TenantTestCase):
    _counter = 0

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "hr-documents"
        tenant.name = "HR Documents"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.company = Company.objects.create(code="HDC", name="HR Doc Co")

        cls.site = Location.objects.create(
            company=cls.company, code="HDC-HO", name="Head Office",
        )

        cls.shift = Shift.objects.create(
            code="HDC-OFFICE", name="Office",
            start_time="09:00", end_time="17:00",
        )

        cls.annual = LeaveType.objects.create(
            code="HDC-ANNUAL", name="Cuti Tahunan",
        )

        cls.unpaid_type = LeaveType.objects.create(
            code="HDC-UNPAID", name="Cuti Tanpa Upah",
        )

        LeavePolicy.objects.create(
            leave_type=cls.annual,
            code="HDC-ANNUAL-STD",
            name="Cuti Tahunan",
            uses_balance=True,
            entitlement_days=Decimal("12.00"),
            eligible_after_months=0,
        )

        LeavePolicy.objects.create(
            leave_type=cls.unpaid_type,
            code="HDC-UNPAID-STD",
            name="Cuti Tanpa Upah",
            uses_balance=False,
            eligible_after_months=0,
        )

    # ------------------------------------------------------------------
    # Pabrik data
    # ------------------------------------------------------------------

    @classmethod
    def make_employee(cls, *, balance: Decimal | None = None) -> Employee:
        cls._counter += 1

        employee = Employee.objects.create(
            employee_number=f"HDC{cls._counter:04d}",
            first_name="Doc",
            last_name=f"Employee {cls._counter}",
        )

        OrganizationAssignment.objects.create(
            employee=employee,
            company=cls.company,
            location=cls.site,
            organization_effective_date=date(2025, 1, 1),
        )

        EmploymentAssignment.objects.create(
            employee=employee,
            join_date=date(2024, 1, 1),
            shift=cls.shift,
        )

        if balance is not None:
            LeaveBalance.objects.create(
                employee=employee,
                leave_type=cls.annual,
                year=MONDAY.year,
                opening_balance=balance,
            )

        return Employee.objects.get(pk=employee.pk)

    def make_leave(
        self,
        employee,
        *,
        start: date,
        end: date | None = None,
        status: str = LeaveStatus.RECORDED,
        leave_type=None,
        half_day: bool = False,
    ) -> EmployeeLeave:
        return EmployeeLeaveService.create(
            data={
                "employee": employee,
                "leave_type": leave_type or self.annual,
                "start_date": start,
                "end_date": end or start,
                "is_half_day": half_day,
                "status": status,
            },
        )

    def make_attendance(
        self,
        employee,
        *,
        work_date: date,
        check_in: time | None = time(9, 0),
        check_out: time | None = time(17, 0),
        status: str = AttendanceStatus.PRESENT,
    ) -> EmployeeAttendance:
        def stamp(value, day=work_date):
            if value is None:
                return None

            return datetime.combine(day, value).replace(tzinfo=WALL)

        return EmployeeAttendanceService.create(
            data={
                "employee": employee,
                "work_date": work_date,
                "status": status,
                "shift": self.shift,
                "scheduled_check_in": stamp(time(9, 0)),
                "scheduled_check_out": stamp(time(17, 0)),
                "check_in": stamp(check_in),
                "check_out": stamp(check_out),
            },
        )

    def make_permission(
        self,
        employee,
        *,
        work_date: date,
        permission_type: str,
        start_time: time | None = None,
        end_time: time | None = None,
        status: str = AttendancePermissionStatus.APPROVED,
    ) -> AttendancePermission:
        permission = AttendancePermission.objects.create(
            employee=employee,
            company=self.company,
            location=self.site,
            date=work_date,
            permission_type=permission_type,
            start_time=start_time,
            end_time=end_time,
            reason="Keperluan yang sudah disampaikan ke atasan.",
            status=status,
        )

        AttendancePermissionEffectService.recalculate_for_permission(
            permission=permission,
        )

        return permission

    def balance_of(self, employee) -> Decimal:
        row = LeaveBalance.objects.get(
            employee=employee, leave_type=self.annual, year=MONDAY.year,
        )

        return row.remaining

    def facts(self, employee, *, start: date, end: date):
        return PayrollSourceService.collect(
            employee=employee, start_date=start, end_date=end,
        )

    # ==================================================================
    # Cuti — saldo
    # ==================================================================

    def test_recorded_leave_consumes_balance(self):
        employee = self.make_employee(balance=Decimal("10.0"))

        self.make_leave(
            employee, start=MONDAY, end=MONDAY + timedelta(days=2),
            status=LeaveStatus.RECORDED,
        )

        self.assertEqual(self.balance_of(employee), Decimal("7.0"))

    def test_approved_leave_consumes_balance(self):
        employee = self.make_employee(balance=Decimal("10.0"))

        leave = self.make_leave(
            employee, start=MONDAY, status=LeaveStatus.DRAFT,
        )

        EmployeeLeaveService.set_status(
            instance=leave, status=LeaveStatus.APPROVED,
        )

        self.assertEqual(self.balance_of(employee), Decimal("9.0"))

    def test_submitted_leave_does_not_consume_balance(self):
        employee = self.make_employee(balance=Decimal("10.0"))

        leave = self.make_leave(
            employee, start=MONDAY, status=LeaveStatus.DRAFT,
        )

        EmployeeLeaveService.set_status(
            instance=leave, status=LeaveStatus.SUBMITTED,
        )

        self.assertEqual(self.balance_of(employee), Decimal("10.0"))

    def test_draft_leave_does_not_consume_balance(self):
        employee = self.make_employee(balance=Decimal("10.0"))

        self.make_leave(employee, start=MONDAY, status=LeaveStatus.DRAFT)

        self.assertEqual(self.balance_of(employee), Decimal("10.0"))

    def test_rejected_leave_does_not_consume_balance(self):
        employee = self.make_employee(balance=Decimal("10.0"))

        leave = self.make_leave(
            employee, start=MONDAY, status=LeaveStatus.DRAFT,
        )

        EmployeeLeaveService.set_status(
            instance=leave, status=LeaveStatus.SUBMITTED,
        )
        EmployeeLeaveService.set_status(
            instance=leave, status=LeaveStatus.REJECTED,
        )

        self.assertEqual(self.balance_of(employee), Decimal("10.0"))

    def test_cancelling_a_recorded_leave_restores_balance(self):
        employee = self.make_employee(balance=Decimal("10.0"))

        leave = self.make_leave(
            employee, start=MONDAY, end=MONDAY + timedelta(days=1),
            status=LeaveStatus.RECORDED,
        )

        self.assertEqual(self.balance_of(employee), Decimal("8.0"))

        EmployeeLeaveService.set_status(
            instance=leave, status=LeaveStatus.CANCELLED,
        )

        self.assertEqual(
            self.balance_of(employee),
            Decimal("10.0"),
            "Saldo tidak dikembalikan — pembatalan meninggalkan "
            "potongan yang tidak bisa dijelaskan ke pegawainya.",
        )

    def test_half_day_leave_consumes_half_a_day(self):
        employee = self.make_employee(balance=Decimal("10.0"))

        leave = self.make_leave(
            employee, start=MONDAY, status=LeaveStatus.RECORDED,
            half_day=True,
        )

        self.assertEqual(leave.total_days, Decimal("0.50"))
        self.assertEqual(self.balance_of(employee), Decimal("9.5"))

    # ==================================================================
    # Cuti — hubungannya dengan presensi
    # ==================================================================

    def test_closing_writes_leave_for_a_covered_day_without_a_row(self):
        employee = self.make_employee(balance=Decimal("10.0"))

        self.make_leave(
            employee, start=MONDAY, status=LeaveStatus.APPROVED,
        )

        AttendanceClosingService.close(
            start=MONDAY, end=MONDAY, employees=[employee.id],
        )

        row = EmployeeAttendance.objects.get(
            employee=employee, work_date=MONDAY, is_deleted=False,
        )

        self.assertEqual(row.status, AttendanceStatus.LEAVE)

    def test_closing_writes_absent_for_an_uncovered_day(self):
        employee = self.make_employee(balance=Decimal("10.0"))

        AttendanceClosingService.close(
            start=MONDAY, end=MONDAY, employees=[employee.id],
        )

        row = EmployeeAttendance.objects.get(
            employee=employee, work_date=MONDAY, is_deleted=False,
        )

        self.assertEqual(row.status, AttendanceStatus.ABSENT)

    def test_approved_leave_does_not_rewrite_an_existing_absent_row(self):
        """
        Perilaku yang paling sering disalahpahami, dikunci apa adanya.

        Baris mangkir yang sudah terbit **tetap** mangkir sesudah
        cutinya disetujui. Yang berubah pembacaannya di lapisan fakta
        payroll — dan itu memang tempat keputusannya, bukan di kolom
        status presensi.
        """
        employee = self.make_employee(balance=Decimal("10.0"))

        AttendanceClosingService.close(
            start=MONDAY, end=MONDAY, employees=[employee.id],
        )

        self.make_leave(
            employee, start=MONDAY, status=LeaveStatus.APPROVED,
        )

        AttendanceClosingService.close(
            start=MONDAY, end=MONDAY, employees=[employee.id],
        )

        row = EmployeeAttendance.objects.get(
            employee=employee, work_date=MONDAY, is_deleted=False,
        )

        self.assertEqual(row.status, AttendanceStatus.ABSENT)

        facts = self.facts(employee, start=MONDAY, end=MONDAY)

        self.assertEqual(facts.absence_covered_by_leave, 1)
        self.assertEqual(facts.absent_days, Decimal("0"))
        self.assertEqual(facts.leave_days, Decimal("1.00"))

    def test_unpaid_leave_reaches_payroll_as_unpaid(self):
        from apps.payroll.models import PayrollLeaveRule

        employee = self.make_employee()

        PayrollLeaveRule.objects.create(
            leave_type=self.unpaid_type, is_unpaid=True,
        )

        self.make_leave(
            employee, start=MONDAY, status=LeaveStatus.APPROVED,
            leave_type=self.unpaid_type,
        )

        facts = self.facts(employee, start=MONDAY, end=MONDAY)

        self.assertEqual(facts.leave_days, Decimal("1.00"))
        self.assertEqual(facts.unpaid_leave_days, Decimal("1.00"))
        self.assertEqual(facts.paid_leave_days, Decimal("0.00"))

    # ==================================================================
    # Izin Kehadiran
    # ==================================================================

    def test_permission_fully_excuses_a_small_lateness(self):
        employee = self.make_employee()

        row = self.make_attendance(
            employee, work_date=MONDAY, check_in=time(9, 18),
        )

        self.assertEqual(row.late_minutes, 18)

        self.make_permission(
            employee, work_date=MONDAY,
            permission_type=AttendancePermissionType.LATE_ARRIVAL,
            end_time=time(9, 20),
        )

        row.refresh_from_db()

        self.assertEqual(row.excused_late_minutes, 18)
        self.assertEqual(row.permission_state, "excused")

    def test_permission_partially_excuses_a_long_lateness(self):
        employee = self.make_employee()

        row = self.make_attendance(
            employee, work_date=MONDAY, check_in=time(11, 0),
        )

        self.assertEqual(row.late_minutes, 120)

        self.make_permission(
            employee, work_date=MONDAY,
            permission_type=AttendancePermissionType.LATE_ARRIVAL,
            end_time=time(10, 30),
        )

        row.refresh_from_db()

        # Datang 30 menit lewat batas yang diizinkan: sisanya tetap
        # tanpa izin.
        self.assertEqual(row.excused_late_minutes, 90)
        self.assertEqual(row.unauthorized_late_minutes, 30)
        self.assertEqual(row.permission_state, "partial")

    def test_two_permissions_explain_late_and_early_on_one_day(self):
        employee = self.make_employee()

        row = self.make_attendance(
            employee, work_date=MONDAY,
            check_in=time(9, 30), check_out=time(16, 0),
        )

        self.assertEqual(row.late_minutes, 30)
        self.assertEqual(row.early_leave_minutes, 60)

        self.make_permission(
            employee, work_date=MONDAY,
            permission_type=AttendancePermissionType.LATE_ARRIVAL,
            end_time=time(9, 35),
        )
        self.make_permission(
            employee, work_date=MONDAY,
            permission_type=AttendancePermissionType.EARLY_LEAVE,
            start_time=time(16, 0),
        )

        row.refresh_from_db()

        self.assertEqual(row.excused_late_minutes, 30)
        self.assertEqual(row.excused_early_leave_minutes, 60)
        self.assertEqual(row.permission_state, "excused")

    def test_full_day_permission_excuses_an_absence(self):
        employee = self.make_employee()

        row = self.make_attendance(
            employee, work_date=MONDAY,
            check_in=None, check_out=None,
            status=AttendanceStatus.ABSENT,
        )

        self.make_permission(
            employee, work_date=MONDAY,
            permission_type=AttendancePermissionType.FULL_DAY,
        )

        row.refresh_from_db()

        self.assertTrue(row.is_excused_absence)
        self.assertEqual(row.permission_state, "excused")
        self.assertEqual(
            row.status,
            AttendanceStatus.ABSENT,
            "Izin menjelaskan ketidakhadiran; ia tidak menghapusnya.",
        )

    def test_temporary_out_records_minutes_without_excusing_early_leave(self):
        employee = self.make_employee()

        row = self.make_attendance(
            employee, work_date=MONDAY, check_out=time(16, 45),
        )

        self.assertEqual(row.early_leave_minutes, 15)

        self.make_permission(
            employee, work_date=MONDAY,
            permission_type=AttendancePermissionType.TEMPORARY_OUT,
            start_time=time(13, 0), end_time=time(14, 30),
        )

        row.refresh_from_db()

        self.assertEqual(row.permission_minutes, 90)
        self.assertEqual(row.excused_early_leave_minutes, 0)

    def test_pending_permission_explains_but_does_not_excuse(self):
        employee = self.make_employee()

        row = self.make_attendance(
            employee, work_date=MONDAY, check_in=time(9, 30),
        )

        self.make_permission(
            employee, work_date=MONDAY,
            permission_type=AttendancePermissionType.LATE_ARRIVAL,
            end_time=time(10, 0),
            status=AttendancePermissionStatus.SUBMITTED,
        )

        row.refresh_from_db()

        self.assertEqual(
            row.excused_late_minutes,
            0,
            "Pengajuan yang belum disetujui tidak boleh memaafkan "
            "apa pun — kalau boleh, setiap orang membebaskan dirinya "
            "sendiri.",
        )
        self.assertEqual(row.permission_state, "pending")

    def test_permission_never_touches_the_tap(self):
        employee = self.make_employee()

        row = self.make_attendance(
            employee, work_date=MONDAY,
            check_in=time(9, 40), check_out=time(16, 10),
        )

        before = (
            row.check_in, row.check_out,
            row.late_minutes, row.early_leave_minutes,
        )

        self.make_permission(
            employee, work_date=MONDAY,
            permission_type=AttendancePermissionType.LATE_ARRIVAL,
            end_time=time(9, 45),
        )

        row.refresh_from_db()

        self.assertEqual(
            (
                row.check_in, row.check_out,
                row.late_minutes, row.early_leave_minutes,
            ),
            before,
            "Jam tap dan angka menurut mesin adalah fakta; izin hanya "
            "mengklasifikasikannya.",
        )

    # ==================================================================
    # Lembur
    # ==================================================================

    def test_overtime_duration_is_derived_from_the_clock(self):
        employee = self.make_employee()

        overtime = EmployeeOvertimeService.create(
            data={
                "employee": employee,
                "work_date": MONDAY,
                "start_time": time(17, 0),
                "end_time": time(19, 30),
            },
        )

        self.assertEqual(overtime.duration_minutes, 150)
        self.assertEqual(overtime.duration_hours, 2.5)

    def test_overtime_crossing_midnight_is_not_negative(self):
        employee = self.make_employee()

        overtime = EmployeeOvertimeService.create(
            data={
                "employee": employee,
                "work_date": MONDAY,
                "start_time": time(23, 0),
                "end_time": time(1, 30),
            },
        )

        self.assertEqual(overtime.duration_minutes, 150)

    def test_unpaid_overtime_is_not_read_by_payroll(self):
        employee = self.make_employee()

        EmployeeOvertimeService.create(
            data={
                "employee": employee,
                "work_date": MONDAY,
                "start_time": time(17, 0),
                "end_time": time(19, 0),
                "is_paid": False,
            },
        )

        facts = self.facts(employee, start=MONDAY, end=MONDAY)

        self.assertEqual(facts.overtime_hours, Decimal("0.00"))
        self.assertFalse(facts.has_overtime_source)

    def test_cancelled_overtime_is_not_read_by_payroll(self):
        employee = self.make_employee()

        EmployeeOvertimeService.create(
            data={
                "employee": employee,
                "work_date": MONDAY,
                "start_time": time(17, 0),
                "end_time": time(19, 0),
                "is_paid": True,
                "status": "cancelled",
            },
        )

        facts = self.facts(employee, start=MONDAY, end=MONDAY)

        self.assertEqual(facts.overtime_hours, Decimal("0.00"))

    def test_two_records_on_one_date_are_one_overtime_day(self):
        """
        Dua catatan di tanggal yang sama dijumlahkan **sebelum**
        tingkat disusun.

        Kalau tidak, tarif jam pertama diberikan dua kali kepada
        perusahaan yang bertingkat harian — dan angkanya tidak bisa
        dijelaskan ke siapa pun.
        """
        employee = self.make_employee()

        for start, end in ((time(17, 0), time(18, 0)),
                           (time(18, 0), time(19, 30))):
            EmployeeOvertimeService.create(
                data={
                    "employee": employee,
                    "work_date": MONDAY,
                    "start_time": start,
                    "end_time": end,
                },
            )

        facts = self.facts(employee, start=MONDAY, end=MONDAY)

        self.assertEqual(facts.overtime_hours, Decimal("2.50"))
        self.assertEqual(facts.overtime_daily_hours, [Decimal("2.50")])

    def test_overtime_on_separate_dates_stays_separate(self):
        employee = self.make_employee()

        for offset in (0, 1):
            EmployeeOvertimeService.create(
                data={
                    "employee": employee,
                    "work_date": MONDAY + timedelta(days=offset),
                    "start_time": time(17, 0),
                    "end_time": time(18, 0),
                },
            )

        facts = self.facts(
            employee, start=MONDAY, end=MONDAY + timedelta(days=1),
        )

        self.assertEqual(facts.overtime_hours, Decimal("2.00"))
        self.assertEqual(
            facts.overtime_daily_hours,
            [Decimal("1.00"), Decimal("1.00")],
        )

    def test_no_trial_lineage_is_read(self):
        """
        Tidak satu pun konfigurasi silsilah uji ikut terbaca.

        Dikunci sebagai test, bukan sebagai catatan: dependensi yang
        dilarang hanya terbukti tidak ada kalau ada yang memeriksanya.
        """
        from apps.payroll.models import OvertimeGroup

        self.assertFalse(
            OvertimeGroup.objects.filter(code__startswith="TRL").exists(),
        )
        self.assertFalse(
            Employee.objects
            .filter(employee_number__startswith="TRL")
            .exists(),
        )


class OvertimeTierSplitTests(TenantTestCase):
    """
    Penyusunan jam lembur ke dalam tingkat.

    Dipisah dari kelas di atas karena yang diuji **fungsi murni** milik
    mesin hitung payroll — tidak butuh pegawai, tidak butuh presensi.
    """

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "ot-tiers"
        tenant.name = "Overtime Tiers"

    @staticmethod
    def tiers():
        from apps.payroll.models import OvertimeGroupTier

        return [
            OvertimeGroupTier(
                sequence=1,
                hour_from=Decimal("0.00"),
                hour_to=Decimal("2.00"),
                multiplier=Decimal("1.50"),
            ),
            OvertimeGroupTier(
                sequence=2,
                hour_from=Decimal("2.00"),
                hour_to=None,
                multiplier=Decimal("2.00"),
            ),
        ]

    def spread(self, hours: str):
        from apps.payroll.services.calculation import (
            PayrollCalculationService,
        )

        return PayrollCalculationService._spread_over_tiers(
            Decimal(hours), self.tiers(),
        )

    def test_below_the_boundary_uses_the_first_tier_only(self):
        weighted, parts, covered = self.spread("0.50")

        self.assertEqual(weighted, Decimal("0.75"))
        self.assertEqual(covered, Decimal("0.50"))
        self.assertEqual(len(parts), 1)

    def test_exactly_at_the_boundary_stays_in_the_first_tier(self):
        weighted, _, covered = self.spread("2.00")

        self.assertEqual(weighted, Decimal("3.00"))
        self.assertEqual(covered, Decimal("2.00"))

    def test_above_the_boundary_splits_across_both_tiers(self):
        weighted, parts, covered = self.spread("2.05")

        # 2,00 jam x 1,5 = 3,00 ; 0,05 jam x 2,0 = 0,10
        self.assertEqual(weighted, Decimal("3.10"))
        self.assertEqual(covered, Decimal("2.05"))
        self.assertEqual(len(parts), 2)

    def test_well_above_the_boundary(self):
        weighted, _, covered = self.spread("2.45")

        self.assertEqual(weighted, Decimal("3.90"))
        self.assertEqual(covered, Decimal("2.45"))


class PermissionTreatmentSplitTests(TenantTestCase):
    """
    `unpaid_over_minutes` hanya berlaku pada perlakuan **PAID**.

    Dikunci karena namanya menyesatkan: kolom itu terbaca seperti
    "batas sebelum potongan mulai", dan pada perlakuan UNPAID ia tidak
    dibaca sama sekali — seluruh durasinya dipotong. Yang mengonfigurasi
    izin keluar sementara dengan UNPAID + ambang akan mendapat angka
    yang bukan yang dimaksudnya.
    """

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "perm-treatment"
        tenant.name = "Permission Treatment"

    def test_paid_treatment_deducts_only_the_excess(self):
        rule = ResolvedPermissionRule(
            treatment=PermissionPayTreatment.PAID,
            unpaid_over_minutes=60,
        )

        self.assertEqual(rule.split(30), (30, 0))
        self.assertEqual(rule.split(60), (60, 0))
        self.assertEqual(rule.split(90), (60, 30))

    def test_unpaid_treatment_ignores_the_threshold(self):
        rule = ResolvedPermissionRule(
            treatment=PermissionPayTreatment.UNPAID,
            unpaid_over_minutes=60,
        )

        self.assertEqual(rule.split(30), (0, 30))
        self.assertEqual(rule.split(90), (0, 90))

    def test_information_only_reports_without_touching_pay(self):
        rule = ResolvedPermissionRule(
            treatment=PermissionPayTreatment.INFORMATION_ONLY,
            unpaid_over_minutes=60,
        )

        self.assertEqual(rule.split(90), (0, 0))
