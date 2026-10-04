"""
`POST /api/me/attendance/punch/` — adapter tipis di atas
`AttendancePunchService`.

Yang dikunci di sini adalah sisi HTTP-nya: siapa yang boleh memanggil,
kolom apa yang ditolak (identitas dan nilai turunan server), bentuk
balasan yang tidak membocorkan bukti terbatas, dan kode UNAVAILABLE yang
bisa dibedakan frontend. Aturan tap-nya sendiri dikunci di
`apps.hr.tests.attendance.test_self_punch`.
"""

from __future__ import annotations

from unittest import mock
from uuid import uuid4

from rest_framework.test import APIClient

from apps.hr.models import AttendanceLog, EmployeeAttendance
from apps.hr.tests.attendance.punch_base import (
    ENABLED,
    SelfPunchTestCase,
    WEDNESDAY,
    passing_engines,
    wib,
)


URL = "/api/me/attendance/punch/"

NOW = "apps.hr.api.attendance.punch.timezone.now"

LEAKY_KEYS = {
    "face_score",
    "face_threshold",
    "face_provider",
    "face_model_version",
    "liveness_score",
    "liveness_threshold",
    "liveness_provider",
    "gps_accuracy_meters",
    "distance_from_geofence_meters",
    "geofence_radius_meters",
    "policy_snapshot",
    "latitude",
    "longitude",
    "check_in_latitude",
    "employee",
    "employee_id",
    "raw_payload",
}


def walk_keys(node):
    if isinstance(node, dict):
        for key, value in node.items():
            yield key
            yield from walk_keys(value)
    elif isinstance(node, list):
        for item in node:
            yield from walk_keys(item)


class SelfPunchAPITestCase(SelfPunchTestCase):
    reusable_schema_name = "fast_self_service_punch"

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "self-service-punch"
        tenant.name = "Self Service Punch"

    def client_for(self, user=None) -> APIClient:
        client = APIClient(HTTP_HOST=self.tenant.get_primary_domain().domain)

        if user is not None:
            client.force_authenticate(user=user)

        return client

    def body(self, owner, /, **overrides):
        payload = {
            "client_punch_id": str(uuid4()),
            "punch_type": "IN",
            "latitude": "-6.2000000",
            "longitude": "106.8166667",
            "location_accuracy": "12.5",
            "selfie": self.make_selfie(owner).pk,
        }

        payload.update(overrides)

        return payload

    def post(self, user, payload, *, at=None):
        with mock.patch(NOW, return_value=at or wib(WEDNESDAY, 9, 55)):
            return self.client_for(user).post(URL, payload, format="json")


class AccessTests(SelfPunchAPITestCase):
    def test_unauthenticated_is_rejected(self):
        response = self.client_for().post(URL, {}, format="json")

        self.assertEqual(response.status_code, 401)

    def test_account_without_employee_is_rejected(self):
        user = self.make_user()

        response = self.post(user, self.body(user))

        self.assertEqual(response.status_code, 404)
        self.assertEqual(response.data["code"], "employee_not_linked")

    def test_disabled_by_default_writes_nothing(self):
        employee, user = self.make_punch_employee()

        with passing_engines():
            response = self.post(user, self.body(user))

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["code"], "attendance_punch_disabled")
        self.assertFalse(AttendanceLog.objects.filter(employee=employee).exists())

    @ENABLED
    def test_enabled_without_engines_is_unavailable(self):
        employee, user = self.make_punch_employee()

        response = self.post(user, self.body(user))

        self.assertEqual(response.status_code, 403)
        self.assertEqual(response.data["code"], "attendance_punch_not_configured")
        self.assertFalse(AttendanceLog.objects.filter(employee=employee).exists())

    def test_get_only_reports_availability(self):
        # ATT-GPS-1: GET = apakah tap tersedia untuk akun ini. Bawaannya
        # mati; tidak ada daftar mesin, kebijakan, atau data lain.
        _employee, user = self.make_punch_employee()

        response = self.client_for(user).get(URL)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["data"], {"available": False, "trial": False})

    def test_other_methods_are_not_allowed(self):
        _employee, user = self.make_punch_employee()

        for method in ("put", "patch", "delete"):
            with self.subTest(method):
                response = getattr(self.client_for(user), method)(URL, {}, format="json")

                self.assertEqual(response.status_code, 405)


