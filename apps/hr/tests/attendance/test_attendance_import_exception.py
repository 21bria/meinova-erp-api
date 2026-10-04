"""
Import -> Attendance Policy -> pengecualian, dan batas-batasnya.

Yang dijaga di sini satu hal pokok: **importer tidak punya aturan
pengecualian sendiri.** Ambang "terlambat lebih dari sekian menit
dianggap harus mengambil cuti" tinggal di `AttendancePolicy`, dan
importer cuma menuliskan jam tap plus jadwalnya lalu membiarkan
`AttendancePolicyResolver` yang memutuskan. Kalau nanti ada yang
memindahkan ambangnya ke importer, `test_threshold_comes_from_policy`
yang pertama gagal.

Tiga hal lain yang ikut dikunci:

* baris presensi yang **sudah** berstatus cuti tidak boleh berubah jadi
  terlambat gara-gara ada tap yang masuk untuk tanggal itu;
* penanda kewajiban cuti **tidak** memotong saldo;
* yang boleh memutuskan pengecualian adalah **akun** atasan langsung —
  bukan siapa pun yang id User-nya kebetulan sama dengan id Employee
  atasan.
"""

from __future__ import annotations

import tempfile
from datetime import date
from decimal import Decimal
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied

from apps.administration.models import AttendancePolicy
from apps.framework.imports import ImportPipelineService
from apps.hr.api.attendance.obligation import AttendanceObligationService
from apps.hr.models import (
    AttendanceStatus,
    EmployeeAttendance,
    OrganizationAssignment,
)

from .base import MODULE, AttendanceImportTestCase


# Rabu, hari kerja kantor pada kalender bawaan (Senin–Jumat).
WORK_DAY = date(2026, 7, 1)


class AttendanceExceptionTestCase(AttendanceImportTestCase):
    """Profil HO sederhana: koma, satu kolom waktu, tap mentah."""

    @classmethod
    def attendance_policy(cls, **overrides):
        payload = {
            "code": f"AIM-POL-{overrides.pop('suffix', '1')}",
            "name": "Attendance Policy",
            "location": cls.site,
            "late_tolerance_minutes": 1,
            "early_leave_tolerance_minutes": 1,
            "late_leave_threshold_minutes": 120,
            "early_leave_leave_threshold_minutes": 120,
            "leave_deduction_days": Decimal("1.00"),
            "overtime_threshold_minutes": 30,
            "break_minutes": 60,
        }

        payload.update(overrides)

        return AttendancePolicy.objects.create(**payload)

    @classmethod
    def profile(cls, code):
        return cls.make_profile(
            code,
            mapping={
                "employee_code": ["employeecode"],
                "log_time": ["timestamp"],
            },
            datetime_formats=["%Y-%m-%d %H:%M:%S"],
            options={"attendance": {"event_mode": "raw_tap"}},
        )

    def csv_for(self, rows):
        """`rows` = [(employee_number, "HH:MM:SS"), ...]"""
        lines = ["EmployeeCode,Timestamp"]

        for number, clock in rows:
            lines.append(f"{number},{WORK_DAY.isoformat()} {clock}")

        handle = tempfile.NamedTemporaryFile(
            mode="w",
            suffix=".csv",
            delete=False,
            encoding="utf-8",
        )

        handle.write("\n".join(lines) + "\n")
        handle.close()

        self.addCleanup(lambda: Path(handle.name).unlink(missing_ok=True))

        return Path(handle.name)

    def run_import(self, profile, path):
        return ImportPipelineService.execute(
            module=MODULE,
            file_path=path,
            source_type="csv",
            parser_options=profile.parser_options,
            mapping=profile.mapping or None,
            value_mapping=profile.value_mapping or None,
            date_formats=profile.datetime_formats or None,
            options=profile.options or None,
            profile=profile,
        )

    def attendance_of(self, employee):
        return EmployeeAttendance.objects.get(
            employee=employee,
            work_date=WORK_DAY,
            is_deleted=False,
        )


