"""
BT-2A — batas Visitor Request dan Business Trip.

* Visitor Request = orang luar saja.
* Business Trip = perjalanan dinas pegawai.
* Travel Request = perjalanan roster/cuti (tidak disentuh di sini).

Yang dikunci berkas ini: API menolak tamu internal dan pegawai sebagai
subjek tamu dengan pesan yang jelas (bukan konversi diam-diam), pegawai
tetap sah sebagai host dan pemohon, schema tidak lagi menawarkan
internal, dokumen internal lama tetap terbaca, dan Business Trip tidak
bergantung pada Visitor Request sama sekali.

Lewat HTTP sungguhan untuk jalur API — yang diuji adalah apa yang
diterima layar dan klien lain, bukan cuma service.
"""

from __future__ import annotations

import ast
import inspect
import json

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.utils import timezone
from django_tenants.test.client import TenantClient
from apps.accounts.jwt import TenantRefreshToken as RefreshToken

from apps.administration.models.references.visitor import VisitType
from apps.hr.models import (
    VisitorRequest,
    VisitorRequestStatus,
    VisitorType,
)

from .base import VisitorTestCase


URL = "/api/hr/visitor-requests/"
SCHEMA = "/api/framework/schema/hr/visitor-requests/"


class VisitorBoundaryTests(VisitorTestCase):
    def setUp(self):
        super().setUp()

        self.http = TenantClient(self.tenant)

        self.requester = self.make_employee(location=self.head_office)
        self.host = self.make_employee(location=self.site)
        self.traveller = self.make_employee(location=self.head_office)

        self._counter += 1

        self.admin = get_user_model().objects.create_user(
            username=f"vst.admin{self._counter}",
            email=f"vst.admin{self._counter}@example.test",
            password="Test-Only#Pw1",
            is_superuser=True,
            is_staff=True,
        )

    # ------------------------------------------------------------------

    def auth(self):
        token = RefreshToken.for_user(self.admin).access_token

        return {"HTTP_AUTHORIZATION": f"Bearer {token}"}

    def payload(self, **extra):
        today = timezone.localdate().isoformat()

        data = {
            "requester": self.requester.pk,
            "host_employee": self.host.pk,
            "visitor_type": VisitorType.EXTERNAL,
            "external_visitor": self.make_guest().pk,
            "visit_purpose": self.purpose.pk,
            "visit_type": self.visit_type.pk,
            "visit_start_date": today,
            "visit_end_date": today,
        }
        data.update(extra)

        return data

    def post(self, data):
        return self.http.post(
            URL,
            data=json.dumps(data),
            content_type="application/json",
            **self.auth(),
        )

    @staticmethod
    def body(response) -> dict:
        return json.loads(response.content)

    @classmethod
    def record(cls, response) -> dict:
        """Create/detail mengirim record-nya, dengan atau tanpa amplop."""
        body = cls.body(response)

        return body.get("data", body)

    # ------------------------------------------------------------------
    # 1 + 5. Tamu luar tetap bisa dibuat; pegawai sah sebagai host/pemohon
    # ------------------------------------------------------------------

    def test_api_creates_an_external_request_with_employee_host_and_requester(self):
        response = self.post(self.payload())

        self.assertEqual(response.status_code, 201, response.content[:800])

        created = VisitorRequest.objects.get(
            pk=self.record(response)["id"],
        )

        self.assertEqual(created.visitor_type, VisitorType.EXTERNAL)
        self.assertEqual(created.requester_id, self.requester.pk)
        self.assertEqual(created.host_employee_id, self.host.pk)
        self.assertIsNone(created.employee_id)

    # ------------------------------------------------------------------
    # 2 + 3. Internal tidak ditawarkan dan ditolak kalau dikirim langsung
    # ------------------------------------------------------------------

    def test_schema_offers_only_external_and_no_employee_subject(self):
        response = self.http.get(SCHEMA)

        self.assertEqual(response.status_code, 200)

        schema = self.body(response)
        schema = schema.get("data", schema)
        fields = schema["fields"]

        self.assertEqual(
            [option["value"] for option in fields["visitor_type"]["options"]],
            [VisitorType.EXTERNAL],
        )

        employee = fields["employee"]
        self.assertFalse(employee["form"])
        self.assertFalse(employee["filter"])

        # Host dan pemohon tetap pegawai, tetap ada di form.
        self.assertTrue(fields["host_employee"].get("form", True))
        self.assertIn("requester", fields)

    def test_api_rejects_explicit_internal_without_converting(self):
        before = VisitorRequest.objects.count()

        response = self.post(
            self.payload(
                visitor_type=VisitorType.INTERNAL,
                employee=self.traveller.pk,
                external_visitor=None,
            ),
        )

        self.assertEqual(response.status_code, 400, response.content[:800])
        self.assertIn("visitor_type", response.content.decode())
        self.assertIn("Business Trip", response.content.decode())

        self.assertEqual(VisitorRequest.objects.count(), before)

    def test_internal_visit_type_is_rejected(self):
        internal, _ = VisitType.objects.get_or_create(
            code="INTERNAL",
            is_deleted=False,
            defaults={"name": "Internal"},
        )

        with self.assertRaises(ValidationError) as caught:
            self.make_request(requester=self.requester, visit_type=internal)

        self.assertIn("visit_type", caught.exception.message_dict)

    # ------------------------------------------------------------------
    # 4. Pegawai tidak bisa menjadi subjek tamu
    # ------------------------------------------------------------------

    def test_api_rejects_an_employee_as_the_visitor(self):
        before = VisitorRequest.objects.count()

        response = self.post(self.payload(employee=self.traveller.pk))

        self.assertEqual(response.status_code, 400, response.content[:800])
        self.assertIn("employee", response.content.decode())

        self.assertEqual(VisitorRequest.objects.count(), before)

    def test_update_cannot_attach_an_employee_as_the_visitor(self):
        from apps.hr.api.visitor.services import VisitorRequestService

        request = self.make_request(requester=self.requester)

        with self.assertRaises(ValidationError) as caught:
            VisitorRequestService.update(
                instance=request,
                data={"employee": self.traveller},
            )

        self.assertIn("employee", caught.exception.message_dict)

        request.refresh_from_db()
        self.assertIsNone(request.employee_id)

    # ------------------------------------------------------------------
    # 6. Dokumen internal lama tetap terbaca
    # ------------------------------------------------------------------

    def test_legacy_internal_record_is_readable_through_the_api(self):
        legacy = self.make_legacy_internal(
            requester=self.requester,
            employee=self.traveller,
            status=VisitorRequestStatus.COMPLETED,
        )

        response = self.http.get(f"{URL}{legacy.pk}/", **self.auth())

        self.assertEqual(response.status_code, 200, response.content[:800])

        row = self.record(response)

        self.assertEqual(row["visitor_type"], VisitorType.INTERNAL)
        self.assertEqual(row["visitor_type_label"], "Internal")
        self.assertEqual(row["visitor_name"], self.traveller.full_name)

    # ------------------------------------------------------------------
    # 9. Business Trip tidak bergantung pada Visitor Request
    # ------------------------------------------------------------------

    def test_business_trip_code_never_references_visitor_request(self):
        """
        Satu perjalanan, satu dokumen: Business Trip tidak membuat,
        membaca, atau menautkan Visitor Request (§15).
        """
        from apps.hr.api.business_trip import (
            overlap,
            serializers,
            services,
            tasks,
            views,
        )
        from apps.hr.models import business_trip

        for module in (business_trip, overlap, serializers, services, tasks, views):
            tree = ast.parse(inspect.getsource(module))

            # Kode saja — docstring dan komentar boleh menyebut Visitor
            # untuk menjelaskan batasnya.
            names = set()

            for node in ast.walk(tree):
                if isinstance(node, ast.Name):
                    names.add(node.id)
                elif isinstance(node, ast.Attribute):
                    names.add(node.attr)
                elif isinstance(node, ast.alias):
                    names.add(node.name)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names.add(node.module)

            leaked = sorted(name for name in names if "visitor" in name.lower())

            self.assertEqual(leaked, [], module.__name__)
