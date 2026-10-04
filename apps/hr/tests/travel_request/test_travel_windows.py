"""
Regression Tahap 2: jendela travel dan anchor pengingat keberangkatan.

Keduanya jenis kesalahan yang sama — sebuah tanggal dihitung ulang di
tempat kedua, lalu melenceng dari tempat pertama tanpa ada yang
melemparkan error. Yang diuji di sini bukan "ada barisnya", melainkan
**tanggalnya sama persis dengan yang dipakai jadwal**.
"""

from __future__ import annotations

from datetime import date, timedelta

from django.core.exceptions import ValidationError

from apps.hr.api.site_rotation.services import (
    inbound_travel_window,
    outbound_travel_window,
)
from apps.hr.api.travel_request.services import (
    TravelArrangementService,
    TravelRequestService,
)
from apps.hr.models import (
    RosterSegmentType,
    RotationPeriod,
    RotationPeriodType,
    TravelDirection,
    TravelRequestStatus,
)
from apps.hr.reminders import travel as travel_reminders

from .base import AS_OF, TravelRequestTestCase


class TravelWindowTests(TravelRequestTestCase):
    """B2 — jendela travel dibaca dari jadwal, bukan dihitung ulang."""

    def test_window_splits_round_trip_total(self):
        """
        `cycle_travel_days` adalah total pulang-pergi. 2 = sehari
        keluar, sehari kembali — bukan dua hari di masing-masing arah.
        """
        employee = self.make_employee()
        rotation = self.make_rotation(employee, travel_days=2)
        work, off = self.make_periods(rotation)

        self.assertEqual(
            outbound_travel_window(off),
            (work.end_date + timedelta(days=1),) * 2,
        )

        self.assertEqual(
            inbound_travel_window(off),
            (off.end_date + timedelta(days=1),) * 2,
        )

    def test_odd_total_leans_to_the_outbound_side(self):
        """
        3 hari PP = 2 keluar + 1 kembali. Aturan #4 dokumen klien:
        perjalanan Sorong/Ternate → site sudah dihitung On Site,
        sehingga sisi kembali memang lebih pendek.
        """
        employee = self.make_employee()
        rotation = self.make_rotation(employee, travel_days=3)
        work, off = self.make_periods(rotation)

        outbound = outbound_travel_window(off)
        inbound = inbound_travel_window(off)

        self.assertEqual(
            (outbound[1] - outbound[0]).days + 1,
            2,
        )

        self.assertEqual(
            (inbound[1] - inbound[0]).days + 1,
            1,
        )

    def test_no_travel_days_means_no_window(self):
        """Pegawai lokal: nol hari perjalanan, nol baris."""
        employee = self.make_employee()
        rotation = self.make_rotation(employee, travel_days=0)
        _, off = self.make_periods(rotation)

        self.assertIsNone(outbound_travel_window(off))
        self.assertIsNone(inbound_travel_window(off))

    def test_actual_travel_segment_rows_win(self):
        """
        Jalur roster baru menulis `TRAVEL_OUT`/`TRAVEL_IN` sebagai baris
        tersendiri. Tanggal yang sudah tercatat itu yang dipakai, bukan
        properti turunan yang menghitung ulang dari pola.
        """
        employee = self.make_employee()
        rotation = self.make_rotation(employee, travel_days=2)
        work, off = self.make_periods(rotation)

        # Pita perjalanan yang tanggalnya digeser tangan — persis
        # keadaan yang membuat menghitung ulang jadi salah.
        band_start = work.end_date + timedelta(days=1)

        RotationPeriod.objects.create(
            rotation=rotation,
            employee=employee,
            sequence=10,
            period_type=RotationPeriodType.OFF,
            segment_type=RosterSegmentType.TRAVEL_OUT,
            start_date=band_start,
            end_date=off.start_date - timedelta(days=1),
            total_days=(off.start_date - band_start).days,
            cycle_number=1,
        )

        self.assertEqual(
            outbound_travel_window(off),
            (band_start, off.start_date - timedelta(days=1)),
        )

    def test_first_block_without_predecessor_has_no_outbound_window(self):
        employee = self.make_employee()
        rotation = self.make_rotation(employee, travel_days=2)

        orphan = RotationPeriod.objects.create(
            rotation=rotation,
            employee=employee,
            sequence=1,
            period_type=RotationPeriodType.OFF,
            segment_type=RosterSegmentType.FIELD_BREAK,
            start_date=AS_OF,
            end_date=AS_OF + timedelta(days=13),
            total_days=14,
            cycle_number=1,
        )

        self.assertIsNone(outbound_travel_window(orphan))


