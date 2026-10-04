"""
ATT-BIO-2A di sisi HTTP `POST /api/me/attendance/punch/`.

Balasan untuk pegawai tidak memuat subjek pendaftaran, skor, ambang,
penyedia, atau versi model; kolom biometrik kiriman client ditolak; dan
sebab-sebab baru dijawab dengan pesan netral tanpa isi pengecualian
mesin.
"""

from __future__ import annotations

from decimal import Decimal

from apps.hr.api.attendance.biometric_enrollment import BiometricEnrollmentService
from apps.hr.tests.attendance.punch_base import (
    TEST_FACE_MODEL,
    TEST_FACE_PROVIDER,
    WEDNESDAY,
    ExplodingCheck,
    FixedCheck,
    passing_engines,
    unique_png,
    wib,
)

from .test_attendance_punch import LEAKY_KEYS, SelfPunchAPITestCase, walk_keys


BIOMETRIC_LEAKY_KEYS = LEAKY_KEYS | {
    "subject_id",
    "subject",
    "enrollment",
    "biometric_enrollments",
    "liveness_model_version",
}


class BiometricResponseTests(SelfPunchAPITestCase):
    punch_enabled = True

    def assert_clean(self, response, employee):
        subject = BiometricEnrollmentService.subject_for(employee, TEST_FACE_PROVIDER)

        self.assertEqual(set(walk_keys(response.data)) & BIOMETRIC_LEAKY_KEYS, set())

        body = str(response.data)

        for value in (TEST_FACE_PROVIDER, TEST_FACE_MODEL, "0.93", "0.80", "engine down"):
            self.assertNotIn(value, body)

        if subject is not None:
            self.assertNotIn(subject.subject_id, body)

    def test_accepted_response_carries_no_biometric_material(self):
        employee, user = self.make_punch_employee()

        with passing_engines():
            response = self.post(user, self.body(user))

        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(response.data["data"]["result"], "accepted")
        self.assert_clean(response, employee)

    def test_new_reasons_have_neutral_messages(self):
        cases = (
            ("no_face", {"face": FixedCheck("no_face")}, True),
            ("multiple_faces", {"face": FixedCheck("multiple_faces")}, True),
            ("not_enrolled", {}, False),
            ("validator_error", {"face": ExplodingCheck()}, True),
            (
                "face_mismatch",
                {"face": FixedCheck("fail", score=Decimal("0.2"), model_version=TEST_FACE_MODEL)},
                True,
            ),
        )

        for reason, engines, enrolled in cases:
            employee, user = self.make_punch_employee(enrolled=enrolled)

            with self.subTest(reason), passing_engines(**engines):
                response = self.post(user, self.body(user))

                self.assertEqual(response.status_code, 201, response.data)

                data = response.data["data"]

                self.assertEqual(data["result"], "rejected")
                self.assertEqual(data["reason_code"], reason)
                self.assertIsNone(data["attendance"])
                self.assertTrue(data["message"])
                self.assert_clean(response, employee)

    def test_replayed_selfie_response(self):
        employee, user = self.make_punch_employee()
        content = unique_png()

        with passing_engines():
            first = self.post(
                user,
                self.body(user, selfie=self.make_selfie(user, content=content).pk),
            )
            replay = self.post(
                user,
                self.body(
                    user,
                    punch_type="out",
                    selfie=self.make_selfie(user, content=content).pk,
                ),
                at=wib(WEDNESDAY, 18, 5),
            )

        self.assertEqual(first.data["data"]["result"], "accepted")
        self.assertEqual(replay.status_code, 201, replay.data)
        self.assertEqual(replay.data["data"]["reason_code"], "selfie_replayed")
        self.assertTrue(replay.data["data"]["message"])
        self.assert_clean(replay, employee)

    def test_client_cannot_supply_biometric_values(self):
        employee, user = self.make_punch_employee()
        subject = BiometricEnrollmentService.subject_for(employee, TEST_FACE_PROVIDER)

        for key, value in (
            ("subject_id", subject.subject_id),
            ("face_score", "0.99"),
            ("face_result", "pass"),
            ("liveness_result", "pass"),
            ("enrollment", "1"),
        ):
            with self.subTest(key), passing_engines():
                response = self.post(user, self.body(user, **{key: value}))

                self.assertEqual(response.status_code, 400, response.data)
                self.assertEqual(response.data["code"], "field_not_accepted")
