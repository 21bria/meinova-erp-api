"""
TR/BT POLICY-1 — applicability dokumen perjalanan dan batas perjalanan
fisik.

Yang dikunci di sini:

* resolver turunan empat keadaan (`travel_document`) dari dua penanda
  Employee Group yang sudah ada — tanpa master, kolom, atau enum baru;
* kelayakan Travel Request dan Business Trip di jalur create **dan**
  submit, termasuk group yang berubah di antara keduanya;
* penjagaan timbal balik TR↔BT memakai rentang **perjalanan fisik** TR
  (etape keluar s/d etape pulang), jatuh ke blok off tanpa itinerary;
* penjagaan itu tetap jalan untuk `BOTH`, dokumen lama, dan pegawai yang
  group-nya berganti;
* menu Travel Request / Business Trip: `test_menu_visibility_semantics.py`
  (POLICY-1A).
"""

from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from apps.administration.api.reference.hr.serializers.hr import (
    EmployeeGroupSerializer,
)
from apps.administration.models import RotationPurpose
from apps.administration.models.references.hr import EmployeeGroup
from apps.hr import applicability
from apps.hr.api.business_trip.services import BusinessTripService
from apps.hr.api.travel_request.services import TravelRequestService
from apps.hr.models import (
    BusinessTripStatus,
    TravelArrangement,
    TravelDirection,
    TravelRequestPurpose,
    TravelRequestStatus,
)

from .base import FAR, BusinessTripTestCase


# Blok off TR yang diuji: FIRST..LAST.
FIRST = FAR
LAST = FAR + timedelta(days=4)


def fake_group(*, field_break: bool, business_trip: bool):
    """Group tak tersimpan — resolver cuma membaca dua penandanya."""
    return EmployeeGroup(
        code="X",
        name="X",
        field_break_applicable=field_break,
        business_trip_applicable=business_trip,
    )


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


class TravelDocumentResolverContract(SimpleTestCase):
    def test_four_states_from_the_two_existing_flags(self):
        cases = {
            (True, False): applicability.TRAVEL_REQUEST,
            (False, True): applicability.BUSINESS_TRIP,
            (True, True): applicability.BOTH,
            (False, False): applicability.NONE,
        }

        for (field_break, business_trip), expected in cases.items():
            with self.subTest(field_break=field_break, business_trip=business_trip):
                group = fake_group(
                    field_break=field_break,
                    business_trip=business_trip,
                )

                self.assertEqual(
                    applicability.group_travel_document(group),
                    expected,
                )

                employee = SimpleNamespace(
                    employment=SimpleNamespace(employee_group=group),
                )

                self.assertEqual(
                    applicability.travel_document(employee),
                    expected,
                )

    def test_unconfigured_is_both(self):
        """Tanpa group / tanpa employment = seperti sebelum resolver ada."""
        self.assertEqual(
            applicability.group_travel_document(None),
            applicability.BOTH,
        )
        self.assertEqual(
            applicability.travel_document(
                SimpleNamespace(employment=SimpleNamespace(employee_group=None)),
            ),
            applicability.BOTH,
        )
        self.assertEqual(
            applicability.travel_document(SimpleNamespace(employment=None)),
            applicability.BOTH,
        )

    def test_default_group_is_both(self):
        """Kedua penanda `default=True`: group yang belum disentuh = BOTH."""
        self.assertEqual(
            applicability.group_travel_document(EmployeeGroup(code="D", name="D")),
            applicability.BOTH,
        )

    def test_warning_messages_keep_canonical_meaning(self):
        """POLICY-2C: BOTH sah — dua dokumen untuk tujuannya masing-masing,
        bukan galat dan bukan perintah mematikan salah satunya."""
        both = applicability.travel_document_warnings(
            fake_group(field_break=True, business_trip=True),
        )
        none = applicability.travel_document_warnings(
            fake_group(field_break=False, business_trip=False),
        )

        self.assertEqual([w["kind"] for w in both], [applicability.BOTH])
        self.assertEqual([w["kind"] for w in none], [applicability.NONE])

        self.assertEqual(
            both[0]["message"],
            "Pegawai dalam grup ini dapat menggunakan Travel Request dan "
            "Perjalanan Dinas. Gunakan masing-masing dokumen sesuai tujuan "
            "perjalanannya.",
        )
        self.assertEqual(
            none[0]["message"],
            "Pegawai dalam grup ini tidak dapat menggunakan Travel Request "
            "maupun Perjalanan Dinas.",
        )

        for forbidden in ("matikan", "tidak sah", "salah satu"):
            self.assertNotIn(forbidden, both[0]["message"].lower())

    def test_warnings_only_for_both_and_none(self):
        self.assertTrue(applicability.travel_document_warnings(
            fake_group(field_break=True, business_trip=True),
        ))
        self.assertTrue(applicability.travel_document_warnings(
            fake_group(field_break=False, business_trip=False),
        ))
        self.assertEqual(applicability.travel_document_warnings(
            fake_group(field_break=True, business_trip=False),
        ), [])
        self.assertEqual(applicability.travel_document_warnings(
            fake_group(field_break=False, business_trip=True),
        ), [])


