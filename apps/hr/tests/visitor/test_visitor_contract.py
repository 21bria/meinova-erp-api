"""
Kontrak dokumen Visitor Request yang berlaku hari ini (BT-1).

Tamu **eksternal** adalah satu-satunya jenis untuk dokumen baru sejak
BT-2A. Tamu **internal** yang dikunci di sini adalah dokumen lama: tetap
terbaca, `clean()`-nya tetap sah, dan boleh dialihkan ke eksternal —
tapi tidak bisa lagi dibuat atau dialihkan menjadi internal.
"""

from __future__ import annotations

from datetime import timedelta

from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.hr.api.visitor.services import VisitorRequestService
from apps.hr.models import (
    VisitorRequest,
    VisitorRequestStatus,
    VisitorType,
)

from .base import VisitorTestCase


class ExternalVisitorContractTests(VisitorTestCase):
    def setUp(self):
        super().setUp()
        self.requester = self.make_employee()

    def test_external_request_points_to_the_guest_master(self):
        guest = self.make_guest(organization_name="PT Audit")

        request = self.make_request(requester=self.requester, guest=guest)

        self.assertEqual(request.visitor_type, VisitorType.EXTERNAL)
        self.assertEqual(request.external_visitor_id, guest.pk)
        self.assertIsNone(request.employee_id)
        self.assertEqual(request.visitor_name, guest.full_name)
        self.assertEqual(request.visitor_organization, "PT Audit")
        self.assertEqual(request.status, VisitorRequestStatus.DRAFT)

    def test_visitor_type_defaults_to_external(self):
        self.assertEqual(
            VisitorRequest._meta.get_field("visitor_type").default,
            VisitorType.EXTERNAL,
        )

    def test_external_without_guest_is_rejected(self):
        with self.assertRaises(ValidationError) as caught:
            VisitorRequestService.create(
                data={
                    "requester": self.requester,
                    "host_employee": self.requester,
                    "visitor_type": VisitorType.EXTERNAL,
                    "visit_purpose": self.purpose,
                    "visit_start_date": timezone.localdate(),
                    "visit_end_date": timezone.localdate(),
                },
            )

        self.assertIn("external_visitor", caught.exception.message_dict)

    def test_blacklisted_guest_is_rejected_by_the_service(self):
        guest = self.make_guest(
            is_blacklisted=True,
            blacklist_reason="Pelanggaran K3",
        )

        with self.assertRaises(ValidationError) as caught:
            self.make_request(requester=self.requester, guest=guest)

        self.assertIn("external_visitor", caught.exception.message_dict)
        self.assertIn(
            "Pelanggaran K3",
            caught.exception.message_dict["external_visitor"][0],
        )

    def test_guest_without_identity_number_is_rejected(self):
        guest = self.make_guest(identity_number="")

        with self.assertRaises(ValidationError) as caught:
            self.make_request(requester=self.requester, guest=guest)

        self.assertIn("external_visitor", caught.exception.message_dict)

    def test_document_number_uses_the_visitor_request_series(self):
        request = self.make_request(requester=self.requester)

        self.assertTrue(request.document_number.startswith("VR"))

    def test_end_before_start_is_rejected(self):
        today = timezone.localdate()

        with self.assertRaises(ValidationError) as caught:
            self.make_request(
                requester=self.requester,
                start=today,
                end=today - timedelta(days=1),
            )

        self.assertIn("visit_end_date", caught.exception.message_dict)


