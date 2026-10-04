"""
Sepuluh skenario trial, apa adanya.

Yang dikunci di sini **bukan** bahwa izin mengubah angka presensi —
justru sebaliknya: `late_minutes` tidak boleh bergerak satu menit pun
karena ada izin. Yang berubah klasifikasinya, dan setiap test di bawah
memeriksa keduanya sekaligus. Test yang cuma memeriksa "excused = ya"
akan tetap hijau kalau suatu saat ada yang memutuskan mengurangi
`late_minutes`, dan itu justru perilaku yang paling dilarang
spesifikasinya.
"""

from __future__ import annotations

from datetime import time, timedelta

from apps.hr.models import (
    AttendancePermissionStatus,
    AttendancePermissionType,
    AttendanceStatus,
)
from apps.hr.api.attendance_permission.services import (
    AttendancePermissionService,
)

from .base import TRIAL_DATE, AttendancePermissionTestCase, at


class NormalAttendanceTestCase(AttendancePermissionTestCase):
    """Skenario 01 — hadir tepat waktu, tanpa pengecualian."""

    def test_present_without_exception(self):
        employee = self.make_employee()

        row = self.make_attendance(
            employee,
            check_in=at(TRIAL_DATE, 7, 55),
            check_out=at(TRIAL_DATE, 17, 5),
        )

        self.assertEqual(row.status, AttendanceStatus.PRESENT)
        self.assertEqual(row.late_minutes, 0)
        self.assertEqual(row.early_leave_minutes, 0)
        self.assertEqual(row.permission_state, "")


class UnauthorizedLateTestCase(AttendancePermissionTestCase):
    """Skenario 02 — terlambat 2 jam tanpa izin."""

    def test_late_without_permission_is_unauthorized(self):
        employee = self.make_employee()

        row = self.make_attendance(
            employee,
            check_in=at(TRIAL_DATE, 10, 0),
            check_out=at(TRIAL_DATE, 17, 0),
        )

        self.assertEqual(row.late_minutes, 120)
        self.assertEqual(row.excused_late_minutes, 0)
        self.assertEqual(row.unauthorized_late_minutes, 120)
        self.assertEqual(row.permission_state, "unauthorized")


class ExcusedLateTestCase(AttendancePermissionTestCase):
    """Skenario 03 — terlambat 115 menit dengan izin sampai 10:00."""

    def test_late_within_permission_is_fully_excused(self):
        employee = self.make_employee()

        permission = self.make_permission(
            employee,
            permission_type=AttendancePermissionType.LATE_ARRIVAL,
            end_time=time(10, 0),
        )

        self.approve_directly(permission)

        row = self.make_attendance(
            employee,
            check_in=at(TRIAL_DATE, 9, 55),
            check_out=at(TRIAL_DATE, 17, 0),
        )

        # Angka menurut mesin **tidak bergerak**. Ini yang membuat
        # "terlambat 115 menit karena izin" dan "terlambat 115 menit
        # tanpa izin" tetap dua baris yang angkanya sama.
        self.assertEqual(row.late_minutes, 115)

        self.assertEqual(row.excused_late_minutes, 115)
        self.assertEqual(row.unauthorized_late_minutes, 0)
        self.assertEqual(row.permission_state, "excused")


class PartiallyExcusedLateTestCase(AttendancePermissionTestCase):
    """
    Skenario 04 — izin sampai 10:00, datang 10:30.

    Hanya bagian di luar izin yang tanpa izin. Menganggap seluruh 150
    menit termaafkan membuat izin jadi surat sakti; menganggap seluruh
    150 menit tanpa izin membuat izin tidak berguna.
    """

    def test_only_the_uncovered_portion_is_unauthorized(self):
        employee = self.make_employee()

        permission = self.make_permission(
            employee,
            permission_type=AttendancePermissionType.LATE_ARRIVAL,
            end_time=time(10, 0),
        )

        self.approve_directly(permission)

        row = self.make_attendance(
            employee,
            check_in=at(TRIAL_DATE, 10, 30),
            check_out=at(TRIAL_DATE, 17, 0),
        )

        self.assertEqual(row.late_minutes, 150)
        self.assertEqual(row.excused_late_minutes, 120)
        self.assertEqual(row.unauthorized_late_minutes, 30)
        self.assertEqual(row.permission_state, "partial")


