"""
BT-2 — siapa boleh membaca, menulis, dan memutuskan Business Trip.

Lewat HTTP sungguhan dengan token JWT: yang diuji penyaringan baris dan
penjagaan subjek, dan itu baru berarti kalau `request.user` datang dari
jalur yang sama dengan layar. Setiap skenario positif punya pasangan
negatif — gerbang yang tidak pernah menolak siapa pun juga lulus test
positif.

Tidak meniru dua celah Travel Request (temuan BT-1): approver ber-
cakupan `own` bisa membaca dokumen yang ditagihkan kepadanya, dan
endpoint anak (ruas) disaring per baris termasuk jalur create.
"""

from __future__ import annotations

import json

from datetime import timedelta

from django.contrib.auth.models import Permission
from django_tenants.test.client import TenantClient
from apps.accounts.jwt import TenantRefreshToken as RefreshToken

from apps.accounts.models import AuthorityMode, Role
from apps.accounts.services.role_assignment import assign_roles
from apps.hr.api.business_trip.services import BusinessTripService
from apps.hr.models import BusinessTripLeg, BusinessTripStatus

from .base import FAR, BusinessTripTestCase, at


TRIPS = "/api/hr/business-trips/"
LEGS = "/api/hr/business-trip-legs/"

WRITE = ["add", "change", "view", "delete"]


class _As:
    def __init__(self, client, user):
        self.client = client
        self.headers = {
            "HTTP_AUTHORIZATION": (
                f"Bearer {RefreshToken.for_user(user).access_token}"
            ),
        }

    def get(self, path):
        return self.client.get(path, **self.headers)

    def post(self, path, payload=None):
        return self.client.post(
            path,
            data=json.dumps(payload or {}),
            content_type="application/json",
            **self.headers,
        )

    def patch(self, path, payload):
        return self.client.patch(
            path,
            data=json.dumps(payload),
            content_type="application/json",
            **self.headers,
        )


def _ids(response) -> set[int]:
    return {row["id"] for row in json.loads(response.content)["data"]}


