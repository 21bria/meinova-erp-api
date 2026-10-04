"""
ATT-GPS-1 di sisi HTTP: `GET/POST /api/me/attendance/punch/` dengan mode
uji coba GPS per tenant.
"""

from __future__ import annotations

from decimal import Decimal

from django.db import connection
from django.test import override_settings

from apps.hr.models import AttendanceGeofence, AttendanceLog, EmployeeAttendance
from apps.hr.tests.attendance.punch_base import WEDNESDAY, passing_engines, wib

from .test_attendance_punch import LEAKY_KEYS, URL, SelfPunchAPITestCase, walk_keys


TRIAL_KEYS = {
    "mode",
    "location_result",
    "accuracy_m",
    "geofence_result",
    "distance_m",
    "radius_m",
    "selfie_stored",
    "biometric_verification",
    "attendance_recorded",
}


class TrialAPITests(SelfPunchAPITestCase):
    def setUp(self):
        super().setUp()

        AttendanceGeofence.objects.create(
            location=self.site,
            latitude=Decimal("-6.2000000"),
            longitude=Decimal("106.8166667"),
            radius_m=100,
        )

    def trial(self):
        return override_settings(
            ATTENDANCE_SELF_PUNCH_TRIAL_SCHEMAS=[connection.schema_name],
        )

    def test_availability(self):
        _employee, user = self.make_punch_employee()

        self.assertEqual(
            self.client_for(user).get(URL).data["data"],
            {"available": False, "trial": False},
        )

        with self.trial():
            self.assertEqual(
                self.client_for(user).get(URL).data["data"],
                {"available": True, "trial": True, "max_gps_accuracy_m": 100},
            )

        with override_settings(ATTENDANCE_SELF_PUNCH_TRIAL_SCHEMAS=["other_tenant"]):
            self.assertEqual(
                self.client_for(user).get(URL).data["data"],
                {"available": False, "trial": False},
            )

        # Dinyalakan global pun tetap tidak tersedia: wajah/liveness belum ada.
        with override_settings(ATTENDANCE_SELF_PUNCH_ENABLED=True):
            self.assertEqual(
                self.client_for(user).get(URL).data["data"],
                {"available": False, "trial": False},
            )

    def test_trial_response_is_labelled_and_records_nothing(self):
        employee, user = self.make_punch_employee(enrolled=False)

        with self.trial():
            response = self.post(user, self.body(user))

        self.assertEqual(response.status_code, 201, response.data)

        data = response.data["data"]

        self.assertEqual(data["result"], "rejected")
        self.assertIsNone(data["attendance"])
        self.assertIn("tidak dicatat", data["message"])

        trial = data["trial"]
        self.assertEqual(set(trial), TRIAL_KEYS)
        self.assertEqual(trial["mode"], "gps_trial")
        self.assertEqual(trial["location_result"], "pass")
        self.assertEqual(trial["accuracy_m"], "12.50")
        self.assertEqual(trial["geofence_result"], "inside")
        self.assertEqual(trial["distance_m"], "0.00")
        self.assertEqual(trial["radius_m"], "100.00")
        self.assertTrue(trial["selfie_stored"])
        self.assertEqual(trial["biometric_verification"], "unavailable")
        self.assertFalse(trial["attendance_recorded"])

        # Tidak membocorkan kolom bukti lain atau pusat geofence.
        self.assertEqual(set(walk_keys(response.data)) & LEAKY_KEYS, set())
        self.assertNotIn("106.8166667", str(response.data))

        self.assertFalse(EmployeeAttendance.objects.filter(employee=employee).exists())
        self.assertTrue(AttendanceLog.objects.filter(employee=employee).exists())

    def test_trial_outside_geofence_reports_distance(self):
        _employee, user = self.make_punch_employee()

        with self.trial():
            response = self.post(user, self.body(user, latitude="-6.1986510"))

        trial = response.data["data"]["trial"]

        self.assertEqual(response.data["data"]["reason_code"], "outside_geofence")
        self.assertEqual(trial["geofence_result"], "outside")
        self.assertAlmostEqual(float(trial["distance_m"]), 150.0, delta=0.5)

    def test_trial_without_selfie(self):
        _employee, user = self.make_punch_employee()

        with self.trial():
            response = self.post(user, self.body(user, selfie=None))

        self.assertFalse(response.data["data"]["trial"]["selfie_stored"])

    def test_non_trial_response_has_no_trial_block(self):
        _employee, user = self.make_punch_employee()

        with override_settings(ATTENDANCE_SELF_PUNCH_ENABLED=True), passing_engines():
            response = self.post(user, self.body(user))

        self.assertEqual(response.data["data"]["result"], "accepted")
        self.assertNotIn("trial", response.data["data"])

    def test_trial_does_not_bypass_authentication_or_scope(self):
        employee, user = self.make_punch_employee()
        other, _other_user = self.make_punch_employee()

        with self.trial():
            for method in ("get", "post"):
                with self.subTest(method):
                    response = getattr(self.client_for(None), method)(URL, {}, format="json")

                    self.assertIn(response.status_code, (401, 403))

            response = self.post(user, self.body(user, employee_id=other.pk))

            self.assertEqual(response.status_code, 400)
            self.assertEqual(response.data["code"], "field_not_accepted")

        self.assertFalse(AttendanceLog.objects.filter(employee=other).exists())

    def test_invalid_coordinates_are_rejected_before_anything_is_written(self):
        employee, user = self.make_punch_employee()

        with self.trial():
            for field, value in (("latitude", "91"), ("longitude", "-181")):
                with self.subTest(field):
                    response = self.post(user, self.body(user, **{field: value}))

                    self.assertEqual(response.status_code, 400, response.data)

        self.assertFalse(AttendanceLog.objects.filter(employee=employee).exists())

    def test_wall_clock_recorded_at_unchanged(self):
        _employee, user = self.make_punch_employee()

        with self.trial():
            response = self.post(user, self.body(user), at=wib(WEDNESDAY, 9, 55))

        self.assertEqual(response.data["data"]["recorded_at"], "2026-07-01T09:55:00+07:00")