class ExcusedEarlyLeaveTestCase(AttendancePermissionTestCase):
    """Skenario 05 — izin pulang mulai 15:00, tap keluar 15:05."""

    def test_early_leave_within_permission_is_excused(self):
        employee = self.make_employee()

        permission = self.make_permission(
            employee,
            permission_type=AttendancePermissionType.EARLY_LEAVE,
            start_time=time(15, 0),
        )

        self.approve_directly(permission)

        row = self.make_attendance(
            employee,
            check_in=at(TRIAL_DATE, 8, 0),
            check_out=at(TRIAL_DATE, 15, 5),
        )

        self.assertEqual(row.early_leave_minutes, 115)
        self.assertEqual(row.excused_early_leave_minutes, 115)
        self.assertEqual(row.unauthorized_early_leave_minutes, 0)
        self.assertEqual(row.permission_state, "excused")

    def test_leaving_before_the_allowed_time_is_partly_unauthorized(self):
        employee = self.make_employee()

        permission = self.make_permission(
            employee,
            permission_type=AttendancePermissionType.EARLY_LEAVE,
            start_time=time(15, 0),
        )

        self.approve_directly(permission)

        row = self.make_attendance(
            employee,
            check_in=at(TRIAL_DATE, 8, 0),
            check_out=at(TRIAL_DATE, 14, 0),
        )

        self.assertEqual(row.early_leave_minutes, 180)
        self.assertEqual(row.excused_early_leave_minutes, 120)
        self.assertEqual(row.unauthorized_early_leave_minutes, 60)


class TemporaryOutTestCase(AttendancePermissionTestCase):
    """
    Skenario 06 — izin keluar 13:00–15:00.

    Presensi aktualnya **tetap dipertahankan**: jam masuk dan jam
    pulang tidak berubah, dan jam kerjanya tetap tercatat di sebelah
    menit izinnya.
    """

    def test_temporary_out_is_recorded_beside_actual_attendance(self):
        employee = self.make_employee()

        permission = self.make_permission(
            employee,
            permission_type=AttendancePermissionType.TEMPORARY_OUT,
            start_time=time(13, 0),
            end_time=time(15, 0),
        )

        self.approve_directly(permission)

        row = self.make_attendance(
            employee,
            check_in=at(TRIAL_DATE, 8, 0),
            check_out=at(TRIAL_DATE, 17, 0),
        )

        self.assertEqual(row.permission_minutes, 120)

        # Presensi aktualnya utuh.
        self.assertEqual(row.check_in, at(TRIAL_DATE, 8, 0))
        self.assertEqual(row.check_out, at(TRIAL_DATE, 17, 0))
        self.assertEqual(row.status, AttendanceStatus.PRESENT)

        self.assertEqual(row.permission_state, "excused")

    def test_two_temporary_outs_are_summed(self):
        employee = self.make_employee()

        for start, end in ((time(10, 0), time(11, 0)),
                           (time(13, 0), time(15, 0))):
            permission = self.make_permission(
                employee,
                permission_type=AttendancePermissionType.TEMPORARY_OUT,
                start_time=start,
                end_time=end,
            )

            self.approve_directly(permission)

        row = self.make_attendance(
            employee,
            check_in=at(TRIAL_DATE, 8, 0),
            check_out=at(TRIAL_DATE, 17, 0),
        )

        self.assertEqual(row.permission_minutes, 180)


class FullDayPermissionTestCase(AttendancePermissionTestCase):
    """Skenario 07 — izin sehari, tidak ada tap sama sekali."""

    def test_absence_with_permission_is_excused(self):
        employee = self.make_employee()

        permission = self.make_permission(
            employee,
            permission_type=AttendancePermissionType.FULL_DAY,
        )

        self.approve_directly(permission)

        row = self.make_attendance(
            employee,
            status=AttendanceStatus.ABSENT,
        )

        # Statusnya tetap ABSENT. Menggesernya ke `permit` akan
        # mengeluarkannya dari potongan payroll **diam-diam** — dan
        # dibayar atau tidak adalah keputusan Payroll Permission Rule,
        # bukan efek samping sebuah kolom status.
        self.assertEqual(row.status, AttendanceStatus.ABSENT)

        self.assertTrue(row.is_excused_absence)
        self.assertFalse(row.is_unauthorized_absence)
        self.assertEqual(row.permission_state, "excused")

    def test_absence_without_permission_stays_unauthorized(self):
        employee = self.make_employee()

        row = self.make_attendance(
            employee,
            status=AttendanceStatus.ABSENT,
        )

        self.assertFalse(row.is_excused_absence)
        self.assertTrue(row.is_unauthorized_absence)
        self.assertEqual(row.permission_state, "unauthorized")


