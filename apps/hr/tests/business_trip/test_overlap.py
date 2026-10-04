"""
BT-2 — tumpang-tindih saat diajukan, dan penjagaan timbal balik Travel
Request.

Satuannya hari kalender inklusif di jam dinding. Draf bukan klaim di
kedua sisi. Dokumen pegawai lain tidak pernah dibaca.
"""

from __future__ import annotations

from datetime import timedelta

from django.core.exceptions import ValidationError

from apps.administration.models import RotationPurpose
from apps.hr.api.business_trip.overlap import (
    assert_travel_request_has_no_business_trip,
)
from apps.hr.api.business_trip.services import BusinessTripService
from apps.hr.api.travel_request.services import TravelRequestService
from apps.hr.models import (
    AttendancePermission,
    AttendancePermissionStatus,
    AttendancePermissionType,
    BusinessTripStatus,
    EmployeeLeave,
    LeaveStatus,
    TravelRequest,
    TravelRequestPurpose,
    TravelRequestStatus,
)

from .base import FAR, BusinessTripTestCase


FIRST = FAR
LAST = FAR + timedelta(days=4)


class BusinessTripOverlapTests(BusinessTripTestCase):
    def setUp(self):
        super().setUp()

        self.manager = self.make_employee()
        self.hrga = self.make_employee(roles=["HRGA"])
        self.employee = self.make_employee(reports_to=self.manager)

        # Perjalanan yang diuji: FIRST..LAST (lima hari).
        self.trip = self.make_trip(self.employee, start=FIRST, days=5)

    def submit(self):
        BusinessTripService.submit(trip=self.trip, user=self.employee.user)
        self.trip.refresh_from_db()

        return self.trip

    def assert_rejected(self, fragment):
        with self.assertRaises(ValidationError) as caught:
            BusinessTripService.submit(trip=self.trip)

        message = caught.exception.message_dict["departure_datetime"][0]

        self.assertIn(fragment, message)

        self.trip.refresh_from_db()
        self.assertEqual(self.trip.status, BusinessTripStatus.DRAFT)

    def leave(self, *, start, end, status, employee=None):
        return EmployeeLeave.objects.create(
            employee=employee or self.employee,
            company=self.company,
            leave_type=self.leave_type,
            start_date=start,
            end_date=end,
            total_days=(end - start).days + 1,
            status=status,
        )

    def travel(self, *, start, end, status, employee=None):
        return TravelRequest.objects.create(
            employee=employee or self.employee,
            company=self.company,
            location=self.site,
            start_date=start,
            end_date=end,
            status=status,
        )

    def permission(self, *, day, status, kind=AttendancePermissionType.FULL_DAY):
        return AttendancePermission.objects.create(
            employee=self.employee,
            company=self.company,
            permission_type=kind,
            date=day,
            reason="Urusan keluarga",
            status=status,
        )

    # ------------------------------------------------------------------
    # Tanpa konflik
    # ------------------------------------------------------------------

    def test_clean_calendar_submits(self):
        self.assertEqual(self.submit().status, BusinessTripStatus.SUBMITTED)

    def test_leave_ending_the_day_before_departure_is_fine(self):
        self.leave(
            start=FIRST - timedelta(days=3),
            end=FIRST - timedelta(days=1),
            status=LeaveStatus.APPROVED,
        )

        self.assertEqual(self.submit().status, BusinessTripStatus.SUBMITTED)

    def test_leave_starting_the_day_after_return_is_fine(self):
        self.leave(
            start=LAST + timedelta(days=1),
            end=LAST + timedelta(days=2),
            status=LeaveStatus.APPROVED,
        )

        self.assertEqual(self.submit().status, BusinessTripStatus.SUBMITTED)

    def test_drafts_are_not_claims(self):
        self.leave(start=FIRST, end=FIRST, status=LeaveStatus.DRAFT)
        self.travel(start=FIRST, end=LAST, status=TravelRequestStatus.DRAFT)
        self.permission(day=FIRST, status=AttendancePermissionStatus.DRAFT)
        self.make_trip(self.employee, start=FIRST, days=2)

        self.assertEqual(self.submit().status, BusinessTripStatus.SUBMITTED)

    def test_closed_documents_are_not_claims(self):
        self.leave(start=FIRST, end=FIRST, status=LeaveStatus.REJECTED)
        self.leave(start=FIRST, end=FIRST, status=LeaveStatus.CANCELLED)
        self.travel(start=FIRST, end=LAST, status=TravelRequestStatus.CANCELLED)
        self.set_status(
            self.make_trip(self.employee, start=FIRST, days=2),
            BusinessTripStatus.CANCELLED,
        )

        self.assertEqual(self.submit().status, BusinessTripStatus.SUBMITTED)

    def test_partial_day_permission_is_not_a_conflict(self):
        self.permission(
            day=FIRST,
            status=AttendancePermissionStatus.APPROVED,
            kind=AttendancePermissionType.LATE_ARRIVAL,
        )

        self.assertEqual(self.submit().status, BusinessTripStatus.SUBMITTED)

    def test_other_employees_documents_are_ignored(self):
        other = self.make_employee()

        self.leave(
            start=FIRST,
            end=LAST,
            status=LeaveStatus.APPROVED,
            employee=other,
        )
        self.set_status(
            self.make_trip(other, start=FIRST, days=5),
            BusinessTripStatus.APPROVED,
        )

        self.assertEqual(self.submit().status, BusinessTripStatus.SUBMITTED)

    # ------------------------------------------------------------------
    # Konflik
    # ------------------------------------------------------------------

    def test_approved_leave_conflicts(self):
        leave = self.leave(start=LAST, end=LAST, status=LeaveStatus.APPROVED)

        self.assert_rejected(f"cuti {leave.document_number or f'#{leave.pk}'}")

    def test_submitted_leave_conflicts(self):
        self.leave(start=FIRST, end=FIRST, status=LeaveStatus.SUBMITTED)

        self.assert_rejected("cuti")

    def test_recorded_leave_conflicts(self):
        self.leave(
            start=FIRST - timedelta(days=2),
            end=FIRST,
            status=LeaveStatus.RECORDED,
        )

        self.assert_rejected("cuti")

    def test_another_submitted_trip_conflicts(self):
        self.set_status(
            self.make_trip(self.employee, start=LAST, days=2),
            BusinessTripStatus.SUBMITTED,
        )

        self.assert_rejected("Business Trip")

    def test_trip_ending_on_the_departure_day_conflicts(self):
        """Hari yang sama tidak bisa dimiliki dua dokumen."""
        self.set_status(
            self.make_trip(
                self.employee,
                start=FIRST - timedelta(days=2),
                days=3,
            ),
            BusinessTripStatus.APPROVED,
        )

        self.assert_rejected("Business Trip")

    def test_completed_trip_still_claims_its_days(self):
        self.set_status(
            self.make_trip(self.employee, start=FIRST, days=1),
            BusinessTripStatus.COMPLETED,
        )

        self.assert_rejected("Business Trip")

    def test_submitted_travel_request_conflicts(self):
        self.travel(
            start=FIRST + timedelta(days=1),
            end=LAST + timedelta(days=5),
            status=TravelRequestStatus.SUBMITTED,
        )

        self.assert_rejected("Travel Request")

    def test_approved_travel_request_conflicts(self):
        self.travel(start=LAST, end=LAST, status=TravelRequestStatus.APPROVED)

        self.assert_rejected("Travel Request")

    def test_full_day_permission_conflicts(self):
        self.permission(
            day=FIRST + timedelta(days=2),
            status=AttendancePermissionStatus.APPROVED,
        )

        self.assert_rejected("izin sehari penuh")

    def test_pending_full_day_permission_conflicts(self):
        self.permission(
            day=FIRST,
            status=AttendancePermissionStatus.IN_REVIEW,
        )

        self.assert_rejected("izin sehari penuh")