class BusinessTripSecurityTests(BusinessTripTestCase):
    def setUp(self):
        super().setUp()

        self.http = TenantClient(self.tenant)

        n = self._counter

        self.writer_role = self.role(f"BT-W-{n}", trip=WRITE, leg=WRITE)
        self.blind_role = self.role(f"BT-B-{n}", trip=["add"], leg=[])

        self.manager = self.make_employee()
        self.hrga = self.make_employee(roles=["HRGA"])

        self.me = self.make_employee(reports_to=self.manager)
        self.colleague = self.make_employee(reports_to=self.manager)
        self.stranger = self.make_employee()
        self.site_worker = self.make_employee(
            location=self.site,
            reports_to=self.manager,
        )

        for employee in (self.me, self.colleague, self.stranger,
                         self.manager, self.site_worker):
            self.grant(employee, self.writer_role, "own", None)

        self.site_admin = self.make_employee(location=self.site)
        self.grant(self.site_admin, self.writer_role, "location", self.site.pk)

        self.foreign_admin = self.make_employee(company=self.other_company)
        self.grant(
            self.foreign_admin,
            self.writer_role,
            "company",
            self.other_company.pk,
        )

        self.blind = self.make_employee()
        self.grant(self.blind, self.blind_role, "own", None)

        self.my_trip = self.make_trip(self.me, start=FAR)
        self.colleague_trip = self.make_trip(self.colleague, start=FAR)
        self.site_trip = self.make_trip(self.site_worker, start=FAR)

    # ------------------------------------------------------------------

    @staticmethod
    def role(code, *, trip, leg):
        role = Role.objects.create(code=code, name=code)

        codenames = [f"{verb}_businesstrip" for verb in trip] + [
            f"{verb}_businesstripleg" for verb in leg
        ]

        role.permissions.set(
            Permission.objects.filter(
                content_type__app_label="hr",
                codename__in=codenames,
            ),
        )

        return role

    @staticmethod
    def grant(employee, role, resource_type, resource_id):
        assign_roles(employee.user, [{
            "role": role.pk,
            "authority_mode": AuthorityMode.EXPLICIT,
            "authorities": [
                {"resource_type": resource_type, "resource_id": resource_id},
            ],
        }])

    def as_(self, employee):
        return _As(self.http, employee.user)

    def detail(self, trip):
        return f"{TRIPS}{trip.pk}/"

    def submit(self, trip, employee):
        BusinessTripService.submit(trip=trip, user=employee.user)
        trip.refresh_from_db()

        return trip

    # ------------------------------------------------------------------
    # Baca
    # ------------------------------------------------------------------

    def test_employee_lists_only_own_trips(self):
        response = self.as_(self.me).get(TRIPS)

        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertEqual(_ids(response), {self.my_trip.pk})

    def test_employee_cannot_open_a_colleagues_trip(self):
        response = self.as_(self.me).get(self.detail(self.colleague_trip))

        self.assertEqual(response.status_code, 404)

    def test_read_requires_the_view_permission(self):
        response = self.as_(self.blind).get(TRIPS)

        self.assertEqual(response.status_code, 403)

    def test_location_admin_sees_only_their_location(self):
        admin = self.as_(self.site_admin)

        self.assertEqual(_ids(admin.get(TRIPS)), {self.site_trip.pk})
        self.assertEqual(
            admin.get(self.detail(self.my_trip)).status_code,
            404,
        )

    def test_other_company_admin_sees_nothing_of_this_company(self):
        response = self.as_(self.foreign_admin).get(TRIPS)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(_ids(response), set())

    # ------------------------------------------------------------------
    # Approver
    # ------------------------------------------------------------------

    def test_approver_cannot_read_before_the_document_reaches_them(self):
        response = self.as_(self.manager).get(self.detail(self.my_trip))

        self.assertEqual(response.status_code, 404)

    def test_approver_reads_the_assigned_document_outside_own_scope(self):
        self.submit(self.my_trip, self.me)

        response = self.as_(self.manager).get(self.detail(self.my_trip))

        self.assertEqual(response.status_code, 200, response.content[:300])

        body = json.loads(response.content)

        self.assertTrue(body["approval"]["can_act"])

    def test_approver_approves_over_http(self):
        self.submit(self.my_trip, self.me)

        response = self.as_(self.manager).post(
            f"{self.detail(self.my_trip)}approve/",
        )

        self.assertEqual(response.status_code, 200, response.content[:300])

        self.my_trip.refresh_from_db()

        # Meja HRGA masih menunggu.
        self.assertEqual(self.my_trip.status, BusinessTripStatus.SUBMITTED)

    def test_unrelated_employee_cannot_approve(self):
        self.submit(self.my_trip, self.me)

        response = self.as_(self.stranger).post(
            f"{self.detail(self.my_trip)}approve/",
        )

        self.assertEqual(response.status_code, 404)

        self.my_trip.refresh_from_db()
        self.assertEqual(self.my_trip.status, BusinessTripStatus.SUBMITTED)

    def test_in_scope_admin_who_is_not_the_desk_cannot_approve(self):
        self.submit(self.site_trip, self.site_worker)

        response = self.as_(self.site_admin).post(
            f"{self.detail(self.site_trip)}approve/",
        )

        self.assertIn(response.status_code, (400, 403), response.content[:300])

        self.site_trip.refresh_from_db()
        self.assertEqual(self.site_trip.status, BusinessTripStatus.SUBMITTED)

    def test_approver_cannot_edit_the_document(self):
        self.submit(self.my_trip, self.me)

        response = self.as_(self.manager).patch(
            self.detail(self.my_trip),
            {"purpose": "Disunting approver"},
        )

        self.assertEqual(response.status_code, 404)

    # ------------------------------------------------------------------
    # Tulis
    # ------------------------------------------------------------------

    def payload(self, **extra):
        data = {
            "destination_type": "internal_location",
            "destination_location": self.site.pk,
            "purpose_category": "site_visit",
            "purpose": "Inspeksi",
            "departure_datetime": at(FAR, 7).isoformat(),
            "return_datetime": at(FAR, 18).isoformat(),
        }
        data.update(extra)

        return data

    def test_employee_creates_own_trip_without_naming_the_employee(self):
        response = self.as_(self.me).post(TRIPS, self.payload())

        self.assertEqual(response.status_code, 201, response.content[:400])

        body = json.loads(response.content)
        data = body.get("data", body)

        self.assertEqual(data["employee"], self.me.pk)
        self.assertEqual(data["status"], "draft")

    def test_write_guard_rejects_creating_for_someone_else(self):
        response = self.as_(self.me).post(
            TRIPS,
            self.payload(employee=self.colleague.pk),
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("employee", response.content.decode())

    def test_write_guard_rejects_moving_a_trip_to_someone_else(self):
        response = self.as_(self.me).patch(
            self.detail(self.my_trip),
            {"employee": self.colleague.pk},
        )

        self.assertEqual(response.status_code, 400)

        self.my_trip.refresh_from_db()
        self.assertEqual(self.my_trip.employee_id, self.me.pk)

    def test_status_cannot_be_written_through_the_form(self):
        response = self.as_(self.me).patch(
            self.detail(self.my_trip),
            {"status": "approved"},
        )

        self.assertIn(response.status_code, (200, 400))

        self.my_trip.refresh_from_db()
        self.assertEqual(self.my_trip.status, BusinessTripStatus.DRAFT)

    def test_employee_submits_own_trip_over_http(self):
        response = self.as_(self.me).post(f"{self.detail(self.my_trip)}submit/")

        self.assertEqual(response.status_code, 200, response.content[:300])

        self.my_trip.refresh_from_db()
        self.assertEqual(self.my_trip.status, BusinessTripStatus.SUBMITTED)

    def test_employee_cannot_submit_a_colleagues_trip(self):
        response = self.as_(self.me).post(
            f"{self.detail(self.colleague_trip)}submit/",
        )

        self.assertEqual(response.status_code, 404)

    def test_employee_cancels_own_upcoming_trip_over_http(self):
        trip = self.set_status(
            self.make_trip(
                self.me,
                start=self.today() + timedelta(days=20),
            ),
            BusinessTripStatus.APPROVED,
        )

        response = self.as_(self.me).post(
            f"{self.detail(trip)}cancel/",
            {"cancellation_reason": "Acara ditunda"},
        )

        self.assertEqual(response.status_code, 200, response.content[:300])

        trip.refresh_from_db()
        self.assertEqual(trip.status, BusinessTripStatus.CANCELLED)

    # ------------------------------------------------------------------
    # Ruas perjalanan
    # ------------------------------------------------------------------

    def leg(self, trip, **extra):
        return BusinessTripLeg.objects.create(
            trip=trip,
            travel_start_date=FAR,
            **extra,
        )

    def test_legs_are_scoped_through_the_trip(self):
        mine = self.leg(self.my_trip)
        theirs = self.leg(self.colleague_trip)

        response = self.as_(self.me).get(LEGS)

        self.assertEqual(response.status_code, 200, response.content[:300])
        self.assertEqual(_ids(response), {mine.pk})

        self.assertEqual(
            self.as_(self.me).get(f"{LEGS}{theirs.pk}/").status_code,
            404,
        )

    def test_leg_cannot_be_added_to_someone_elses_trip(self):
        response = self.as_(self.me).post(
            LEGS,
            {"trip": self.colleague_trip.pk, "travel_start_date": str(FAR)},
        )

        self.assertEqual(response.status_code, 400)
        self.assertFalse(
            BusinessTripLeg.objects.filter(trip=self.colleague_trip).exists(),
        )

    def test_leg_can_be_added_to_own_draft(self):
        response = self.as_(self.me).post(
            LEGS,
            {"trip": self.my_trip.pk, "travel_start_date": str(FAR)},
        )

        self.assertEqual(response.status_code, 201, response.content[:300])

    def test_leg_cannot_be_added_once_submitted(self):
        self.submit(self.my_trip, self.me)

        response = self.as_(self.me).post(
            LEGS,
            {"trip": self.my_trip.pk, "travel_start_date": str(FAR)},
        )

        self.assertEqual(response.status_code, 400)