class RejectedPermissionTestCase(AttendancePermissionTestCase):
    """Skenario 08 — izin ditolak; presensinya tidak terpengaruh."""

    def test_rejected_permission_does_not_excuse_anything(self):
        employee = self.make_employee()

        permission = self.make_permission(
            employee,
            permission_type=AttendancePermissionType.LATE_ARRIVAL,
            end_time=time(10, 0),
        )

        AttendancePermissionService._set_status(
            permission=permission,
            status=AttendancePermissionStatus.REJECTED,
        )

        row = self.make_attendance(
            employee,
            check_in=at(TRIAL_DATE, 10, 0),
            check_out=at(TRIAL_DATE, 17, 0),
        )

        self.assertEqual(row.late_minutes, 120)
        self.assertEqual(row.excused_late_minutes, 0)
        self.assertEqual(row.unauthorized_late_minutes, 120)
        self.assertEqual(row.permission_state, "unauthorized")


class PendingPermissionTestCase(AttendancePermissionTestCase):
    """
    Skenario 09 — izin masih berjalan.

    Yang belum disetujui **tidak memaafkan apa pun**; kalau ia ikut
    dibaca, setiap orang bisa membebaskan keterlambatannya sendiri
    dengan mengetik dokumen yang tidak pernah disetujui siapa pun. Yang
    dibedakan cuma penandanya di layar.
    """

    def test_pending_permission_is_flagged_but_not_excused(self):
        employee = self.make_employee()

        permission = self.make_permission(
            employee,
            permission_type=AttendancePermissionType.LATE_ARRIVAL,
            end_time=time(10, 0),
        )

        AttendancePermissionService._set_status(
            permission=permission,
            status=AttendancePermissionStatus.SUBMITTED,
        )

        row = self.make_attendance(
            employee,
            check_in=at(TRIAL_DATE, 9, 0),
            check_out=at(TRIAL_DATE, 17, 0),
        )

        self.assertEqual(row.late_minutes, 60)
        self.assertEqual(row.excused_late_minutes, 0)
        self.assertEqual(row.permission_state, "pending")

    def test_draft_permission_is_not_even_pending(self):
        """
        Dokumen yang belum diajukan belum diketahui siapa pun.
        Menampilkannya sebagai "menunggu izin" di layar atasan berarti
        menagih keputusan atas sesuatu yang belum sampai ke mejanya.
        """
        employee = self.make_employee()

        self.make_permission(
            employee,
            permission_type=AttendancePermissionType.LATE_ARRIVAL,
            end_time=time(10, 0),
        )

        row = self.make_attendance(
            employee,
            check_in=at(TRIAL_DATE, 9, 0),
            check_out=at(TRIAL_DATE, 17, 0),
        )

        self.assertEqual(row.permission_state, "unauthorized")


class NightShiftTestCase(AttendancePermissionTestCase):
    """
    Skenario 10 — shift 20:00–05:00, izin keluar 23:30–01:00.

    Resolver memakai **batas shift**, bukan tanggal kalender. Yang
    membaca tanggal apa adanya menghitung jendela 23:30 → 01:00 sebagai
    angka negatif, lalu memotongnya jadi nol tanpa satu pun error.
    """

    def test_temporary_out_across_midnight_is_counted(self):
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

        self.approve_directly(permission)

        row = self.make_attendance(
            employee,
            shift=self.night_shift,
            check_in=at(TRIAL_DATE, 20, 0),
            check_out=at(TRIAL_DATE + timedelta(days=1), 5, 0),
        )

        self.assertEqual(row.permission_minutes, 90)

    def test_late_arrival_on_night_shift_is_excused(self):
        employee = self.make_employee(
            shift=self.night_shift,
            location=self.site,
        )

        permission = self.make_permission(
            employee,
            permission_type=AttendancePermissionType.LATE_ARRIVAL,
            end_time=time(22, 0),
        )

        self.approve_directly(permission)

        row = self.make_attendance(
            employee,
            shift=self.night_shift,
            check_in=at(TRIAL_DATE, 21, 55),
            check_out=at(TRIAL_DATE + timedelta(days=1), 5, 0),
        )

        self.assertEqual(row.late_minutes, 115)
        self.assertEqual(row.excused_late_minutes, 115)
        self.assertEqual(row.unauthorized_late_minutes, 0)


