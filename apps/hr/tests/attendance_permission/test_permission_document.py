"""
Dokumen izin: bentuknya, penjagaannya, dan perpindahan statusnya.

Yang **tidak** diuji di sini efeknya terhadap presensi — itu berkas
sebelah. Pemisahannya disengaja: test yang menguji dua hal sekaligus
gagal karena salah satunya dan tidak memberi tahu yang mana.
"""

from __future__ import annotations

from datetime import date, time, timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError

from apps.hr.api.attendance_permission.services import (
    AttendancePermissionService,
)
from apps.hr.models import (
    AttendancePermission,
    AttendancePermissionStatus,
    AttendancePermissionType,
)

from .base import TRIAL_DATE, AttendancePermissionTestCase


class PermissionShapeTestCase(AttendancePermissionTestCase):
    """Empat jenis izin, empat bentuk kolom jam."""

    def test_create_draft_issues_number_and_scope(self):
        employee = self.make_employee()

        permission = self.make_permission(
            employee,
            end_time=time(10, 0),
        )

        self.assertEqual(
            permission.status,
            AttendancePermissionStatus.DRAFT,
        )

        self.assertTrue(
            permission.document_number.startswith("APRM-"),
            permission.document_number,
        )

        # Cakupan didenormalisasi dari penempatan pegawainya — inilah
        # yang dipakai `RoleDataPermission` menyaring barisnya.
        self.assertEqual(permission.company_id, self.company.id)
        self.assertEqual(permission.location_id, self.head_office.id)

    def test_late_arrival_requires_end_time(self):
        employee = self.make_employee()

        with self.assertRaises(ValidationError) as raised:
            self.make_permission(employee)

        self.assertIn("end_time", raised.exception.message_dict)

    def test_early_leave_requires_start_time(self):
        employee = self.make_employee()

        with self.assertRaises(ValidationError) as raised:
            self.make_permission(
                employee,
                permission_type=AttendancePermissionType.EARLY_LEAVE,
            )

        self.assertIn("start_time", raised.exception.message_dict)

    def test_temporary_out_requires_both_times(self):
        employee = self.make_employee()

        with self.assertRaises(ValidationError) as raised:
            self.make_permission(
                employee,
                permission_type=AttendancePermissionType.TEMPORARY_OUT,
                start_time=time(13, 0),
            )

        self.assertIn("end_time", raised.exception.message_dict)

    def test_full_day_clears_times_instead_of_rejecting(self):
        """
        Kolom jam yang tidak dipakai tipenya **dikosongkan**, bukan
        ditolak.

        Form mengirim seluruh isinya apa adanya; mengganti jenis izin
        di form yang sama meninggalkan jam lama menempel, dan menolak
        berarti pengguna harus mengosongkan field yang sudah
        disembunyikan form.
        """
        employee = self.make_employee()

        permission = self.make_permission(
            employee,
            permission_type=AttendancePermissionType.FULL_DAY,
            start_time=time(13, 0),
            end_time=time(15, 0),
        )

        self.assertIsNone(permission.start_time)
        self.assertIsNone(permission.end_time)

    def test_reason_is_mandatory(self):
        employee = self.make_employee()

        with self.assertRaises(ValidationError) as raised:
            self.make_permission(
                employee,
                end_time=time(10, 0),
                reason="   ",
            )

        self.assertIn("reason", raised.exception.message_dict)

    def test_temporary_out_duration_counts_across_midnight(self):
        employee = self.make_employee(shift=self.night_shift)

        permission = self.make_permission(
            employee,
            permission_type=AttendancePermissionType.TEMPORARY_OUT,
            start_time=time(23, 30),
            end_time=time(1, 0),
        )

        # 23:30 → 01:00 keesokan harinya = 90 menit. Tanggal kalender
        # yang dibaca apa adanya menghasilkan angka negatif.
        self.assertEqual(permission.duration_minutes, 90)