class BuildFromPeriodTests(TravelRequestTestCase):
    """B2 — TR yang lahir dari jadwal memakai tanggal jadwal itu."""

    def _built(self, *, travel_days=2):
        employee = self.make_employee()
        rotation = self.make_rotation(employee, travel_days=travel_days)
        work, off = self.make_periods(rotation)

        request = TravelRequestService.build_from_period(period=off)

        return work, off, request

    def test_outbound_leg_does_not_eat_the_last_work_day(self):
        """
        Inti cacatnya. Dengan `cycle_travel_days` dipakai utuh untuk
        satu arah, etape keluar mundur sampai ke hari kerja terakhir —
        dokumen TR menyatakan orangnya berangkat pada hari yang menurut
        jadwal masih di site.
        """
        work, _, request = self._built()

        outbound = request.travels.get(direction=TravelDirection.OUTBOUND)

        self.assertGreater(outbound.travel_start_date, work.end_date)

        self.assertEqual(
            outbound.travel_start_date,
            work.end_date + timedelta(days=1),
        )

    def test_legs_match_the_schedule_windows_exactly(self):
        work, off, request = self._built()

        outbound = request.travels.get(direction=TravelDirection.OUTBOUND)
        inbound = request.travels.get(direction=TravelDirection.INBOUND)

        self.assertEqual(
            (outbound.travel_start_date, outbound.arrival_date),
            outbound_travel_window(off),
        )

        self.assertEqual(
            (inbound.travel_start_date, inbound.arrival_date),
            inbound_travel_window(off),
        )

    def test_single_day_leg_leaves_arrival_empty(self):
        """
        "Dikosongkan = tiba di hari yang sama" adalah arti kolomnya.
        Mengisinya dengan tanggal yang sama membuat perjalanan sehari
        terbaca seperti tanggal tibanya sudah dipastikan.
        """
        _, _, request = self._built()

        inbound = request.travels.get(direction=TravelDirection.INBOUND)

        self.assertIsNone(inbound.travel_end_date)
        self.assertEqual(inbound.arrival_date, inbound.travel_start_date)

    def test_two_day_outbound_keeps_its_arrival_date(self):
        work, _, request = self._built(travel_days=3)

        outbound = request.travels.get(direction=TravelDirection.OUTBOUND)

        self.assertEqual(
            outbound.travel_start_date,
            work.end_date + timedelta(days=1),
        )

        self.assertEqual(
            outbound.travel_end_date,
            work.end_date + timedelta(days=2),
        )

    def test_no_travel_days_creates_no_leg(self):
        _, _, request = self._built(travel_days=0)

        self.assertEqual(request.travels.filter(is_deleted=False).count(), 0)

    def test_route_endpoints_come_from_master(self):
        _, _, request = self._built()

        outbound = request.travels.get(direction=TravelDirection.OUTBOUND)
        inbound = request.travels.get(direction=TravelDirection.INBOUND)

        self.assertEqual(outbound.origin, self.site.name)
        self.assertEqual(outbound.destination, self.point_of_hire.name)

        self.assertEqual(inbound.origin, self.point_of_hire.name)
        self.assertEqual(inbound.destination, self.site.name)

    def test_work_block_is_rejected(self):
        employee = self.make_employee()
        rotation = self.make_rotation(employee)
        work, _ = self.make_periods(rotation)

        with self.assertRaises(ValidationError) as caught:
            TravelRequestService.build_from_period(period=work)

        self.assertIn("rotation_period", caught.exception.message_dict)

    def test_travel_band_is_rejected(self):
        """
        Pita perjalanan jalur baru ber-`period_type` OFF juga, jadi
        memeriksa kolom itu saja akan menerbitkan TR untuk kepulangan
        yang tidak pernah ada.
        """
        employee = self.make_employee()
        rotation = self.make_rotation(employee)
        work, off = self.make_periods(rotation)

        band = RotationPeriod.objects.create(
            rotation=rotation,
            employee=employee,
            sequence=10,
            period_type=RotationPeriodType.OFF,
            segment_type=RosterSegmentType.TRAVEL_OUT,
            start_date=work.end_date + timedelta(days=1),
            end_date=work.end_date + timedelta(days=1),
            total_days=1,
            cycle_number=1,
        )

        with self.assertRaises(ValidationError):
            TravelRequestService.build_from_period(period=band)