# ---------------------------------------------------------------------------
# Fixture bersama
# ---------------------------------------------------------------------------


class PolicyTestCase(BusinessTripTestCase):
    def setUp(self):
        super().setUp()

        self.tr_group = self.group("P1-TR", field_break=True, business_trip=False)
        self.bt_group = self.group("P1-BT", field_break=False, business_trip=True)
        self.both_group = self.group("P1-BOTH", field_break=True, business_trip=True)
        self.none_group = self.group("P1-NONE", field_break=False, business_trip=False)

        self.purpose, _ = RotationPurpose.objects.get_or_create(
            code="P1-FB",
            is_deleted=False,
            defaults={"name": "Field Break", "deducts_leave": False},
        )

    @staticmethod
    def group(code, *, field_break, business_trip):
        return EmployeeGroup.objects.create(
            code=code,
            name=code,
            field_break_applicable=field_break,
            business_trip_applicable=business_trip,
        )

    @staticmethod
    def switch_group(employee, group):
        employment = employee.employment
        employment.employee_group = group
        employment.save(update_fields=["employee_group"])

    def make_travel_request(self, employee, *, start=FIRST, end=LAST, purpose=True):
        request = TravelRequestService.create(
            data={
                "employee": employee,
                "company": self.company,
                "location": self.site,
                "start_date": start,
                "end_date": end,
            },
        )

        if purpose:
            TravelRequestPurpose.objects.create(
                request=request,
                sequence=1,
                purpose=self.purpose,
                start_date=start,
                end_date=end,
                total_days=(end - start).days + 1,
            )

        return request

    @staticmethod
    def leg(request, direction, start, end=None, *, sequence=1):
        return TravelArrangement.objects.create(
            request=request,
            direction=direction,
            sequence=sequence,
            travel_start_date=start,
            travel_end_date=end,
        )

    @staticmethod
    def mark(request, status):
        request.status = status
        request.save(update_fields=["status"])

        return request


# ---------------------------------------------------------------------------
# Kelayakan create + submit
# ---------------------------------------------------------------------------


