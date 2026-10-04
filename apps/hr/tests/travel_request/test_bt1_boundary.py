"""
BT-1 — batas Travel Request yang harus tetap utuh saat Business Trip lahir.

Travel Request (pegawai roster/site: field break dan perjalanan terkait
cuti) **tidak** berubah tujuan (`docs/claude/hr/business-trip.md` §16).
Yang dikunci di sini adalah titik-titik yang akan disentuh atau dijadikan
contoh oleh BT-2:

* himpunan status aktif TR — penjaga tumpang-tindih timbal balik BT-2
  membacanya dari sisi Business Trip;
* TR tidak menulis presensi apa pun saat disetujui (efeknya ke presensi
  hanya lewat roster/jadwal dan catatan cuti yang diterbitkannya);
* menu TR khusus pegawai roster, dan slot `NON_ROSTER_ONLY` yang
  disiapkan untuk perjalanan dinas orang kantor sudah ada;
* atribut keamanan deklaratif viewset TR / Visitor / Leave — pola yang
  ditiru (dan kekurangannya yang tidak boleh ditiru) Business Trip.

Eligibility `field_break` untuk TR sudah dikunci di
`apps/hr/tests/applicability/test_feature_applicability.py`
(`FieldBreakApplicabilityTests`).
"""

from __future__ import annotations

from django.test import SimpleTestCase

from apps.accounts.management.commands.seed_menus import MENU_RULES
from apps.accounts.models.menu import MenuVisibilityRule
from apps.hr.api.leave.views import EmployeeLeaveViewSet
from apps.hr.api.travel_request.services import TravelRequestService
from apps.hr.api.travel_request.views import (
    TravelArrangementViewSet,
    TravelRequestPurposeViewSet,
    TravelRequestViewSet,
)
from apps.hr.api.visitor.views import (
    ExternalVisitorViewSet,
    VisitorPassViewSet,
    VisitorRequestViewSet,
)
from apps.hr.models import EmployeeAttendance, EmployeeLeave
from apps.hr.models.travel_request import (
    TRAVEL_REQUEST_ACTIVE_STATUSES,
    TravelRequestStatus,
)
from apps.workflow.models import InstanceStatus

from .base import TravelRequestTestCase


class TravelRequestStatusContract(SimpleTestCase):
    def test_statuses(self):
        self.assertEqual(
            set(TravelRequestStatus.values),
            {"draft", "submitted", "approved", "rejected", "cancelled"},
        )

    def test_active_statuses_block_a_second_document(self):
        self.assertEqual(
            set(TRAVEL_REQUEST_ACTIVE_STATUSES),
            {
                TravelRequestStatus.DRAFT,
                TravelRequestStatus.SUBMITTED,
                TravelRequestStatus.APPROVED,
            },
        )


class TravelMenuContract(SimpleTestCase):
    # POLICY-1A: syarat menu TR/BT menyebut penanda Employee Group-nya
    # sendiri, bukan nilai roster yang diberi arti lain di rute ini.
    # Semantik runtime-nya: `apps/hr/tests/business_trip/
    # test_menu_visibility_semantics.py`.
    def test_travel_request_menu_follows_field_break_for_employees(self):
        rules = MENU_RULES["EMPLOYEE"]

        self.assertEqual(
            rules["/hr/travel-requests"],
            MenuVisibilityRule.FIELD_BREAK,
        )
        # BT-5: hub-nya tidak lagi roster-only — Business Trip tinggal di
        # hub yang sama. Tiap kartu menyaring dirinya sendiri.
        self.assertNotIn("/hr/roster-travel", rules)

    def test_business_trip_menu_follows_business_trip_for_employees(self):
        self.assertEqual(
            MENU_RULES["EMPLOYEE"]["/hr/business-trips"],
            MenuVisibilityRule.BUSINESS_TRIP,
        )

    def test_roster_schedule_menu_stays_roster_only(self):
        self.assertEqual(
            MENU_RULES["EMPLOYEE"]["/hr/site-rotations"],
            MenuVisibilityRule.ROSTER_ONLY,
        )

    def test_non_roster_slot_exists_for_office_travel(self):
        self.assertEqual(
            MenuVisibilityRule.NON_ROSTER_ONLY,
            "non_roster_only",
        )


class DeclarativeSecurityContract(SimpleTestCase):
    """
    Keadaan **hari ini**. Baris yang ditandai "celah" adalah temuan BT-0A,
    dikunci supaya perbaikannya kelak disengaja; Business Trip tidak
    boleh meniru celahnya (BT-0B §7.1, §8).
    """

    def test_leave_declares_workflow_document_for_approver_read(self):
        self.assertEqual(
            tuple(EmployeeLeaveViewSet.workflow_document),
            ("hr", "leave_request"),
        )

    def test_travel_request_scope(self):
        scope = TravelRequestViewSet.data_scope

        self.assertEqual(scope["own"], "employee__user_id")
        self.assertEqual(scope["location"], "location")

    def test_travel_request_has_no_workflow_document_today(self):
        # Celah: approver bercakupan `own` tidak bisa membuka TR yang
        # ditagihkan kepadanya.
        self.assertIsNone(TravelRequestViewSet.workflow_document)

    def test_travel_request_children_follow_parent_scope(self):
        # Celah BT-0A ditutup: Travel Arrangement (TR-CLEANUP-1) dan
        # Travel Purpose (TR-CLEANUP-2) disaring lewat cakupan TR
        # induknya (`request__…`).
        expected = {
            key: f"request__{path}"
            for key, path in TravelRequestViewSet.data_scope.items()
        }

        self.assertEqual(TravelRequestPurposeViewSet.data_scope, expected)
        self.assertEqual(TravelArrangementViewSet.data_scope, expected)

    def test_visitor_request_scope_follows_the_requester(self):
        scope = VisitorRequestViewSet.data_scope

        self.assertEqual(scope["own"], "requester__user_id")
        self.assertEqual(scope["location"], "location")
        self.assertIsNone(VisitorRequestViewSet.workflow_document)

    def test_visitor_pass_scope_follows_its_request(self):
        self.assertEqual(
            VisitorPassViewSet.data_scope["location"],
            "request__location",
        )

    def test_external_visitor_master_is_deliberately_unscoped(self):
        self.assertIsNone(ExternalVisitorViewSet.data_scope)


class TravelRequestAttendanceBoundaryTests(TravelRequestTestCase):
    def test_approval_writes_no_attendance_rows(self):
        """
        TR menyentuh presensi hanya secara tidak langsung (roster dan
        cuti). Persetujuannya sendiri tidak menulis satu baris presensi
        pun — Business Trip (BT-3) juga tidak menulis baris saat disetujui;
        penutup hari yang membacanya.
        """
        employee = self.make_employee()
        request = self.make_request(employee)

        before = EmployeeAttendance.objects.filter(employee=employee).count()

        TravelRequestService.on_workflow_done(
            request=request,
            status=InstanceStatus.APPROVED,
        )

        request.refresh_from_db()

        self.assertEqual(request.status, TravelRequestStatus.APPROVED)
        self.assertEqual(
            EmployeeAttendance.objects.filter(employee=employee).count(),
            before,
        )

    def test_field_break_purpose_issues_no_leave_record(self):
        employee = self.make_employee()
        request = self.make_request(employee)

        TravelRequestService.on_workflow_done(
            request=request,
            status=InstanceStatus.APPROVED,
        )

        self.assertFalse(
            EmployeeLeave.objects.filter(
                employee=employee,
                is_deleted=False,
            ).exists(),
        )