class DepartureAnchorTests(TravelRequestTestCase):
    """B5 — yang diingatkan tanggal berangkat, bukan awal blok off."""

    def _approved_with_legs(self, *, departure, off_start):
        request = self.make_request(
            start_date=off_start,
            end_date=off_start + timedelta(days=13),
        )

        TravelArrangementService.create(
            data={
                "request": request,
                "direction": TravelDirection.OUTBOUND,
                "travel_start_date": departure,
                "travel_end_date": off_start - timedelta(days=1),
                "origin": "Gebe",
                "destination": "Jakarta",
            },
        )

        request.status = TravelRequestStatus.APPROVED
        request.save(update_fields=["status", "updated_at"])

        request.refresh_from_db()

        return request

    def test_departure_date_reads_the_first_outbound_leg(self):
        off_start = date(2026, 11, 10)

        request = self._approved_with_legs(
            departure=date(2026, 11, 7),
            off_start=off_start,
        )

        self.assertEqual(request.departure_date, date(2026, 11, 7))
        self.assertNotEqual(request.departure_date, request.start_date)

    def test_departure_date_falls_back_to_off_start(self):
        """TR sah disetujui sebelum tiketnya dibeli."""
        request = self.make_request(
            start_date=date(2026, 11, 10),
            end_date=date(2026, 11, 23),
        )

        self.assertEqual(request.departure_date, date(2026, 11, 10))

    def test_earliest_outbound_leg_wins(self):
        """
        Rute bersambung: Gebe → Sorong lalu Sorong → Jakarta, dan arah
        pulang di belakangnya. Yang dipakai etape yang berangkat paling
        awal — bukan etape bernomor 1, karena nomor etape diisi
        belakangan dan bisa saja disisipkan.

        Barisnya ditambahkan selagi dokumen masih DRAFT: sejak baris
        anak dijaga `assert_editable`, etape memang tidak bisa lagi
        disisipkan ke dokumen yang sudah disetujui.
        """
        request = self.make_request(
            start_date=date(2026, 11, 10),
            end_date=date(2026, 11, 23),
        )

        for sequence, (departure, origin, destination) in enumerate(
            (
                (date(2026, 11, 8), "Sorong", "Jakarta"),
                (date(2026, 11, 7), "Gebe", "Sorong"),
            ),
            start=1,
        ):
            TravelArrangementService.create(
                data={
                    "request": request,
                    "direction": TravelDirection.OUTBOUND,
                    "sequence": sequence,
                    "travel_start_date": departure,
                    "origin": origin,
                    "destination": destination,
                },
            )

        TravelArrangementService.create(
            data={
                "request": request,
                "direction": TravelDirection.INBOUND,
                "travel_start_date": date(2026, 11, 24),
                "origin": "Jakarta",
                "destination": "Gebe",
            },
        )

        request.refresh_from_db()

        self.assertEqual(request.departure_date, date(2026, 11, 7))

    # `TenantTestCase` tidak me-rollback antar test, jadi dokumen milik
    # test sebelumnya ikut terbaca pemindai pengingat. Karena itu tiap
    # test di bawah memakai **tanggal acuan sendiri** yang membuat
    # dokumen test lain jatuh di luar jendela pencarian — bukan
    # bersandar pada database yang kebetulan kosong.

    def test_reminder_counts_down_to_the_departure(self):
        """
        Dulu `days_left` dihitung dari awal blok off, jadi pengingat
        H-7 terkirim tiga hari setelah orangnya berangkat.
        """
        today = date(2026, 11, 1)

        self._approved_with_legs(
            departure=today + timedelta(days=7),
            off_start=today + timedelta(days=10),
        )

        stats = travel_reminders.run(today=today, dry_run=True)

        self.assertEqual(stats["notified"], 1)

    def test_reminder_stays_silent_on_the_old_anchor(self):
        """
        Hari yang **dulu** memicu pengingat sekarang tidak boleh
        memicunya: H-7 dari awal blok off berarti H-4 dari
        keberangkatan, dan orangnya berangkat empat hari lagi bukan
        tujuh.
        """
        today = date(2026, 12, 1)

        self._approved_with_legs(
            departure=today + timedelta(days=4),
            off_start=today + timedelta(days=7),
        )

        stats = travel_reminders.run(today=today, dry_run=True)

        self.assertEqual(stats["checked"], 1)
        self.assertEqual(stats["notified"], 0)

    def test_reminder_defaults_today_to_localdate(self):
        """
        `date.today()` memakai zona waktu proses; worker Celery yang
        jalan UTC menganggap hari baru dimulai jam tujuh pagi WIT.
        Tanpa `today=` yang eksplisit, pemindainya harus tetap
        menemukan dokumen yang berangkat H-`DEFAULT_LEAD_DAYS`.
        """
        from django.utils import timezone

        today = timezone.localdate()

        self._approved_with_legs(
            departure=today + timedelta(
                days=travel_reminders.DEFAULT_LEAD_DAYS,
            ),
            off_start=today + timedelta(
                days=travel_reminders.DEFAULT_LEAD_DAYS + 3,
            ),
        )

        stats = travel_reminders.run(dry_run=True)

        self.assertEqual(stats["notified"], 1)

    def test_only_approved_documents_are_reminded(self):
        """
        "Berangkat 7 hari lagi" untuk perjalanan yang masih bisa
        ditolak membuat pengingatnya tidak bisa dipercaya.
        """
        today = date(2027, 1, 4)

        request = self._approved_with_legs(
            departure=today + timedelta(days=7),
            off_start=today + timedelta(days=10),
        )

        request.status = TravelRequestStatus.SUBMITTED
        request.save(update_fields=["status", "updated_at"])

        stats = travel_reminders.run(today=today, dry_run=True)

        self.assertEqual(stats["checked"], 0)
        self.assertEqual(stats["notified"], 0)

    def test_notification_context_uses_the_real_departure(self):
        from apps.hr.api.travel_request import notifications

        request = self._approved_with_legs(
            departure=date(2026, 11, 7),
            off_start=date(2026, 11, 10),
        )

        context = notifications._context(request, days_left=7)

        self.assertEqual(context["departure_date"], "07 November 2026")
        self.assertEqual(context["origin"], "Gebe")
        self.assertEqual(context["destination"], "Jakarta")