class LegacyInternalVisitorContractTests(VisitorTestCase):
    """
    Tamu internal = pegawai yang datang ke lokasi lain. **Ditutup sejak
    BT-2A** — perjalanan pegawai memakai Business Trip. Yang tersisa
    dokumen lama, dan dokumen lama harus tetap bisa dibaca.
    """

    def setUp(self):
        super().setUp()
        self.requester = self.make_employee(location=self.site)
        self.traveller = self.make_employee(location=self.head_office)

    def test_legacy_internal_request_is_still_readable(self):
        request = self.make_legacy_internal(
            requester=self.requester,
            employee=self.traveller,
        )

        self.assertEqual(request.visitor_type, VisitorType.INTERNAL)
        self.assertEqual(request.employee_id, self.traveller.pk)
        self.assertIsNone(request.external_visitor_id)
        self.assertEqual(request.visitor_name, self.traveller.full_name)
        self.assertEqual(request.visitor_organization, self.company.name)

    def test_new_internal_request_is_rejected(self):
        with self.assertRaises(ValidationError) as caught:
            self.make_request(
                requester=self.requester,
                visitor_type=VisitorType.INTERNAL,
                employee=self.traveller,
            )

        self.assertIn("visitor_type", caught.exception.message_dict)
        self.assertIn(
            "Business Trip",
            caught.exception.message_dict["visitor_type"][0],
        )

    def test_model_clean_rejects_both_visitor_references(self):
        """`clean()` sendiri yang menolak — jalur tanpa service juga kena."""
        request = VisitorRequest(
            request_date=timezone.localdate(),
            requester=self.requester,
            host_employee=self.requester,
            visitor_type=VisitorType.INTERNAL,
            employee=self.traveller,
            external_visitor=self.make_guest(),
            visit_purpose=self.purpose,
            visit_start_date=timezone.localdate(),
            visit_end_date=timezone.localdate(),
        )

        with self.assertRaises(ValidationError) as caught:
            request.full_clean()

        self.assertIn("external_visitor", caught.exception.message_dict)

    def test_legacy_internal_draft_can_become_external(self):
        """
        Jalan keluar draft lama: jadikan tamu luar. `apply_visitor_defaults`
        mengosongkan `employee` yang tertinggal.
        """
        request = self.make_legacy_internal(
            requester=self.requester,
            employee=self.traveller,
        )

        guest = self.make_guest()

        request = VisitorRequestService.update(
            instance=request,
            data={
                "visitor_type": VisitorType.EXTERNAL,
                "external_visitor": guest,
            },
        )

        self.assertEqual(request.visitor_type, VisitorType.EXTERNAL)
        self.assertIsNone(request.employee_id)
        self.assertEqual(request.external_visitor_id, guest.pk)

    def test_legacy_internal_draft_cannot_be_edited_as_internal(self):
        request = self.make_legacy_internal(
            requester=self.requester,
            employee=self.traveller,
        )

        with self.assertRaises(ValidationError) as caught:
            VisitorRequestService.update(
                instance=request,
                data={"remarks": "tetap internal"},
            )

        self.assertIn("visitor_type", caught.exception.message_dict)

    def test_switching_external_to_internal_is_rejected(self):
        request = self.make_request(requester=self.requester)

        with self.assertRaises(ValidationError) as caught:
            VisitorRequestService.update(
                instance=request,
                data={
                    "visitor_type": VisitorType.INTERNAL,
                    "employee": self.traveller,
                },
            )

        self.assertIn("visitor_type", caught.exception.message_dict)

        request.refresh_from_db()
        self.assertEqual(request.visitor_type, VisitorType.EXTERNAL)
        self.assertIsNone(request.employee_id)

    def test_workflow_context_exposes_visitor_type(self):
        """Kunci `visitor_type` bisa dipakai `WorkflowStep.condition`."""
        request = self.make_legacy_internal(
            requester=self.requester,
            employee=self.traveller,
        )

        context = VisitorRequestService.workflow_context(request)

        self.assertEqual(context["visitor_type"], VisitorType.INTERNAL)


class VisitorOrganizationContractTests(VisitorTestCase):
    """
    Cakupan dokumen = penempatan **pemohon** (bukan tamu). Lokasi yang
    disebut eksplisit dipertahankan; kalau kosong, diambil dari pemohon.
    Layar pos jaga menyaring lewat kolom `location` ini.
    """

    def setUp(self):
        super().setUp()
        self.requester = self.make_employee(location=self.head_office)

    def test_location_defaults_to_the_requester_placement(self):
        request = self.make_request(requester=self.requester)

        self.assertEqual(request.company_id, self.company.pk)
        self.assertEqual(request.location_id, self.head_office.pk)

    def test_explicit_location_is_kept(self):
        request = self.make_request(
            requester=self.requester,
            location=self.site,
        )

        self.assertEqual(request.location_id, self.site.pk)

    def test_requester_defaults_to_the_typing_user(self):
        request = VisitorRequestService.create(
            data={
                "host_employee": self.requester,
                "visitor_type": VisitorType.EXTERNAL,
                "external_visitor": self.make_guest(),
                "visit_purpose": self.purpose,
                "visit_start_date": timezone.localdate(),
                "visit_end_date": timezone.localdate(),
            },
            user=self.requester.user,
        )

        self.assertEqual(request.requester_id, self.requester.pk)


class VisitorEditabilityContractTests(VisitorTestCase):
    def setUp(self):
        super().setUp()
        self.requester = self.make_employee()

    def test_only_draft_and_rejected_are_editable(self):
        request = self.make_request(requester=self.requester)

        editable = {
            status
            for status in VisitorRequestStatus.values
            if VisitorRequest(status=status).is_editable
        }

        self.assertEqual(
            editable,
            {VisitorRequestStatus.DRAFT, VisitorRequestStatus.REJECTED},
        )

        request.status = VisitorRequestStatus.APPROVED
        request.save(update_fields=["status"])

        with self.assertRaises(ValidationError) as caught:
            VisitorRequestService.update(
                instance=request,
                data={"remarks": "ubah sesudah disetujui"},
            )

        self.assertIn("status", caught.exception.message_dict)