class TravelRequestReciprocalGuardTests(BusinessTripTestCase):
    """Satu-satunya perubahan perilaku Travel Request di BT-2."""

    def setUp(self):
        super().setUp()

        self.employee = self.make_employee(location=self.site)

        self.purpose, _ = RotationPurpose.objects.get_or_create(
            code="BT-FB",
            is_deleted=False,
            defaults={"name": "Field Break", "deducts_leave": False},
        )

    def travel_request(self, *, start=FIRST, end=LAST):
        request = TravelRequestService.create(
            data={
                "employee": self.employee,
                "company": self.company,
                "location": self.site,
                "start_date": start,
                "end_date": end,
            },
        )

        TravelRequestPurpose.objects.create(
            request=request,
            sequence=1,
            purpose=self.purpose,
            start_date=start,
            end_date=end,
            total_days=(end - start).days + 1,
        )

        return request

    def test_travel_request_submit_rejects_an_approved_trip(self):
        trip = self.approved_trip(
            self.employee,
            start=FIRST + timedelta(days=2),
            days=2,
        )

        request = self.travel_request()

        with self.assertRaises(ValidationError) as caught:
            TravelRequestService.submit(request=request)

        message = caught.exception.message_dict["start_date"][0]

        self.assertIn(trip.document_number, message)

        request.refresh_from_db()
        self.assertEqual(request.status, TravelRequestStatus.DRAFT)

    def test_travel_request_submit_rejects_a_submitted_trip(self):
        self.set_status(
            self.make_trip(self.employee, start=LAST, days=1),
            BusinessTripStatus.SUBMITTED,
        )

        with self.assertRaises(ValidationError):
            TravelRequestService.submit(request=self.travel_request())

    def test_draft_or_cancelled_trips_do_not_block(self):
        self.make_trip(self.employee, start=FIRST, days=2)
        self.set_status(
            self.make_trip(self.employee, start=FIRST, days=2),
            BusinessTripStatus.CANCELLED,
        )

        assert_travel_request_has_no_business_trip(self.travel_request())

    def test_adjacent_trip_does_not_block(self):
        self.approved_trip(
            self.employee,
            start=LAST + timedelta(days=1),
            days=2,
        )

        assert_travel_request_has_no_business_trip(self.travel_request())

    def test_other_employees_trip_does_not_block(self):
        other = self.make_employee()

        self.approved_trip(other, start=FIRST, days=5)

        assert_travel_request_has_no_business_trip(self.travel_request())

    def test_symmetry_trip_submit_rejects_a_submitted_travel_request(self):
        request = self.travel_request()
        request.status = TravelRequestStatus.SUBMITTED
        request.save(update_fields=["status"])

        self.employee.employment.employee_group = self.office_group
        self.employee.employment.save(update_fields=["employee_group"])

        trip = self.make_trip(self.employee, start=FIRST + timedelta(days=1))

        with self.assertRaises(ValidationError) as caught:
            BusinessTripService.submit(trip=trip)

        self.assertIn(
            "Travel Request",
            caught.exception.message_dict["departure_datetime"][0],
        )