class RecalculationTestCase(AttendancePermissionTestCase):
    """
    Presensi yang sudah terbit **sebelum** izinnya disetujui.

    Ini urutan yang paling lazim di lapangan: mesin sidik jari sudah
    mengirim tapnya, izinnya menyusul. Tanpa perhitungan ulang,
    persetujuan atasan tidak mengubah apa pun dan gagalnya diam.
    """

    def test_approval_recalculates_existing_attendance(self):
        employee = self.make_employee()

        row = self.make_attendance(
            employee,
            check_in=at(TRIAL_DATE, 10, 0),
            check_out=at(TRIAL_DATE, 17, 0),
        )

        self.assertEqual(row.excused_late_minutes, 0)
        self.assertEqual(row.permission_state, "unauthorized")

        permission = self.make_permission(
            employee,
            permission_type=AttendancePermissionType.LATE_ARRIVAL,
            end_time=time(10, 0),
        )

        self.approve_directly(permission)

        row = self.refreshed(row)

        # Angka mentahnya tetap. Yang berubah klasifikasinya.
        self.assertEqual(row.late_minutes, 120)
        self.assertEqual(row.excused_late_minutes, 120)
        self.assertEqual(row.permission_state, "excused")

    def test_cancelling_an_approved_permission_withdraws_the_excuse(self):
        employee = self.make_employee()

        permission = self.make_permission(
            employee,
            permission_type=AttendancePermissionType.LATE_ARRIVAL,
            end_time=time(10, 0),
        )

        self.approve_directly(permission)

        row = self.make_attendance(
            employee,
            check_in=at(TRIAL_DATE, 10, 0),
            check_out=at(TRIAL_DATE, 17, 0),
        )

        self.assertEqual(row.excused_late_minutes, 120)

        AttendancePermissionService.cancel(permission=permission)

        row = self.refreshed(row)

        self.assertEqual(row.late_minutes, 120)
        self.assertEqual(row.excused_late_minutes, 0)
        self.assertEqual(row.permission_state, "unauthorized")

        self.assertEqual(
            self.refreshed(permission).status,
            AttendancePermissionStatus.CANCELLED,
        )

    def test_soft_deleting_a_permission_withdraws_the_excuse(self):
        employee = self.make_employee()

        permission = self.make_permission(
            employee,
            permission_type=AttendancePermissionType.LATE_ARRIVAL,
            end_time=time(10, 0),
        )

        self.approve_directly(permission)

        row = self.make_attendance(
            employee,
            check_in=at(TRIAL_DATE, 10, 0),
            check_out=at(TRIAL_DATE, 17, 0),
        )

        self.assertEqual(row.excused_late_minutes, 120)

        AttendancePermissionService.soft_delete(instance=permission)

        row = self.refreshed(row)

        self.assertEqual(row.excused_late_minutes, 0)

    def test_recalculation_reports_zero_when_no_attendance_row_exists(self):
        """
        Nol baris bukan kegagalan — izin sah diajukan untuk tanggal
        yang presensinya belum diimpor. Melaporkan "berhasil" untuk nol
        baris membuat orang menunggu perubahan yang tidak akan datang.
        """
        employee = self.make_employee()

        permission = self.make_permission(
            employee,
            permission_type=AttendancePermissionType.LATE_ARRIVAL,
            end_time=time(10, 0),
        )

        AttendancePermissionService._set_status(
            permission=permission,
            status=AttendancePermissionStatus.APPROVED,
        )

        self.assertEqual(
            AttendancePermissionService.recalculate_attendance(
                permission=permission,
            ),
            0,
        )