class TravelDocumentEligibilityTests(PolicyTestCase):
    def test_employee_resolver_reads_the_saved_group(self):
        for group, expected in (
            (self.tr_group, applicability.TRAVEL_REQUEST),
            (self.bt_group, applicability.BUSINESS_TRIP),
            (self.both_group, applicability.BOTH),
            (self.none_group, applicability.NONE),
        ):
            with self.subTest(group=group.code):
                employee = self.make_employee(location=self.site, group=group)

                self.assertEqual(applicability.travel_document(employee), expected)

    def test_travel_request_mode_creates_tr_not_bt(self):
        employee = self.make_employee(location=self.site, group=self.tr_group)

        self.make_travel_request(employee)

        with self.assertRaises(ValidationError) as caught:
            self.make_trip(employee)

        self.assertIn("employee", caught.exception.message_dict)

    def test_business_trip_mode_creates_bt_not_tr(self):
        employee = self.make_employee(group=self.bt_group)

        self.make_trip(employee)

        with self.assertRaises(ValidationError) as caught:
            self.make_travel_request(employee)

        self.assertIn("employee", caught.exception.message_dict)

    def test_both_creates_either(self):
        employee = self.make_employee(group=self.both_group)

        self.make_travel_request(employee)
        self.make_trip(employee, start=FAR + timedelta(days=30))

    def test_none_creates_neither(self):
        employee = self.make_employee(group=self.none_group)

        with self.assertRaises(ValidationError) as tr:
            self.make_travel_request(employee)

        with self.assertRaises(ValidationError) as bt:
            self.make_trip(employee)

        self.assertIn("employee", tr.exception.message_dict)
        self.assertIn("employee", bt.exception.message_dict)

    def test_travel_request_submit_rechecks_after_group_changed(self):
        """Dibuat saat group membolehkan, group dimatikan, lalu diajukan."""
        employee = self.make_employee(location=self.site, group=self.tr_group)
        request = self.make_travel_request(employee)

        self.switch_group(employee, self.bt_group)

        with self.assertRaises(ValidationError) as caught:
            TravelRequestService.submit(request=request)

        self.assertIn("employee", caught.exception.message_dict)

        request.refresh_from_db()
        self.assertEqual(request.status, TravelRequestStatus.DRAFT)

    def test_travel_request_submit_passes_eligibility_when_applicable(self):
        """Lolos kelayakan: yang menolak berikutnya adalah baris kosong."""
        employee = self.make_employee(location=self.site, group=self.tr_group)
        request = self.make_travel_request(employee, purpose=False)

        with self.assertRaises(ValidationError) as caught:
            TravelRequestService.submit(request=request)

        self.assertIn("purposes", caught.exception.message_dict)
        self.assertNotIn("employee", caught.exception.message_dict)

    def test_business_trip_submit_rechecks_after_group_changed(self):
        employee = self.make_employee(group=self.bt_group)
        trip = self.make_trip(employee)

        self.switch_group(employee, self.tr_group)

        with self.assertRaises(ValidationError) as caught:
            BusinessTripService.submit(trip=trip)

        self.assertIn("employee", caught.exception.message_dict)

    def test_submitted_documents_are_not_reevaluated(self):
        """Pengajuan yang sudah berjalan tidak dikunci perubahan group."""
        employee = self.make_employee(location=self.site, group=self.tr_group)
        request = self.mark(
            self.make_travel_request(employee),
            TravelRequestStatus.SUBMITTED,
        )

        self.switch_group(employee, self.none_group)

        request.refresh_from_db()
        request.full_clean()

        self.assertEqual(request.status, TravelRequestStatus.SUBMITTED)

    def test_employee_group_save_is_never_rejected(self):
        """BOTH dan NONE sah disimpan; yang ada cuma peringatan."""
        for group in (self.both_group, self.none_group):
            with self.subTest(group=group.code):
                group.full_clean()

                data = EmployeeGroupSerializer(group).data

                self.assertTrue(data["travel_document_warnings"])

        self.assertEqual(
            EmployeeGroupSerializer(self.tr_group).data["travel_document"],
            applicability.TRAVEL_REQUEST,
        )
        self.assertEqual(
            EmployeeGroupSerializer(self.bt_group).data["travel_document_warnings"],
            [],
        )


# ---------------------------------------------------------------------------
# Perjalanan fisik
# ---------------------------------------------------------------------------


