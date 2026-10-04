"""
BT-2 — aturan dokumen: bentuk, kosakata, penomoran, kelayakan, salinan
organisasi.
"""

from __future__ import annotations

from datetime import timedelta

from django.core.exceptions import ValidationError

from apps.hr.api.business_trip.services import BusinessTripService
from apps.hr.models import (
    BusinessTrip,
    BusinessTripDestinationType,
    BusinessTripPurpose,
    BusinessTripStatus,
    OrganizationAssignment,
)

from .base import FAR, BusinessTripTestCase, at


class BusinessTripShapeTests(BusinessTripTestCase):
    def setUp(self):
        super().setUp()
        self.employee = self.make_employee()

    def test_valid_trip_is_a_numbered_draft(self):
        trip = self.make_trip(self.employee)

        self.assertEqual(trip.status, BusinessTripStatus.DRAFT)
        self.assertTrue(
            trip.document_number.startswith(f"BT-{trip.request_date.year}-"),
            trip.document_number,
        )
        self.assertEqual(trip.destination_location_id, self.site.pk)
        self.assertTrue(trip.is_editable)

    def test_numbers_are_unique_per_document(self):
        first = self.make_trip(self.employee)
        second = self.make_trip(self.employee, start=FAR + timedelta(days=30))

        self.assertNotEqual(first.document_number, second.document_number)

    def test_return_must_be_after_departure(self):
        with self.assertRaises(ValidationError) as caught:
            self.make_trip(
                self.employee,
                departure_datetime=at(FAR, 10),
                return_datetime=at(FAR, 9),
            )

        self.assertIn("return_datetime", caught.exception.message_dict)

    def test_internal_destination_requires_a_location(self):
        with self.assertRaises(ValidationError) as caught:
            BusinessTripService.create(
                data=self.trip_data(
                    self.employee,
                    destination_location=None,
                ) | {"destination_location": None},
            )

        self.assertIn("destination_location", caught.exception.message_dict)

    def test_external_destination_requires_a_city(self):
        with self.assertRaises(ValidationError) as caught:
            self.make_trip(
                self.employee,
                destination_type=BusinessTripDestinationType.EXTERNAL_DOMESTIC,
            )

        self.assertIn("destination_city", caught.exception.message_dict)

    def test_international_destination_requires_a_country(self):
        with self.assertRaises(ValidationError) as caught:
            self.make_trip(
                self.employee,
                destination_type=(
                    BusinessTripDestinationType.EXTERNAL_INTERNATIONAL
                ),
                destination_city=self.city,
            )

        self.assertIn("destination_country", caught.exception.message_dict)

    def test_external_trip_clears_the_company_location(self):
        trip = self.make_trip(
            self.employee,
            destination_type=BusinessTripDestinationType.EXTERNAL_DOMESTIC,
            destination_city=self.city,
        )

        self.assertIsNone(trip.destination_location_id)
        self.assertEqual(trip.destination_city_id, self.city.pk)

    def test_switching_to_internal_clears_city_and_country(self):
        trip = self.make_trip(
            self.employee,
            destination_type=(
                BusinessTripDestinationType.EXTERNAL_INTERNATIONAL
            ),
            destination_city=self.city,
            destination_country=self.abroad,
        )

        trip = BusinessTripService.update(
            instance=trip,
            data={
                "destination_type": (
                    BusinessTripDestinationType.INTERNAL_LOCATION
                ),
                "destination_location": self.site,
            },
        )

        self.assertIsNone(trip.destination_city_id)
        self.assertIsNone(trip.destination_country_id)
        self.assertEqual(trip.destination_location_id, self.site.pk)

    def test_purpose_detail_is_required(self):
        with self.assertRaises(ValidationError) as caught:
            self.make_trip(self.employee, purpose="  ")

        self.assertIn("purpose", caught.exception.message_dict)

    def test_purpose_vocabulary_is_the_approved_set(self):
        self.assertEqual(
            set(BusinessTripPurpose.values),
            {"duty", "site_visit", "meeting", "training", "audit", "other"},
        )

    def test_unknown_purpose_is_rejected(self):
        with self.assertRaises(ValidationError) as caught:
            self.make_trip(self.employee, purpose_category="vendor_visit")

        self.assertIn("purpose_category", caught.exception.message_dict)

    def test_no_visit_purpose_dependency(self):
        field = BusinessTrip._meta.get_field("purpose_category")

        self.assertFalse(field.is_relation)

    def test_origin_defaults_to_the_work_location(self):
        trip = self.make_trip(self.employee)

        self.assertEqual(trip.origin_location_id, self.head_office.pk)

    def test_self_service_create_fills_employee_and_requester(self):
        trip = BusinessTripService.create(
            data=self.trip_data(),
            user=self.employee.user,
        )

        self.assertEqual(trip.employee_id, self.employee.pk)
        self.assertEqual(trip.requester_id, self.employee.pk)

    def test_admin_create_keeps_the_admin_as_requester(self):
        admin = self.make_employee()

        trip = self.make_trip(self.employee, user=admin.user)

        self.assertEqual(trip.employee_id, self.employee.pk)
        self.assertEqual(trip.requester_id, admin.pk)