class PolicyDrivenExceptionTests(AttendanceExceptionTestCase):
    def test_threshold_comes_from_policy_not_from_the_importer(self):
        """
        Dua pegawai, dua policy, satu file.

        Keterlambatannya **sama persis** (150 menit). Yang satu
        menghasilkan kewajiban cuti karena policy-nya berambang 120,
        yang lain tidak karena ambangnya dimatikan. Kalau ambangnya
        hidup di importer, kedua baris ini akan sama.
        """
        self.attendance_policy(suffix="ON", location=self.site)

        self.attendance_policy(
            suffix="OFF",
            location=self.other_site,
            late_leave_threshold_minutes=0,
            early_leave_leave_threshold_minutes=0,
            leave_deduction_days=Decimal("0.00"),
        )

        watched = self.make_employee(
            shift=self.office_shift,
            location=self.site,
        )

        exempt = self.make_employee(
            shift=self.office_shift,
            location=self.other_site,
        )

        profile = self.profile("AIM-EXC-1")

        path = self.csv_for([
            (watched.employee_number, "12:30:00"),
            (watched.employee_number, "18:00:00"),
            (exempt.employee_number, "12:30:00"),
            (exempt.employee_number, "18:00:00"),
        ])

        self.run_import(profile, path)

        strict = self.attendance_of(watched)
        loose = self.attendance_of(exempt)

        # Jam tapnya identik, jadi menit telatnya identik juga.
        self.assertEqual(strict.late_minutes, loose.late_minutes)
        self.assertEqual(strict.status, AttendanceStatus.LATE)
        self.assertEqual(loose.status, AttendanceStatus.LATE)

        # Yang berbeda cuma policy-nya.
        self.assertEqual(strict.leave_required_days, Decimal("1.00"))
        self.assertEqual(strict.leave_required_reason, "late")

        self.assertEqual(loose.leave_required_days, Decimal("0.00"))
        self.assertEqual(loose.leave_required_reason, "")

    def test_late_below_threshold_is_late_but_not_an_exception(self):
        self.attendance_policy(suffix="BELOW")

        employee = self.make_employee(shift=self.office_shift)

        profile = self.profile("AIM-EXC-2")

        # Jadwal 10:00; datang 10:45 = 45 menit, di bawah ambang 120.
        self.run_import(
            profile,
            self.csv_for([
                (employee.employee_number, "10:45:00"),
                (employee.employee_number, "18:00:00"),
            ]),
        )

        attendance = self.attendance_of(employee)

        self.assertEqual(attendance.status, AttendanceStatus.LATE)

        # Toleransi 1 menit dipotong dari menit telatnya...
        self.assertEqual(attendance.late_minutes, 44)

        # ...tapi ambang 120 dinilai terhadap selisih **mentah**.
        self.assertEqual(attendance.leave_required_days, Decimal("0.00"))
        self.assertEqual(attendance.leave_obligation_status, "none")

    def test_early_leave_above_threshold_is_an_exception(self):
        self.attendance_policy(suffix="EARLY")

        employee = self.make_employee(shift=self.office_shift)

        profile = self.profile("AIM-EXC-3")

        # Jadwal pulang 18:00; pulang 15:30 = 150 menit.
        self.run_import(
            profile,
            self.csv_for([
                (employee.employee_number, "09:55:00"),
                (employee.employee_number, "15:30:00"),
            ]),
        )

        attendance = self.attendance_of(employee)

        self.assertEqual(attendance.early_leave_minutes, 149)
        self.assertEqual(attendance.leave_required_reason, "early_leave")
        self.assertEqual(attendance.leave_required_days, Decimal("1.00"))
        self.assertEqual(attendance.leave_obligation_status, "outstanding")

    def test_normal_day_produces_no_exception(self):
        self.attendance_policy(suffix="NORMAL")

        employee = self.make_employee(shift=self.office_shift)

        profile = self.profile("AIM-EXC-4")

        self.run_import(
            profile,
            self.csv_for([
                (employee.employee_number, "09:52:00"),
                (employee.employee_number, "18:05:00"),
            ]),
        )

        attendance = self.attendance_of(employee)

        self.assertEqual(attendance.status, AttendanceStatus.PRESENT)
        self.assertEqual(attendance.late_minutes, 0)
        self.assertEqual(attendance.early_leave_minutes, 0)

        # 5 menit lewat jadwal, di bawah ambang lembur 30 menit.
        self.assertEqual(attendance.overtime_minutes, 0)
        self.assertEqual(attendance.leave_obligation_status, "none")

    def test_marker_never_touches_the_leave_balance(self):
        """
        Penanda, bukan eksekusi. Yang memotong saldo tetap dokumen cuti
        yang diajukan dan disetujui — dan itu berlaku juga untuk
        pengecualian yang lahir dari satu file absensi berisi ratusan
        baris.
        """
        self.attendance_policy(suffix="BAL")

        employee = self.make_employee(shift=self.office_shift)

        profile = self.profile("AIM-EXC-5")

        self.run_import(
            profile,
            self.csv_for([
                (employee.employee_number, "12:30:00"),
                (employee.employee_number, "18:00:00"),
            ]),
        )

        attendance = self.attendance_of(employee)

        self.assertEqual(attendance.leave_required_days, Decimal("1.00"))

        # Tidak ada dokumen cuti, dan tidak ada saldo yang bergerak.
        self.assertIsNone(attendance.leave_id)

        self.assertFalse(
            employee.leave_balances.filter(used__gt=0).exists(),
        )


