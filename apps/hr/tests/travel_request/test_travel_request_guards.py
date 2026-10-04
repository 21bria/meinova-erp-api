"""
Regression Tahap 1: pagar penyuntingan, rekap, dan isi pemberitahuan.

Empat cacat yang ditutup di sini semuanya gagal **tanpa suara** —
tidak ada satu pun yang melempar error, memunculkan log, atau membuat
layar terlihat salah. Itu sebabnya masing-masing dapat testnya sendiri:
yang tidak berbunyi hanya bisa dijaga oleh test.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.core.exceptions import ValidationError

from apps.hr.api.travel_request import notifications as travel_notifications
from apps.hr.api.travel_request.services import (
    TravelArrangementService,
    TravelRequestPurposeService,
    TravelRequestService,
)
from apps.hr.models import (
    TravelDirection,
    TravelRequestStatus,
)

from .base import TravelRequestTestCase


class TravelRequestRouteTests(TravelRequestTestCase):
    """B1 — asal dan tujuan dibaca dari relasi yang benar."""

    def _with_legs(self):
        request = self.make_request()

        TravelArrangementService.create(
            data={
                "request": request,
                "direction": TravelDirection.OUTBOUND,
                "travel_start_date": date(2026, 10, 11),
                "origin": "Gebe",
                "destination": "Sorong",
            },
        )

        TravelArrangementService.create(
            data={
                "request": request,
                "direction": TravelDirection.OUTBOUND,
                "travel_start_date": date(2026, 10, 12),
                "origin": "Sorong",
                "destination": "Jakarta",
            },
        )

        TravelArrangementService.create(
            data={
                "request": request,
                "direction": TravelDirection.INBOUND,
                "travel_start_date": date(2026, 10, 27),
                "origin": "Jakarta",
                "destination": "Gebe",
            },
        )

        return request

    def test_route_reads_first_and_last_outbound_leg(self):
        """
        Rutenya bersambung, jadi asalnya dari etape pertama dan
        tujuannya dari etape terakhir arah keluar — bukan dari satu
        baris yang sama.
        """
        request = self._with_legs()

        origin, destination = travel_notifications._route(request)

        self.assertEqual(origin, "Gebe")
        self.assertEqual(destination, "Jakarta")

    def test_context_carries_route(self):
        """
        Inti cacatnya. `request.arrangements` tidak pernah ada —
        related name-nya `travels` — dan `except Exception` di dalam
        `_route` menelan `AttributeError`-nya, jadi setiap surat
        terkirim dengan asal dan tujuan kosong tanpa satu pun log.
        """
        request = self._with_legs()

        context = travel_notifications._context(request)

        self.assertEqual(context["origin"], "Gebe")
        self.assertEqual(context["destination"], "Jakarta")

    def test_route_is_empty_when_no_leg_typed_yet(self):
        """TR boleh disetujui sebelum tiketnya dibeli."""
        request = self.make_request()

        self.assertEqual(travel_notifications._route(request), ("", ""))

    def test_route_falls_back_to_inbound_origin(self):
        """Baru arah pulang yang diketik: asalnya tetap terbaca."""
        request = self.make_request()

        TravelArrangementService.create(
            data={
                "request": request,
                "direction": TravelDirection.INBOUND,
                "travel_start_date": date(2026, 10, 27),
                "origin": "Jakarta",
                "destination": "Gebe",
            },
        )

        origin, destination = travel_notifications._route(request)

        self.assertEqual(origin, "Jakarta")
        self.assertEqual(destination, "")

    def test_soft_deleted_leg_is_ignored(self):
        request = self._with_legs()

        first = request.travels.order_by("sequence").first()

        TravelArrangementService.soft_delete(instance=first)

        origin, _ = travel_notifications._route(request)

        self.assertEqual(origin, "Sorong")


class TravelRequestChildEditGuardTests(TravelRequestTestCase):
    """B3 — baris baru tidak boleh disisipkan ke dokumen berjalan."""

    def _locked(self, status):
        request = self.make_request()

        request.status = status
        request.save(update_fields=["status", "updated_at"])

        return request

    def test_purpose_cannot_be_added_to_submitted_request(self):
        request = self._locked(TravelRequestStatus.SUBMITTED)

        with self.assertRaises(ValidationError) as caught:
            TravelRequestPurposeService.create(
                data={
                    "request": request,
                    "purpose": self.annual_leave,
                    "start_date": date(2026, 10, 20),
                    "end_date": date(2026, 10, 26),
                },
            )

        self.assertIn("status", caught.exception.message_dict)

    def test_purpose_cannot_be_added_to_approved_request(self):
        """
        Yang paling merugikan dari dua-duanya: baris yang menambah
        potongan saldo disisipkan **setelah** enam meja menandatangani
        isi yang berbeda.
        """
        request = self._locked(TravelRequestStatus.APPROVED)

        with self.assertRaises(ValidationError):
            TravelRequestPurposeService.create(
                data={
                    "request": request,
                    "purpose": self.annual_leave,
                    "start_date": date(2026, 10, 20),
                    "end_date": date(2026, 10, 26),
                },
            )

    def test_arrangement_cannot_be_added_to_submitted_request(self):
        request = self._locked(TravelRequestStatus.SUBMITTED)

        with self.assertRaises(ValidationError):
            TravelArrangementService.create(
                data={
                    "request": request,
                    "direction": TravelDirection.OUTBOUND,
                    "travel_start_date": date(2026, 10, 11),
                },
            )

    def test_draft_and_rejected_still_accept_rows(self):
        """
        Pagarnya tidak boleh menutup jalur perbaikan: dokumen yang
        ditolak memang harus bisa disunting lalu diajukan ulang.
        """
        for status in (
            TravelRequestStatus.DRAFT,
            TravelRequestStatus.REJECTED,
        ):
            with self.subTest(status=status):
                request = self._locked(status)

                leg = TravelArrangementService.create(
                    data={
                        "request": request,
                        "direction": TravelDirection.OUTBOUND,
                        "travel_start_date": date(2026, 10, 11),
                    },
                )

                self.assertIsNotNone(leg.pk)


class TravelRequestResubmitGuardTests(TravelRequestTestCase):
    """B4 — dokumen yang sudah selesai tidak boleh diajukan lagi."""

    def test_approved_request_cannot_be_submitted_again(self):
        """
        `WorkflowService.submit` hanya menolak instance yang masih
        terbuka. Dokumen APPROVED instance-nya sudah ditutup, jadi
        tanpa `assert_editable` pengajuan kedua terbentuk mulus dan
        statusnya mundur APPROVED → SUBMITTED.
        """
        request = self.make_request()

        request.status = TravelRequestStatus.APPROVED
        request.save(update_fields=["status", "updated_at"])

        with self.assertRaises(ValidationError) as caught:
            TravelRequestService.submit(request=request)

        self.assertIn("status", caught.exception.message_dict)

        request.refresh_from_db()

        self.assertEqual(request.status, TravelRequestStatus.APPROVED)

    def test_submitted_request_cannot_be_submitted_again(self):
        request = self.make_request()

        request.status = TravelRequestStatus.SUBMITTED
        request.save(update_fields=["status", "updated_at"])

        with self.assertRaises(ValidationError):
            TravelRequestService.submit(request=request)

    def test_editable_document_passes_the_guard_and_fails_later(self):
        """
        Penjagaan baru tidak boleh menggantikan penjagaan lama.
        Dokumen DRAFT tanpa baris tujuan harus tetap ditolak dengan
        pesan tentang **Travel Purpose**, bukan tentang status.
        """
        request = self.make_request(with_purpose=False)

        with self.assertRaises(ValidationError) as caught:
            TravelRequestService.submit(request=request)

        self.assertIn("purposes", caught.exception.message_dict)


class TravelRequestSyncTotalsTests(TravelRequestTestCase):
    """B6 — rekap ikut turun saat baris tujuan terakhir dihapus."""

    def test_totals_follow_the_purpose_rows(self):
        request = self.make_request(
            start_date=date(2026, 10, 13),
            end_date=date(2026, 10, 26),
        )

        self.assertEqual(request.total_days, 14)

    def test_totals_reset_when_last_purpose_is_deleted(self):
        """
        Dulu `sync_totals` keluar lebih awal saat barisnya habis, jadi
        `total_days` tertinggal memakai angka baris yang sudah tidak
        ada — dokumen kosong yang tetap melaporkan 14 hari di kolom
        tabel yang bisa disortir.
        """
        request = self.make_request()

        self.assertEqual(request.total_days, 14)

        purpose = request.purposes.filter(is_deleted=False).first()

        TravelRequestPurposeService.soft_delete(instance=purpose)

        request.refresh_from_db()

        self.assertIsNone(request.total_days)

    def test_remaining_purpose_still_drives_the_range(self):
        """
        Menghapus satu dari dua baris merapatkan rentang ke yang
        tersisa, bukan mengosongkannya.
        """
        request = self.make_request(
            start_date=date(2026, 10, 13),
            end_date=date(2026, 10, 19),
        )

        TravelRequestPurposeService.create(
            data={
                "request": request,
                "purpose": self.annual_leave,
                "start_date": date(2026, 10, 20),
                "end_date": date(2026, 10, 26),
            },
        )

        request.refresh_from_db()

        self.assertEqual(request.total_days, 14)
        self.assertEqual(request.end_date, date(2026, 10, 26))

        second = (
            request.purposes
            .filter(is_deleted=False)
            .order_by("-start_date")
            .first()
        )

        TravelRequestPurposeService.soft_delete(instance=second)

        request.refresh_from_db()

        self.assertEqual(request.total_days, 7)
        self.assertEqual(request.end_date, date(2026, 10, 19))

    def test_reset_falls_back_to_the_roster_block(self):
        """
        Kalau dokumennya menunjuk blok jadwal, rentangnya kembali ke
        sana — itu asal-usulnya sebelum baris tujuan diketik.
        """
        employee = self.make_employee()
        rotation = self.make_rotation(employee)
        _, off = self.make_periods(rotation)

        request = TravelRequestService.create(
            data={
                "employee": employee,
                "company": self.company,
                "location": self.site,
                "rotation_period": off,
            },
        )

        TravelRequestPurposeService.create(
            data={
                "request": request,
                "purpose": self.field_break,
                "start_date": off.start_date,
                "end_date": off.start_date + timedelta(days=3),
            },
        )

        request.refresh_from_db()

        self.assertEqual(request.end_date, off.start_date + timedelta(days=3))

        purpose = request.purposes.filter(is_deleted=False).first()

        TravelRequestPurposeService.soft_delete(instance=purpose)

        request.refresh_from_db()

        self.assertIsNone(request.total_days)
        self.assertEqual(request.start_date, off.start_date)
        self.assertEqual(request.end_date, off.end_date)