class PhysicalJourneyOverlapTests(PolicyTestCase):
    """Pegawai BOTH: satu-satunya keadaan kedua dokumen bisa dibuat."""

    def setUp(self):
        super().setUp()

        # Approver alur BT, supaya pengajuan yang memang lolos sampai ke
        # workflow (pola `BusinessTripOverlapTests`).
        self.manager = self.make_employee()
        self.hrga = self.make_employee(roles=["HRGA"])

        self.employee = self.make_employee(
            location=self.site,
            group=self.both_group,
            reports_to=self.manager,
        )

    def test_journey_dates_fall_back_to_the_off_block(self):
        request = self.make_travel_request(self.employee)

        self.assertEqual(request.journey_dates, (FIRST, LAST))

    def test_journey_dates_span_outbound_and_inbound_legs(self):
        request = self.make_travel_request(self.employee)

        self.leg(request, TravelDirection.OUTBOUND, FIRST - timedelta(days=2))
        self.leg(
            request,
            TravelDirection.OUTBOUND,
            FIRST - timedelta(days=1),
            sequence=2,
        )
        self.leg(
            request,
            TravelDirection.INBOUND,
            LAST + timedelta(days=1),
            LAST + timedelta(days=2),
        )

        self.assertEqual(
            request.journey_dates,
            (FIRST - timedelta(days=2), LAST + timedelta(days=2)),
        )

    def test_deleted_legs_do_not_extend_the_journey(self):
        request = self.make_travel_request(self.employee)

        leg = self.leg(request, TravelDirection.OUTBOUND, FIRST - timedelta(days=3))
        leg.is_deleted = True
        leg.save(update_fields=["is_deleted"])

        self.assertEqual(request.journey_dates, (FIRST, LAST))

    def test_tr_submit_rejects_trip_on_outbound_departure_day(self):
        """Dulu lolos: BT di hari berangkat, sebelum blok off mulai."""
        request = self.make_travel_request(self.employee)
        self.leg(request, TravelDirection.OUTBOUND, FIRST - timedelta(days=2))

        trip = self.approved_trip(
            self.employee,
            start=FIRST - timedelta(days=2),
            days=1,
        )

        with self.assertRaises(ValidationError) as caught:
            TravelRequestService.submit(request=request)

        self.assertIn(trip.document_number, caught.exception.message_dict["start_date"][0])

    def test_tr_submit_rejects_trip_on_inbound_return_day(self):
        request = self.make_travel_request(self.employee)
        self.leg(
            request,
            TravelDirection.INBOUND,
            LAST + timedelta(days=1),
            LAST + timedelta(days=2),
        )

        trip = self.set_status(
            self.make_trip(self.employee, start=LAST + timedelta(days=2), days=1),
            BusinessTripStatus.SUBMITTED,
        )

        # Kunci + nomor dokumennya disebut: `assertRaises` polos ikut lolos
        # oleh galat konfigurasi workflow TR kalau penjagaannya diam.
        with self.assertRaises(ValidationError) as caught:
            TravelRequestService.submit(request=request)

        self.assertIn(
            trip.document_number,
            caught.exception.message_dict["start_date"][0],
        )

    def test_bt_submit_rejects_submitted_tr_by_its_outbound_leg(self):
        request = self.make_travel_request(self.employee)
        self.leg(request, TravelDirection.OUTBOUND, FIRST - timedelta(days=2))
        self.mark(request, TravelRequestStatus.SUBMITTED)

        trip = self.make_trip(self.employee, start=FIRST - timedelta(days=2), days=1)

        with self.assertRaises(ValidationError) as caught:
            BusinessTripService.submit(trip=trip)

        message = caught.exception.message_dict["departure_datetime"][0]

        self.assertIn("Travel Request", message)
        self.assertIn(str(FIRST - timedelta(days=2)), message)

    def test_bt_submit_rejects_approved_tr_by_its_inbound_leg(self):
        request = self.make_travel_request(self.employee)
        self.leg(request, TravelDirection.INBOUND, LAST + timedelta(days=1))
        self.mark(request, TravelRequestStatus.APPROVED)

        trip = self.make_trip(self.employee, start=LAST + timedelta(days=1), days=2)

        with self.assertRaises(ValidationError) as caught:
            BusinessTripService.submit(trip=trip)

        self.assertIn(
            "Travel Request",
            caught.exception.message_dict["departure_datetime"][0],
        )

    def test_without_itinerary_day_before_off_block_is_free(self):
        """Fallback ke blok off: perilaku dokumen lama tidak berubah."""
        request = self.make_travel_request(self.employee)
        self.mark(request, TravelRequestStatus.SUBMITTED)

        trip = self.make_trip(self.employee, start=FIRST - timedelta(days=2), days=2)

        BusinessTripService.submit(trip=trip)

        trip.refresh_from_db()
        self.assertNotEqual(trip.status, BusinessTripStatus.DRAFT)

    def test_draft_tr_with_legs_is_not_a_claim(self):
        request = self.make_travel_request(self.employee)
        self.leg(request, TravelDirection.OUTBOUND, FIRST - timedelta(days=2))

        trip = self.make_trip(self.employee, start=FIRST - timedelta(days=2), days=1)

        BusinessTripService.submit(trip=trip)

    def test_guard_survives_a_group_change_historical_tr(self):
        """TR lama tetap mengklaim harinya walau group kini BT-only."""
        request = self.make_travel_request(self.employee)
        self.leg(request, TravelDirection.OUTBOUND, FIRST - timedelta(days=1))
        self.mark(request, TravelRequestStatus.APPROVED)

        self.switch_group(self.employee, self.bt_group)

        trip = self.make_trip(self.employee, start=FIRST - timedelta(days=1), days=1)

        with self.assertRaises(ValidationError) as caught:
            BusinessTripService.submit(trip=trip)

        self.assertIn(
            "Travel Request",
            caught.exception.message_dict["departure_datetime"][0],
        )

    def test_guard_survives_a_group_change_historical_trip(self):
        """BT lama tetap mengklaim harinya walau group kini TR-only."""
        request = self.make_travel_request(self.employee)
        self.leg(request, TravelDirection.OUTBOUND, FIRST - timedelta(days=1))

        self.approved_trip(self.employee, start=FIRST - timedelta(days=1), days=1)

        self.switch_group(self.employee, self.tr_group)

        with self.assertRaises(ValidationError) as caught:
            TravelRequestService.submit(request=request)

        self.assertIn("start_date", caught.exception.message_dict)