class LeaveDayIsNeverOverwrittenTests(AttendanceExceptionTestCase):
    def test_tap_on_a_leave_day_does_not_become_late(self):
        """
        Pegawai yang sedang cuti kadang tetap menekan mesin — mampir
        mengambil barang, atau ikut rapat sebentar. Tap itu tidak boleh
        mengubah harinya jadi terlambat, dan **tidak** boleh
        menerbitkan kewajiban cuti di atas cuti yang sudah berjalan.

        Yang menjaganya `NON_COMPUTED_STATUSES` di
        `AttendancePolicyResolver.compute()`, dan pemeriksaan ini
        memastikan jalur import benar-benar melewatinya.
        """
        self.attendance_policy(suffix="LEAVE")

        employee = self.make_employee(shift=self.office_shift)

        assignment = OrganizationAssignment.objects.get(employee=employee)

        # Barisnya sudah ada dan sudah berstatus cuti — persis keadaan
        # setelah `close_attendance` menutup hari itu.
        EmployeeAttendance.objects.create(
            employee=employee,
            company=assignment.company,
            location=assignment.location,
            work_date=WORK_DAY,
            status=AttendanceStatus.LEAVE,
        )

        profile = self.profile("AIM-EXC-LEAVE")

        self.run_import(
            profile,
            self.csv_for([
                (employee.employee_number, "12:30:00"),
                (employee.employee_number, "18:00:00"),
            ]),
        )

        attendance = self.attendance_of(employee)

        self.assertEqual(attendance.status, AttendanceStatus.LEAVE)
        self.assertEqual(attendance.late_minutes, 0)
        self.assertEqual(attendance.leave_required_days, Decimal("0.00"))
        self.assertEqual(attendance.leave_obligation_status, "none")

        # Satu baris, bukan dua: hari cutinya tidak digandakan.
        self.assertEqual(
            EmployeeAttendance.objects
            .filter(employee=employee, work_date=WORK_DAY, is_deleted=False)
            .count(),
            1,
        )


class ObligationReviewPermissionTests(AttendanceExceptionTestCase):
    """
    Siapa yang boleh memutuskan pengecualian.

    Pernah salah, dan salahnya diam: `manager_of()` mengembalikan
    **Employee** sementara yang login **User**, jadi
    `supervisor.pk == user.pk` membandingkan dua ruang id yang berbeda.
    Akibatnya atasan sungguhan ditolak, dan akun yang id-nya kebetulan
    sama dengan id Employee atasan justru lolos.
    """

    def _row(self, employee):
        assignment = OrganizationAssignment.objects.get(employee=employee)

        return EmployeeAttendance.objects.create(
            employee=employee,
            company=assignment.company,
            location=assignment.location,
            work_date=WORK_DAY,
            status=AttendanceStatus.LATE,
            leave_required_days=Decimal("1.00"),
            leave_required_reason="late",
        )

    def _account(self, username):
        return get_user_model().objects.create_user(
            username=username,
            email=f"{username}@example.com",
            password="x",
        )

    def test_supervisor_account_may_review(self):
        boss_account = self._account("aim-boss")

        boss = self.make_employee(
            shift=self.office_shift,
            user=boss_account,
        )

        employee = self.make_employee(shift=self.office_shift)

        OrganizationAssignment.objects.filter(employee=employee).update(
            reports_to=boss,
        )

        attendance = self._row(employee)

        AttendanceObligationService.waive(
            instance=attendance,
            reason="Izin atasan, sudah dikabarkan lewat telepon.",
            user=boss_account,
        )

        attendance.refresh_from_db()

        self.assertTrue(attendance.leave_required_waived)
        self.assertEqual(attendance.review_decision, "valid")

        # Faktanya tetap tersimpan; yang berubah cuma yang berlaku.
        self.assertEqual(attendance.leave_required_days, Decimal("1.00"))
        self.assertEqual(attendance.leave_required_effective, Decimal("0.00"))

    def test_unrelated_account_may_not_review(self):
        boss_account = self._account("aim-boss-2")

        boss = self.make_employee(
            shift=self.office_shift,
            user=boss_account,
        )

        employee = self.make_employee(shift=self.office_shift)

        OrganizationAssignment.objects.filter(employee=employee).update(
            reports_to=boss,
        )

        stranger = self._account("aim-stranger")

        with self.assertRaises(PermissionDenied):
            AttendanceObligationService.waive(
                instance=self._row(employee),
                reason="Bukan urusan saya.",
                user=stranger,
            )

    def test_require_leave_records_the_decision_without_issuing_leave(self):
        boss_account = self._account("aim-boss-3")

        boss = self.make_employee(
            shift=self.office_shift,
            user=boss_account,
        )

        employee = self.make_employee(shift=self.office_shift)

        OrganizationAssignment.objects.filter(employee=employee).update(
            reports_to=boss,
        )

        attendance = self._row(employee)

        AttendanceObligationService.require_leave(
            instance=attendance,
            notes="Tidak ada pemberitahuan sebelumnya.",
            user=boss_account,
        )

        attendance.refresh_from_db()

        self.assertEqual(attendance.review_decision, "require_leave")
        self.assertFalse(attendance.leave_required_waived)

        # Dokumen cutinya **tidak** diterbitkan di sini, dan saldonya
        # tidak bergerak. Pegawainya yang mengajukan lewat modul Cuti.
        self.assertIsNone(attendance.leave_id)

        self.assertFalse(
            employee.leave_balances.filter(used__gt=0).exists(),
        )