class PermissionShiftGuardTestCase(AttendancePermissionTestCase):
    def test_outside_shift_is_rejected(self):
        employee = self.make_employee()

        with self.assertRaises(ValidationError) as raised:
            self.make_permission(
                employee,
                permission_type=AttendancePermissionType.TEMPORARY_OUT,
                start_time=time(18, 0),
                end_time=time(20, 0),
            )

        message = str(raised.exception.message_dict)

        self.assertIn("di luar jam kerja", message)

    def test_hr_override_accepts_outside_shift(self):
        employee = self.make_employee()

        permission = self.make_permission(
            employee,
            permission_type=AttendancePermissionType.TEMPORARY_OUT,
            start_time=time(18, 0),
            end_time=time(20, 0),
            allow_outside_shift=True,
            outside_shift_reason="Shift baru berubah setelah izin dibuat.",
        )

        self.assertTrue(permission.allow_outside_shift)

    def test_override_without_reason_is_rejected(self):
        employee = self.make_employee()

        with self.assertRaises(ValidationError) as raised:
            self.make_permission(
                employee,
                permission_type=AttendancePermissionType.TEMPORARY_OUT,
                start_time=time(18, 0),
                end_time=time(20, 0),
                allow_outside_shift=True,
            )

        self.assertIn(
            "outside_shift_reason",
            raised.exception.message_dict,
        )

    def test_night_shift_window_crossing_midnight_is_accepted(self):
        """
        Izin 23:30–01:00 pada shift 20:00–05:00 **sah**.

        Ini inti dukungan shift malam: jendelanya dinilai terhadap
        rentang shift, bukan terhadap tanggal kalender. Yang membaca
        tanggal apa adanya akan menolaknya sebagai "di luar jam kerja".
        """
        employee = self.make_employee(
            shift=self.night_shift,
            location=self.site,
        )

        permission = self.make_permission(
            employee,
            permission_type=AttendancePermissionType.TEMPORARY_OUT,
            start_time=time(23, 30),
            end_time=time(1, 0),
        )

        self.assertEqual(permission.duration_minutes, 90)


class PermissionOverlapTestCase(AttendancePermissionTestCase):
    def test_overlapping_permission_is_rejected(self):
        employee = self.make_employee()

        self.make_permission(
            employee,
            permission_type=AttendancePermissionType.TEMPORARY_OUT,
            start_time=time(13, 0),
            end_time=time(15, 0),
        )

        with self.assertRaises(ValidationError) as raised:
            self.make_permission(
                employee,
                permission_type=AttendancePermissionType.TEMPORARY_OUT,
                start_time=time(14, 0),
                end_time=time(16, 0),
            )

        self.assertIn(
            "Bertabrakan",
            str(raised.exception.message_dict),
        )

    def test_adjacent_permission_is_allowed(self):
        """
        Izin yang bersambung ujung ke ujung **bukan** tumpang tindih.

        13:00–15:00 lalu 15:00–16:00 adalah dua ketidakhadiran berbeda
        yang tidak berbagi satu menit pun. Menolaknya membuat orang
        memecah izinnya jadi satu baris panjang yang tidak
        menggambarkan apa yang terjadi.
        """
        employee = self.make_employee()

        self.make_permission(
            employee,
            permission_type=AttendancePermissionType.TEMPORARY_OUT,
            start_time=time(13, 0),
            end_time=time(15, 0),
        )

        second = self.make_permission(
            employee,
            permission_type=AttendancePermissionType.TEMPORARY_OUT,
            start_time=time(15, 0),
            end_time=time(16, 0),
        )

        self.assertEqual(second.duration_minutes, 60)

    def test_rejected_permission_does_not_block_a_new_one(self):
        employee = self.make_employee()

        first = self.make_permission(
            employee,
            permission_type=AttendancePermissionType.TEMPORARY_OUT,
            start_time=time(13, 0),
            end_time=time(15, 0),
        )

        AttendancePermissionService._set_status(
            permission=first,
            status=AttendancePermissionStatus.REJECTED,
        )

        second = self.make_permission(
            employee,
            permission_type=AttendancePermissionType.TEMPORARY_OUT,
            start_time=time(13, 0),
            end_time=time(15, 0),
        )

        self.assertIsNotNone(second.pk)

    def test_second_full_day_permission_is_rejected(self):
        employee = self.make_employee()

        self.make_permission(
            employee,
            permission_type=AttendancePermissionType.FULL_DAY,
        )

        with self.assertRaises(ValidationError):
            self.make_permission(
                employee,
                permission_type=AttendancePermissionType.FULL_DAY,
            )


class PermissionConflictWarningTestCase(AttendancePermissionTestCase):
    """
    Konflik dengan cuti dan hari libur adalah **peringatan**, bukan
    penolakan — keputusan tahap pertama yang ditulis di spesifikasinya.
    """

    def test_leave_on_the_same_date_is_reported_as_conflict(self):
        from apps.administration.models import LeaveType
        from apps.hr.models import EmployeeLeave, LeaveStatus

        employee = self.make_employee()

        leave_type = LeaveType.objects.create(
            code=f"APM-LV{employee.pk}",
            name="Cuti Tahunan",
        )

        EmployeeLeave.objects.create(
            employee=employee,
            leave_type=leave_type,
            start_date=TRIAL_DATE,
            end_date=TRIAL_DATE,
            total_days=Decimal("1.0"),
            status=LeaveStatus.APPROVED,
        )

        permission = self.make_permission(
            employee,
            end_time=time(10, 0),
        )

        codes = {
            row["code"]
            for row in AttendancePermissionService.detect_conflicts(permission)
        }

        self.assertIn("leave", codes)

    def test_non_working_day_is_reported_as_conflict(self):
        employee = self.make_employee()

        # Minggu. Kalender kantor Senin–Jumat, jadi hari ini tidak
        # menerbitkan kewajiban presensi sama sekali.
        sunday = TRIAL_DATE + timedelta(days=(6 - TRIAL_DATE.weekday()))

        permission = self.make_permission(
            employee,
            permission_type=AttendancePermissionType.FULL_DAY,
            work_date=sunday,
        )

        codes = {
            row["code"]
            for row in AttendancePermissionService.detect_conflicts(permission)
        }

        self.assertTrue(
            codes & {"non_working_day", "holiday"},
            codes,
        )

    def test_clean_permission_reports_no_conflict(self):
        employee = self.make_employee()

        permission = self.make_permission(
            employee,
            end_time=time(10, 0),
        )

        self.assertEqual(
            AttendancePermissionService.detect_conflicts(permission),
            [],
        )