class IdentityTests(SelfPunchAPITestCase):
    punch_enabled = True

    def test_employee_id_cannot_select_another_employee(self):
        _employee, user = self.make_punch_employee()
        victim, _victim_user = self.make_punch_employee()

        for key in ("employee", "employee_id", "user", "employee_number"):
            with self.subTest(key=key), passing_engines():
                response = self.post(
                    user,
                    self.body(user, **{key: victim.pk}),
                )

                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.data["code"], "field_not_accepted")
                self.assertIn(key, response.data["errors"])

        self.assertFalse(AttendanceLog.objects.filter(employee=victim).exists())
        self.assertFalse(EmployeeAttendance.objects.filter(employee=victim).exists())

    def test_punch_always_lands_on_the_logged_in_employee(self):
        employee, user = self.make_punch_employee()
        other, _other_user = self.make_punch_employee()

        with passing_engines():
            response = self.post(user, self.body(user))

        self.assertEqual(response.status_code, 201)

        log = AttendanceLog.objects.get(employee=employee)

        self.assertEqual(log.company_id, self.company.pk)
        self.assertFalse(AttendanceLog.objects.filter(employee=other).exists())

    def test_server_derived_values_are_refused(self):
        _employee, user = self.make_punch_employee()

        for key, value in (
            ("work_date", "2026-07-01"),
            ("server_timestamp", "2026-07-01T09:00:00+07:00"),
            ("face_pass", True),
            ("liveness_pass", True),
            ("inside_geofence", True),
            ("distance", 0),
            ("decision", "accepted"),
            ("company", self.company.pk),
        ):
            with self.subTest(key=key), passing_engines():
                response = self.post(user, self.body(user, **{key: value}))

                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.data["code"], "field_not_accepted")

        self.assertFalse(AttendanceLog.objects.filter(
            employee__user=user,
        ).exists())


class ValidationTests(SelfPunchAPITestCase):
    punch_enabled = True

    def assert_rejected(self, user, field, **overrides):
        with passing_engines():
            response = self.post(user, self.body(user, **overrides))

        self.assertEqual(response.status_code, 400, response.data)
        self.assertIn(field, response.data["errors"])

    def test_malformed_requests(self):
        _employee, user = self.make_punch_employee()

        cases = [
            ("client_punch_id", {"client_punch_id": "not-a-uuid"}),
            ("punch_type", {"punch_type": "BREAK"}),
            ("latitude", {"latitude": "91"}),
            ("longitude", {"longitude": "-181"}),
            ("latitude", {"latitude": "NaN"}),
            ("latitude", {"longitude": None}),
            ("location_accuracy", {"location_accuracy": "-1"}),
            ("selfie", {"selfie": 99999999}),
        ]

        for field, overrides in cases:
            with self.subTest(field=field, overrides=overrides):
                self.assert_rejected(user, field, **overrides)

        self.assertFalse(AttendanceLog.objects.filter(employee__user=user).exists())

    def test_oversized_unknown_payload_is_refused(self):
        _employee, user = self.make_punch_employee()

        self.assert_rejected(user, "device_dump", device_dump="x" * 200_000)

    def test_device_precision_coordinates_are_rounded_not_refused(self):
        employee, user = self.make_punch_employee()

        with passing_engines():
            response = self.post(
                user,
                self.body(
                    user,
                    latitude="-6.200000012345678",
                    longitude="106.816666687654321",
                ),
            )

        self.assertEqual(response.status_code, 201, response.data)

        log = AttendanceLog.objects.get(employee=employee)

        self.assertEqual(str(log.latitude), "-6.2000000")
        self.assertEqual(str(log.longitude), "106.8166667")


class ResponseTests(SelfPunchAPITestCase):
    punch_enabled = True

    def test_accepted_response_and_replay(self):
        _employee, user = self.make_punch_employee()

        payload = self.body(user)

        with passing_engines():
            first = self.post(user, payload)
            retry = self.post(user, payload, at=wib(WEDNESDAY, 9, 57))

        self.assertEqual(first.status_code, 201)

        data = first.data["data"]

        self.assertEqual(data["result"], "accepted")
        self.assertEqual(data["punch_type"], "in")
        self.assertEqual(data["work_date"], "2026-07-01")
        self.assertIsNone(data["reason_code"])
        self.assertFalse(data["replayed"])
        self.assertEqual(data["attendance"]["check_in"], "2026-07-01T09:55:00+07:00")
        self.assertIsNone(data["attendance"]["check_out"])

        self.assertEqual(set(walk_keys(first.data)) & LEAKY_KEYS, set())

        self.assertEqual(retry.status_code, 200)
        self.assertTrue(retry.data["data"]["replayed"])
        self.assertEqual(retry.data["data"]["recorded_at"], data["recorded_at"])

    def test_rejected_response_names_the_reason_only(self):
        _employee, user = self.make_punch_employee()

        with passing_engines():
            response = self.post(user, self.body(user, punch_type="out"))

        self.assertEqual(response.status_code, 201)

        data = response.data["data"]

        self.assertEqual(data["result"], "rejected")
        self.assertEqual(data["reason_code"], "check_out_without_check_in")
        self.assertIsNone(data["attendance"])
        self.assertTrue(data["message"])

    def test_review_required_response(self):
        employee, user = self.make_punch_employee()

        self.make_leave(employee, WEDNESDAY)

        with passing_engines():
            response = self.post(user, self.body(user))

        data = response.data["data"]

        self.assertEqual(data["result"], "review_required")
        self.assertEqual(data["reason_code"], "on_leave")
        self.assertIsNone(data["attendance"])

    def test_reused_id_from_another_account_is_a_conflict(self):
        _employee, user = self.make_punch_employee()
        _other, other_user = self.make_punch_employee()

        punch_id = str(uuid4())

        with passing_engines():
            self.post(user, self.body(user, client_punch_id=punch_id))
            response = self.post(
                other_user,
                self.body(other_user, client_punch_id=punch_id),
            )

        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.data["code"], "attendance_punch_id_conflict")
