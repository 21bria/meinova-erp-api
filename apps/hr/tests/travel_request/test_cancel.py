"""
M4 — pembatalan Travel Request yang sudah disetujui.

Sebelum ini dokumen yang sudah APPROVED tidak punya jalur keluar sama
sekali: `withdraw()` cuma jalan selama alurnya masih terbuka, dan cuti
yang terlanjur terbit tidak punya pencabutan. Perjalanan yang batal
karena tiketnya hangus meninggalkan dokumen berstatus "Approved"
selamanya, saldo cuti yang terpotong untuk cuti yang tidak pernah
diambil, dan blok jadwal yang tidak bisa diajukan ulang.

Yang dijaga berkas ini, dan semuanya gagal **diam-diam** kalau rusak:

- pembatalan memakai `EmployeeLeaveService`, bukan ORM — saldo hanya
  benar kalau `recalculate_used` yang menghitungnya;
- catatan cuti **dibatalkan**, bukan dihapus, dan nomor LV-nya tetap;
- catatan cuti yang cuma **diadopsi** dari HR tidak ikut dicabut;
- pemanggilan kedua tidak menyentuh apa pun lagi;
- dokumen yang belum disetujui tidak bisa memakai jalur ini.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from django.core.exceptions import ValidationError

from apps.administration.models import (
    LeaveType,
    RotationPurpose,
)
from apps.hr.api.leave.services import EmployeeLeaveService
from apps.hr.api.travel_request.services import (
    TravelRequestPurposeService,
    TravelRequestService,
)
from apps.hr.models import (
    EmployeeLeave,
    LeaveBalance,
    LeaveStatus,
    TravelRequestStatus,
)

from .base import TravelRequestTestCase


SERVICE_LOGGER = "apps.hr.api.travel_request.services"

# Jangkar tanggal sendiri, jauh dari berkas test tetangga.
# `TenantTestCase` tidak me-rollback antar test, jadi dokumen milik
# berkas lain harus jatuh di luar jendela pencarian overlap di sini.
WINDOW_START = date(2028, 5, 8)
WINDOW_END = date(2028, 5, 19)
WINDOW_YEAR = WINDOW_START.year


class CancelTestBase(TravelRequestTestCase):
    """TR yang barisnya memotong saldo, plus kartu cuti untuk dibaca."""

    _kind_counter = 0

    @classmethod
    def make_leave_kind(cls):
        """
        Satu Leave Type + Travel Purpose ber-`deducts_leave` yang cuma
        dipakai satu test.

        Berbagi satu jenis cuti antar test membuat pencarian overlap
        menemukan dokumen test sebelumnya, dan kegagalannya muncul di
        test yang tidak bersalah.
        """
        cls._kind_counter += 1

        suffix = f"{cls._kind_counter:02d}"

        leave_type = LeaveType.objects.create(
            code=f"TRC-LT-{suffix}",
            name=f"Cuti Batal {suffix}",
        )

        purpose = RotationPurpose.objects.create(
            code=f"TRC-RP-{suffix}",
            name=f"Cuti Batal {suffix}",
            deducts_leave=True,
            leave_type=leave_type,
        )

        return leave_type, purpose

    def make_deducting_request(self, *, employee=None, purpose=None):
        employee = employee or self.make_employee()

        request = self.make_request(
            employee,
            start_date=WINDOW_START,
            end_date=WINDOW_END,
            with_purpose=False,
        )

        row = TravelRequestPurposeService.create(
            data={
                "request": request,
                "purpose": purpose,
                "start_date": WINDOW_START,
                "end_date": WINDOW_END,
            },
        )

        request.refresh_from_db()

        return request, row

    @staticmethod
    def make_balance(employee, leave_type) -> LeaveBalance:
        return LeaveBalance.objects.create(
            employee=employee,
            leave_type=leave_type,
            year=WINDOW_YEAR,
            entitlement=Decimal("12.0"),
        )

    @staticmethod
    def approve(request):
        """
        Keadaan yang `on_workflow_done` tinggalkan saat alurnya
        disetujui, tanpa ikut mengirim pemberitahuannya: status
        APPROVED lalu penerbitan catatan cuti. Yang diuji berkas ini
        pembatalannya, bukan alur persetujuannya — itu punya testnya
        sendiri.
        """
        request.status = TravelRequestStatus.APPROVED
        request.save(update_fields=["status", "updated_at"])

        TravelRequestService.issue_leave_records(request=request)

        request.refresh_from_db()

        return request

    def approved_with_leave(self):
        """TR APPROVED + satu catatan cuti terbitannya + kartu saldo."""
        leave_type, purpose = self.make_leave_kind()

        request, row = self.make_deducting_request(purpose=purpose)

        balance = self.make_balance(request.employee, leave_type)

        self.approve(request)

        row.refresh_from_db()
        balance.refresh_from_db()

        # Prasyarat, bukan yang diuji: kalau salah satunya meleset,
        # seluruh assertion pembatalan di bawah jadi tidak bermakna.
        self.assertIsNotNone(row.employee_leave_id)
        self.assertTrue(row.leave_issued)
        self.assertGreater(balance.used, Decimal("0.0"))

        return request, row, balance


# ----------------------------------------------------------------------
# 1–2 — dokumen yang disetujui bisa dibatalkan, dan berhenti di CANCELLED
# ----------------------------------------------------------------------


class CancelApprovedRequestTests(CancelTestBase):
    def test_approved_request_can_be_cancelled(self):
        request, _row, _balance = self.approved_with_leave()

        TravelRequestService.cancel(request=request)

        request.refresh_from_db()

        self.assertEqual(request.status, TravelRequestStatus.CANCELLED)

    def test_cancelled_request_is_not_editable_and_cannot_be_resubmitted(self):
        """
        CANCELLED adalah akhir, bukan singgahan.

        Kalau dokumennya masih bisa diajukan ulang, `issue_leave_records`
        akan melewati barisnya (`employee_leave_id` masih terisi) dan
        perjalanannya jalan lagi dengan cuti yang sudah dibatalkan —
        dokumen approved yang saldonya tidak terpotong.
        """
        request, _row, _balance = self.approved_with_leave()

        TravelRequestService.cancel(request=request)

        request.refresh_from_db()

        self.assertFalse(request.is_editable)

        with self.assertRaises(ValidationError) as caught:
            TravelRequestService.submit(request=request)

        self.assertIn("status", caught.exception.message_dict)


# ----------------------------------------------------------------------
# 3–5 — catatan cutinya dicabut lewat Leave service, bukan dihapus
# ----------------------------------------------------------------------


class CancelIssuedLeaveTests(CancelTestBase):
    def test_issued_leave_is_cancelled_not_deleted(self):
        request, row, _balance = self.approved_with_leave()

        leave_pk = row.employee_leave_id

        TravelRequestService.cancel(request=request)

        leave = EmployeeLeave.objects.get(pk=leave_pk)

        self.assertEqual(leave.status, LeaveStatus.CANCELLED)

        # Hard delete akan membuat kartu cuti orang ini kehilangan
        # jejak bahwa cutinya pernah terbit sama sekali.
        self.assertFalse(leave.is_deleted)

    def test_leave_document_number_survives_the_cancellation(self):
        """
        Nomor LV tidak dilepas dan tidak dipakai ulang.

        Deret nomor dokumen tidak boleh berlubang dan tidak boleh
        punya dua pemilik; catatan yang dibatalkan tetap memegang
        nomornya sendiri.
        """
        request, row, _balance = self.approved_with_leave()

        leave = row.employee_leave
        number_before = leave.document_number

        self.assertTrue(number_before)

        TravelRequestService.cancel(request=request)

        leave.refresh_from_db()

        self.assertEqual(leave.document_number, number_before)

    def test_link_between_purpose_and_leave_is_kept(self):
        """
        Tautannya justru jejak yang harus tersimpan: "cuti ini pernah
        terbit dari TR ini, lalu dibatalkan".
        """
        request, row, _balance = self.approved_with_leave()

        leave_pk = row.employee_leave_id

        TravelRequestService.cancel(request=request)

        row.refresh_from_db()

        self.assertEqual(row.employee_leave_id, leave_pk)
        self.assertTrue(row.leave_issued)

    def test_balance_returns_after_cancellation(self):
        """
        Saldo pulih karena `EmployeeLeaveService.set_status`
        menjumlahkan ulang kartunya — bukan karena ada yang
        mengurangi `used` dengan tangan.
        """
        request, row, balance = self.approved_with_leave()

        used_while_approved = balance.used

        self.assertEqual(used_while_approved, row.employee_leave.total_days)

        TravelRequestService.cancel(request=request)

        balance.refresh_from_db()

        self.assertEqual(balance.used, Decimal("0.0"))
        self.assertEqual(balance.advance_used, Decimal("0.0"))

    def test_adopted_leave_of_hr_is_not_cancelled(self):
        """
        Catatan cuti yang sudah lebih dulu dicatat HR cuma **diadopsi**
        `issue_leave_records`, tidak diterbitkannya.

        Membatalkannya karena dokumen perjalanan batal akan
        mengembalikan saldo untuk cuti yang benar-benar diambil —
        salah yang paling mahal di berkas ini, dan yang paling sulit
        ketahuan.
        """
        leave_type, purpose = self.make_leave_kind()

        request, row = self.make_deducting_request(purpose=purpose)

        existing = EmployeeLeaveService.create(
            data={
                "employee": request.employee,
                "leave_type": leave_type,
                "start_date": WINDOW_START,
                "end_date": WINDOW_END,
                "total_days": Decimal("5"),
                "status": LeaveStatus.RECORDED,
            },
        )

        self.approve(request)

        row.refresh_from_db()

        # Diadopsi, bukan diterbitkan.
        self.assertEqual(row.employee_leave_id, existing.pk)
        self.assertFalse(row.leave_issued)

        TravelRequestService.cancel(request=request)

        existing.refresh_from_db()
        request.refresh_from_db()

        self.assertEqual(request.status, TravelRequestStatus.CANCELLED)
        self.assertEqual(existing.status, LeaveStatus.RECORDED)


# ----------------------------------------------------------------------
# 6 — pemanggilan ulang tidak menyentuh apa pun lagi
# ----------------------------------------------------------------------


class CancelIdempotencyTests(CancelTestBase):
    def test_second_cancel_changes_nothing(self):
        request, row, balance = self.approved_with_leave()

        TravelRequestService.cancel(request=request)

        request.refresh_from_db()
        row.refresh_from_db()
        balance.refresh_from_db()

        leave = row.employee_leave
        leave_touched_at = leave.updated_at

        leave_count = EmployeeLeave.objects.filter(
            employee=request.employee,
        ).count()

        TravelRequestService.cancel(request=request)

        request.refresh_from_db()
        balance.refresh_from_db()
        leave.refresh_from_db()

        self.assertEqual(request.status, TravelRequestStatus.CANCELLED)
        self.assertEqual(leave.status, LeaveStatus.CANCELLED)

        # Tidak ada catatan cuti baru, dan saldonya tidak dikoreksi
        # dua kali.
        self.assertEqual(
            EmployeeLeave.objects.filter(employee=request.employee).count(),
            leave_count,
        )
        self.assertEqual(balance.used, Decimal("0.0"))

        # Dan catatan cutinya tidak ditulis ulang — pembatalan yang
        # sudah selesai tidak boleh memindahkan `updated_by` tiap kali
        # tombolnya tertekan.
        self.assertEqual(leave.updated_at, leave_touched_at)


# ----------------------------------------------------------------------
# 7 — dokumen yang belum memenuhi syarat tidak boleh lewat sini
# ----------------------------------------------------------------------


class CancelGuardTests(CancelTestBase):
    def _at(self, status):
        request = self.make_request()

        request.status = status
        request.save(update_fields=["status", "updated_at"])

        return request

    def test_draft_cannot_use_this_path(self):
        request = self._at(TravelRequestStatus.DRAFT)

        with self.assertRaises(ValidationError) as caught:
            TravelRequestService.cancel(request=request)

        self.assertIn("status", caught.exception.message_dict)

        request.refresh_from_db()

        self.assertEqual(request.status, TravelRequestStatus.DRAFT)

    def test_submitted_cannot_use_this_path(self):
        """
        Yang masih menunggu ditarik lewat Withdraw: alurnya masih
        terbuka, dan menutupnya lewat sini meninggalkan pengajuan
        berjalan yang dokumennya sudah selesai.
        """
        request = self._at(TravelRequestStatus.SUBMITTED)

        with self.assertRaises(ValidationError):
            TravelRequestService.cancel(request=request)

        request.refresh_from_db()

        self.assertEqual(request.status, TravelRequestStatus.SUBMITTED)

    def test_rejected_cannot_use_this_path(self):
        request = self._at(TravelRequestStatus.REJECTED)

        with self.assertRaises(ValidationError):
            TravelRequestService.cancel(request=request)

        request.refresh_from_db()

        self.assertEqual(request.status, TravelRequestStatus.REJECTED)


# ----------------------------------------------------------------------
# Sambungan ke B7 — blok jadwalnya bebas lagi
# ----------------------------------------------------------------------


class CancelReleasesTheRosterBlockTests(CancelTestBase):
    """
    `test_cancelled_does_not_block` di `test_from_rotation_period`
    memaksa statusnya lewat ORM, karena saat B7 ditulis belum ada kode
    yang pernah menyetel CANCELLED. Yang ini menempuh jalurnya
    sungguhan: `cancel()` yang menyetelnya, lalu blok jadwal yang sama
    diajukan ulang.
    """

    def test_new_request_can_be_made_after_cancellation(self):
        employee = self.make_employee()
        rotation = self.make_rotation(employee)
        _, off = self.make_periods(rotation)

        first = TravelRequestService.build_from_period(period=off)

        first.status = TravelRequestStatus.APPROVED
        first.save(update_fields=["status", "updated_at"])

        # Blok off pabrik ini berpurpose Field Break — tidak memotong
        # saldo, jadi tidak ada catatan cuti yang ikut dicabut. Yang
        # diuji di sini memang cuma pelepasan bloknya.
        TravelRequestService.cancel(request=first)

        first.refresh_from_db()

        self.assertEqual(first.status, TravelRequestStatus.CANCELLED)

        second = TravelRequestService.build_from_period(period=off)

        self.assertNotEqual(second.pk, first.pk)
        self.assertEqual(second.rotation_period_id, off.pk)