class PermissionEditGuardTestCase(AttendancePermissionTestCase):
    def test_submitted_permission_cannot_be_edited(self):
        employee = self.make_employee()

        permission = self.make_permission(employee, end_time=time(10, 0))

        AttendancePermissionService._set_status(
            permission=permission,
            status=AttendancePermissionStatus.SUBMITTED,
        )

        with self.assertRaises(ValidationError) as raised:
            AttendancePermissionService.update(
                instance=permission,
                data={"reason": "Diubah di tengah jalan"},
            )

        self.assertIn("status", raised.exception.message_dict)

    def test_draft_permission_can_be_edited(self):
        employee = self.make_employee()

        permission = self.make_permission(employee, end_time=time(10, 0))

        updated = AttendancePermissionService.update(
            instance=permission,
            data={"reason": "Alasan yang diperbaiki"},
        )

        self.assertEqual(updated.reason, "Alasan yang diperbaiki")


class PermissionLockedPeriodTestCase(AttendancePermissionTestCase):
    """
    Periode payroll yang sudah FINALIZED mengunci tanggalnya.

    **Tanpa model periode presensi baru** — yang tidak boleh berubah
    adalah tanggal yang angkanya sudah dipakai membayar orang, dan
    satu-satunya tabel yang menyatakannya `PayrollPeriod`.
    """

    _period_counter = 0

    def _finalize_period(self):
        from apps.payroll.models import (
            PayrollGroup,
            PayrollPeriod,
        )
        from apps.payroll.models.choices import PayrollPeriodStatus

        type(self)._period_counter += 1

        suffix = type(self)._period_counter

        group = PayrollGroup.objects.create(
            code=f"APM-GRP{suffix}",
            name=f"Bulanan {suffix}",
        )

        period = PayrollPeriod.objects.create(
            company=self.company,
            payroll_group=group,
            code=f"APM-{TRIAL_DATE:%Y%m}-{suffix}",
            name="September 2026",
            start_date=date(TRIAL_DATE.year, TRIAL_DATE.month, 1),
            end_date=date(TRIAL_DATE.year, TRIAL_DATE.month, 30),
            status=PayrollPeriodStatus.FINALIZED,
        )

        # **Dibersihkan setelah test-nya.** Periode yang dikunci di sini
        # dibuat di luar transaksi test-nya, dan periode terkunci menolak
        # setiap izin di bulan itu — jadi tanpa baris ini, setiap kelas
        # test yang berjalan sesudah kelas ini gagal dengan "periode
        # sudah dikunci payroll", dan sebabnya terbaca seperti bug di
        # kode yang justru sedang diuji.
        self.addCleanup(period.delete)

        return period

    def test_locked_period_rejects_new_permission(self):
        employee = self.make_employee()

        self._finalize_period()

        with self.assertRaises(ValidationError) as raised:
            self.make_permission(employee, end_time=time(10, 0))

        message = str(raised.exception.message_dict)

        self.assertIn("dikunci payroll", message)

        # Pesannya harus menyebut jalan keluarnya. "Periode terkunci"
        # tanpa kelanjutan membuat orang mengetik ulang dokumen yang
        # sama sampai menyerah.
        self.assertIn("Attendance Adjustment", message)

    def test_locked_period_rejects_cancellation(self):
        employee = self.make_employee()

        permission = self.make_permission(employee, end_time=time(10, 0))

        self.approve_directly(permission)

        self._finalize_period()

        with self.assertRaises(ValidationError):
            AttendancePermissionService.cancel(permission=permission)

        self.assertEqual(
            self.refreshed(permission).status,
            AttendancePermissionStatus.APPROVED,
        )


class PermissionSoftDeleteTestCase(AttendancePermissionTestCase):
    def test_soft_delete_keeps_the_row(self):
        employee = self.make_employee()

        permission = self.make_permission(employee, end_time=time(10, 0))

        AttendancePermissionService.soft_delete(instance=permission)

        self.assertTrue(self.refreshed(permission).is_deleted)

        self.assertFalse(
            AttendancePermission.objects
            .filter(pk=permission.pk, is_deleted=False)
            .exists(),
        )