class BusinessTripEligibilityTests(BusinessTripTestCase):
    def test_group_without_business_trip_cannot_create(self):
        crew = self.make_employee(group=self.site_group, location=self.site)

        with self.assertRaises(ValidationError) as caught:
            self.make_trip(crew)

        self.assertIn("employee", caught.exception.message_dict)

    def test_employee_without_group_is_eligible(self):
        employee = self.make_employee()
        employee.employment.employee_group = None
        employee.employment.save(update_fields=["employee_group"])

        employee.refresh_from_db()

        trip = self.make_trip(employee)

        self.assertEqual(trip.status, BusinessTripStatus.DRAFT)

    def test_eligibility_is_rechecked_at_submit(self):
        employee = self.make_employee(reports_to=self.make_employee())
        trip = self.make_trip(employee)

        employee.employment.employee_group = self.site_group
        employee.employment.save(update_fields=["employee_group"])

        with self.assertRaises(ValidationError) as caught:
            BusinessTripService.submit(trip=trip)

        self.assertIn("employee", caught.exception.message_dict)

    def test_eligibility_comes_from_the_group_not_the_location(self):
        """Tidak ada kode lokasi 'HO' di mana pun: pegawai site ber-group
        kantor tetap boleh."""
        employee = self.make_employee(location=self.site)

        trip = self.make_trip(employee, destination=self.head_office)

        self.assertEqual(trip.location_id, self.site.pk)


class BusinessTripSnapshotTests(BusinessTripTestCase):
    def setUp(self):
        super().setUp()

        self.manager = self.make_employee()
        self.hrga = self.make_employee(roles=["HRGA"])
        self.employee = self.make_employee(reports_to=self.manager)

    def move(self, employee, *, location, department):
        OrganizationAssignment.objects.filter(employee=employee).update(
            location=location,
            department=department,
        )

    def test_snapshot_captures_the_placement(self):
        trip = self.make_trip(self.employee)
        placement = self.employee.organization

        self.assertEqual(trip.company_id, placement.company_id)
        self.assertEqual(trip.location_id, placement.location_id)
        self.assertEqual(trip.department_id, placement.department_id)
        self.assertEqual(trip.position_id, placement.position_id)

    def test_draft_follows_a_move(self):
        trip = self.make_trip(self.employee)

        self.move(
            self.employee,
            location=self.site,
            department=self.other_department,
        )

        trip = BusinessTripService.update(
            instance=trip,
            data={"notes": "disunting sesudah mutasi"},
        )

        self.assertEqual(trip.location_id, self.site.pk)
        self.assertEqual(trip.department_id, self.other_department.pk)

    def test_submitted_trip_keeps_its_historical_placement(self):
        trip = self.make_trip(self.employee)

        BusinessTripService.submit(trip=trip, user=self.employee.user)

        self.move(
            self.employee,
            location=self.site,
            department=self.other_department,
        )

        trip.refresh_from_db()

        self.assertEqual(trip.status, BusinessTripStatus.SUBMITTED)
        self.assertEqual(trip.location_id, self.head_office.pk)
        self.assertEqual(trip.department_id, self.department.pk)

    def test_approved_trip_keeps_its_historical_placement(self):
        trip = self.make_trip(self.employee)

        BusinessTripService.submit(trip=trip, user=self.employee.user)

        for approver in (self.manager, self.hrga):
            BusinessTripService.decide(
                trip=trip,
                decision="approve",
                user=approver.user,
            )

        self.move(
            self.employee,
            location=self.site,
            department=self.other_department,
        )

        trip.refresh_from_db()

        self.assertEqual(trip.status, BusinessTripStatus.APPROVED)
        self.assertEqual(trip.location_id, self.head_office.pk)
        self.assertEqual(trip.department_id, self.department.pk)

    def test_snapshot_fields_are_read_only_in_the_api_serializer(self):
        from apps.hr.api.business_trip.serializers import (
            BusinessTripSerializer,
        )

        read_only = set(BusinessTripSerializer.Meta.read_only_fields)

        for name in (
            "company", "branch", "location", "division", "department",
            "section", "position", "cost_center", "status", "requester",
        ):
            self.assertIn(name, read_only)
