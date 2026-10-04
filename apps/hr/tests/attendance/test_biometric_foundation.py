"""
ATT-BIO-2A — fondasi biometrik netral penyedia.

Tidak ada pengenalan wajah atau liveness sungguhan di sini. Yang dikunci
adalah **kontrak dan transisi keadaannya**: siklus hidup pendaftaran,
subjek yang diserahkan ke mesin, ambang yang diputuskan ERP, kosakata
sebab, deteksi selfie identik, dan bahwa tap mesin (DEVICE) tidak pernah
menyentuh semua itu. Mesin wajah/liveness = pengganti test
(`punch_base.FixedCheck`).
"""

from __future__ import annotations

import uuid
from datetime import time
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import override_settings
from django.utils import timezone

from apps.hr.api.attendance import punch_checks as checks
from apps.hr.api.attendance.biometric_enrollment import BiometricEnrollmentService
from apps.hr.api.attendance.punch import (
    AttendancePunchNotConfigured,
    AttendancePunchService,
)
from apps.hr.api.attendance_sync.services import AttendanceSyncService
from apps.hr.models import (
    AttendanceLog,
    AttendanceLogVerification,
    AttendancePermission,
    AttendancePermissionStatus,
    AttendancePermissionType,
    BiometricEnrollmentStatus,
    EmployeeAttendance,
    EmployeeBiometricEnrollment,
)
from apps.hr.models.attendance.verification import PunchDecision, PunchReason
from apps.uploads.models import UploadedFile

from .punch_base import (
    ENABLED,
    TEST_FACE_MODEL,
    TEST_FACE_POLICY,
    TEST_FACE_PROVIDER,
    THURSDAY,
    WEDNESDAY,
    ExplodingCheck,
    FixedCheck,
    SelfPunchTestCase,
    face_pass,
    passing_engines,
    unique_png,
    wib,
)


def row_of(employee, day):
    return EmployeeAttendance.objects.filter(
        employee=employee,
        work_date=day,
        is_deleted=False,
    ).first()


def enrollments_of(employee):
    return list(
        EmployeeBiometricEnrollment.objects
        .filter(employee=employee)
        .order_by("version")
    )


class BiometricTestCase(SelfPunchTestCase):
    punch_enabled = True

    def assert_rejected_without_attendance(self, result, reason, day=WEDNESDAY):
        self.assertEqual(result.decision, PunchDecision.REJECTED)
        self.assertEqual(result.verification.reason_code, reason)
        self.assertIsNone(result.attendance)
        self.assertIsNone(result.log.attendance_id)
        self.assertTrue(result.log.is_processed)
        self.assertIsNone(row_of(result.log.employee, day))


# ======================================================================
# 1. Siklus hidup pendaftaran
# ======================================================================


class EnrollmentLifecycleTests(BiometricTestCase):
    punch_enabled = False

    def test_enroll_creates_an_active_random_subject(self):
        employee, user = self.make_punch_employee(enrolled=False)
        other, _ = self.make_punch_employee(enrolled=False)

        first = BiometricEnrollmentService.enroll(
            employee=employee, provider=TEST_FACE_PROVIDER, user=user,
        )
        second = BiometricEnrollmentService.enroll(
            employee=other, provider=TEST_FACE_PROVIDER, user=user,
        )

        self.assertEqual(first.status, BiometricEnrollmentStatus.ACTIVE)
        self.assertEqual(first.version, 1)
        self.assertEqual(first.enrolled_by, user)
        self.assertIsNotNone(first.enrolled_at)
        self.assertIsNone(first.revoked_at)

        # uuid4 acak, bukan turunan data pegawai.
        self.assertEqual(first.subject_id.version, 4)
        self.assertNotEqual(first.subject_id, second.subject_id)
        for value in (employee.employee_number, employee.full_name):
            self.assertNotIn(value.lower(), str(first.subject_id))

        # Representasi string (bisa sampai ke log) tanpa subject_id.
        self.assertNotIn(str(first.subject_id), str(first))

    def test_only_one_active_enrollment_per_provider(self):
        employee, user = self.make_punch_employee(enrolled=False)

        BiometricEnrollmentService.enroll(
            employee=employee, provider=TEST_FACE_PROVIDER, user=user,
        )

        with self.assertRaises(ValidationError):
            BiometricEnrollmentService.enroll(
                employee=employee, provider=TEST_FACE_PROVIDER, user=user,
            )

        # Database juga menolaknya, bukan cuma service.
        with self.assertRaises(IntegrityError), transaction.atomic():
            EmployeeBiometricEnrollment.objects.create(
                employee=employee,
                provider=TEST_FACE_PROVIDER,
                version=9,
                enrollment_source="hr_assisted",
                enrolled_at=timezone.now(),
            )

        # Penyedia lain = pendaftaran lain.
        other = BiometricEnrollmentService.enroll(
            employee=employee, provider="another-provider", user=user,
        )
        self.assertEqual(other.version, 1)

    def test_reenroll_revokes_and_creates_a_new_identity(self):
        employee, user = self.make_punch_employee(enrolled=False)

        old = BiometricEnrollmentService.enroll(
            employee=employee, provider=TEST_FACE_PROVIDER, user=user,
        )
        new = BiometricEnrollmentService.reenroll(
            employee=employee, provider=TEST_FACE_PROVIDER, user=user, reason="Foto buram",
        )

        old.refresh_from_db()

        self.assertEqual(old.status, BiometricEnrollmentStatus.REVOKED)
        self.assertIsNotNone(old.revoked_at)
        self.assertEqual(old.revoked_by, user)
        self.assertEqual(old.revocation_reason, "Foto buram")

        self.assertEqual(new.status, BiometricEnrollmentStatus.ACTIVE)
        self.assertEqual(new.version, 2)
        self.assertNotEqual(new.subject_id, old.subject_id)
        self.assertEqual([e.pk for e in enrollments_of(employee)], [old.pk, new.pk])

        subject = BiometricEnrollmentService.subject_for(employee, TEST_FACE_PROVIDER)
        self.assertEqual(subject.subject_id, str(new.subject_id))
        self.assertEqual(subject.version, 2)

    def test_revoked_enrollment_is_final_and_history_is_immutable(self):
        employee, user = self.make_punch_employee(enrolled=False)

        enrollment = BiometricEnrollmentService.enroll(
            employee=employee, provider=TEST_FACE_PROVIDER, user=user,
        )

        # Identitas tidak bisa ditimpa, bahkan saat ACTIVE.
        enrollment.subject_id = uuid.uuid4()
        with self.assertRaises(ValidationError):
            enrollment.save()
        enrollment.refresh_from_db()

        BiometricEnrollmentService.revoke(enrollment, user=user, reason="Keluar")

        with self.assertRaises(ValidationError):
            BiometricEnrollmentService.revoke(enrollment, user=user)

        enrollment.refresh_from_db()
        enrollment.status = BiometricEnrollmentStatus.ACTIVE
        enrollment.revoked_at = None
        with self.assertRaises(ValidationError):
            enrollment.save()

        with self.assertRaises(ValidationError):
            enrollment.delete()
        with self.assertRaises(ValidationError):
            EmployeeBiometricEnrollment.objects.filter(pk=enrollment.pk).delete()
        with self.assertRaises(ValidationError):
            EmployeeBiometricEnrollment.objects.filter(pk=enrollment.pk).update(
                status=BiometricEnrollmentStatus.ACTIVE,
            )

        self.assertIsNone(BiometricEnrollmentService.subject_for(employee, TEST_FACE_PROVIDER))

    def test_revoked_status_requires_revoked_at_in_the_database(self):
        employee, _user = self.make_punch_employee(enrolled=False)

        with self.assertRaises(IntegrityError), transaction.atomic():
            EmployeeBiometricEnrollment.objects.create(
                employee=employee,
                provider=TEST_FACE_PROVIDER,
                version=1,
                status=BiometricEnrollmentStatus.REVOKED,
                enrollment_source="hr_assisted",
                enrolled_at=timezone.now(),
            )

    def test_avatar_is_not_an_enrollment(self):
        employee, user = self.make_punch_employee(enrolled=False)

        avatar = self.make_selfie(user, category=UploadedFile.Category.AVATAR)
        employee.avatar_file = avatar
        employee.save(update_fields=["avatar_file"])

        self.assertEqual(enrollments_of(employee), [])
        self.assertIsNone(BiometricEnrollmentService.subject_for(employee, TEST_FACE_PROVIDER))

        with ENABLED, passing_engines():
            result = self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55))

        self.assert_rejected_without_attendance(result, PunchReason.NOT_ENROLLED)
        self.assertEqual(enrollments_of(employee), [])


# ======================================================================
# 2. Ambang: tidak terkalibrasi = tidak pernah PASS
# ======================================================================


class ThresholdPolicyTests(BiometricTestCase):
    def test_production_defaults_stay_fail_closed(self):
        employee, user = self.make_punch_employee()

        self.assertFalse(checks.get_check(checks.FACE).configured)
        self.assertFalse(checks.get_check(checks.LIVENESS).configured)
        self.assertIsNone(checks.FaceMatchPolicy.from_settings())

        policy = checks.resolve_policy(employee, WEDNESDAY)
        self.assertTrue(policy.is_required(checks.FACE))
        self.assertTrue(policy.is_required(checks.LIVENESS))

        with self.assertRaises(AttendancePunchNotConfigured):
            self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55))

        self.assertFalse(AttendanceLog.objects.filter(employee=employee).exists())

    def test_engine_without_calibrated_threshold_is_not_configured(self):
        employee, user = self.make_punch_employee()

        for policy in (
            None,
            {**TEST_FACE_POLICY, "provider": "someone-else"},
            {**TEST_FACE_POLICY, "threshold": None},
            {**TEST_FACE_POLICY, "threshold": 0.8},
            {**TEST_FACE_POLICY, "threshold": "NaN"},
            {**TEST_FACE_POLICY, "comparator": ">"},
            {**TEST_FACE_POLICY, "model_version": ""},
        ):
            with self.subTest(policy=policy), passing_engines(face_policy=policy):
                with self.assertRaises(AttendancePunchNotConfigured):
                    self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55))

        self.assertFalse(AttendanceLog.objects.filter(employee=employee).exists())

    def test_comparator_semantics(self):
        similarity = checks.FaceMatchPolicy(
            provider="p", model_version="m", threshold=Decimal("0.80"), comparator="gte",
        )
        distance = checks.FaceMatchPolicy(
            provider="p", model_version="m", threshold=Decimal("0.40"), comparator="lte",
        )

        self.assertTrue(similarity.accepts(Decimal("0.80")))
        self.assertFalse(similarity.accepts(Decimal("0.79")))
        self.assertTrue(distance.accepts(Decimal("0.40")))
        self.assertFalse(distance.accepts(Decimal("0.41")))
        self.assertFalse(similarity.accepts(None))

    def test_erp_policy_decides_the_match_not_the_engine(self):
        cases = (
            (face_pass("0.79"), "fail", PunchReason.FACE_MISMATCH),
            (FixedCheck("pass", model_version=TEST_FACE_MODEL), "error", PunchReason.VALIDATOR_ERROR),
            (face_pass("0.99", model_version="other-model"), "error", PunchReason.VALIDATOR_ERROR),
            (FixedCheck("fail", score=Decimal("0.99"), model_version=TEST_FACE_MODEL), "fail", PunchReason.FACE_MISMATCH),
        )

        for engine, face_result, reason in cases:
            employee, user = self.make_punch_employee()

            with self.subTest(face_result=face_result, reason=reason), passing_engines(face=engine):
                result = self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55))

                self.assert_rejected_without_attendance(result, reason)
                self.assertEqual(result.verification.face_result, face_result)
                self.assertEqual(result.verification.face_threshold, Decimal("0.80"))


# ======================================================================
# 3. Skenario verifikasi (mesin pengganti)
# ======================================================================


class VerificationScenarioTests(BiometricTestCase):
    def test_enrolled_employee_with_matching_face_is_accepted(self):
        employee, user = self.make_punch_employee()
        subject = BiometricEnrollmentService.subject_for(employee, TEST_FACE_PROVIDER)

        with passing_engines() as engines:
            result = self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55))

        self.assertEqual(result.decision, PunchDecision.ACCEPTED)

        verification = result.verification
        self.assertEqual(verification.face_result, "pass")
        self.assertEqual(verification.face_score, Decimal("0.93"))
        self.assertEqual(verification.face_threshold, Decimal("0.80"))
        self.assertEqual(verification.face_provider, TEST_FACE_PROVIDER)
        self.assertEqual(verification.face_model_version, TEST_FACE_MODEL)
        self.assertEqual(verification.liveness_result, "pass")
        self.assertEqual(verification.policy_snapshot["face_match"], TEST_FACE_POLICY)
        self.assertTrue(verification.policy_snapshot["configured"][checks.FACE])

        # Tertaut: log → verifikasi → baris harian.
        self.assertEqual(verification.log_id, result.log.pk)
        self.assertEqual(result.log.attendance_id, result.attendance.pk)
        self.assertEqual(row_of(employee, WEDNESDAY).pk, result.attendance.pk)

        # Mesin wajah menerima subjek pegawai ini — dan hanya itu.
        [evidence] = engines[checks.FACE].calls
        self.assertEqual(evidence.subject, subject)
        self.assertEqual(evidence.employee.pk, employee.pk)

        # Bukti beku.
        verification.face_score = Decimal("0.10")
        with self.assertRaises(ValidationError):
            verification.save()

    def test_failure_states(self):
        cases = (
            ("face mismatch", {"face": FixedCheck("fail", score=Decimal("0.2"), model_version=TEST_FACE_MODEL)},
             PunchReason.FACE_MISMATCH, {"face_result": "fail"}),
            ("no face", {"face": FixedCheck("no_face")},
             PunchReason.NO_FACE, {"face_result": "no_face"}),
            ("multiple faces", {"face": FixedCheck("multiple_faces")},
             PunchReason.MULTIPLE_FACES, {"face_result": "multiple_faces"}),
            ("liveness sees multiple faces", {"liveness": FixedCheck("multiple_faces")},
             PunchReason.MULTIPLE_FACES, {"liveness_result": "multiple_faces", "face_result": "not_run"}),
            ("failed liveness", {"liveness": FixedCheck("fail")},
             PunchReason.LIVENESS_FAILED, {"liveness_result": "fail", "face_result": "not_run"}),
            ("verifier error", {"face": ExplodingCheck()},
             PunchReason.VALIDATOR_ERROR, {"face_result": "error"}),
            ("liveness verifier error", {"liveness": ExplodingCheck()},
             PunchReason.VALIDATOR_ERROR, {"liveness_result": "error", "face_result": "not_run"}),
        )

        for label, engines, reason, fields in cases:
            employee, user = self.make_punch_employee()

            with self.subTest(label), passing_engines(**engines):
                result = self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55))

                self.assert_rejected_without_attendance(result, reason)

                for name, value in fields.items():
                    self.assertEqual(getattr(result.verification, name), value, name)

                # Pengecualian mesin tidak pernah tersimpan mentah.
                self.assertNotIn("engine down", result.verification.reason_detail)

    def test_not_enrolled_never_reaches_any_biometric_engine(self):
        employee, user = self.make_punch_employee(enrolled=False)

        with passing_engines() as engines:
            result = self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55))

        self.assert_rejected_without_attendance(result, PunchReason.NOT_ENROLLED)
        self.assertEqual(result.verification.face_result, "not_enrolled")
        self.assertEqual(result.verification.face_provider, TEST_FACE_PROVIDER)
        self.assertEqual(result.verification.liveness_result, "not_run")
        self.assertEqual(result.verification.location_result, "pass")
        self.assertEqual(engines[checks.FACE].calls, [])
        self.assertEqual(engines[checks.LIVENESS].calls, [])

    def test_revoked_enrollment_counts_as_not_enrolled(self):
        employee, user = self.make_punch_employee()

        [enrollment] = enrollments_of(employee)
        BiometricEnrollmentService.revoke(enrollment, user=user)

        with passing_engines():
            result = self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55))

        self.assert_rejected_without_attendance(result, PunchReason.NOT_ENROLLED)

    def test_failed_liveness_never_reaches_face_matching(self):
        employee, user = self.make_punch_employee()

        with passing_engines(liveness=FixedCheck("fail")) as engines:
            self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55))

        self.assertEqual(engines[checks.FACE].calls, [])

    def test_gps_failure_still_wins_before_biometrics(self):
        employee, user = self.make_punch_employee()

        with passing_engines() as engines:
            result = self.punch(
                employee, user, "in", wib(WEDNESDAY, 9, 55), accuracy=None,
            )

        self.assert_rejected_without_attendance(result, PunchReason.LOCATION_LOW_ACCURACY)
        self.assertEqual(result.verification.face_result, "not_run")
        self.assertEqual(engines[checks.FACE].calls, [])
        self.assertEqual(engines[checks.LIVENESS].calls, [])

    def test_engine_only_ever_sees_the_punching_employees_subject(self):
        enrolled, _ = self.make_punch_employee()
        unenrolled, user = self.make_punch_employee(enrolled=False)

        # Pegawai lain terdaftar; pegawai yang tap tidak → NOT_ENROLLED,
        # bukan pencocokan dengan pendaftaran orang lain.
        with passing_engines() as engines:
            result = self.punch(unenrolled, user, "in", wib(WEDNESDAY, 9, 55))

        self.assertEqual(result.verification.reason_code, PunchReason.NOT_ENROLLED)
        self.assertEqual(engines[checks.FACE].calls, [])
        self.assertIsNotNone(BiometricEnrollmentService.subject_for(enrolled, TEST_FACE_PROVIDER))


# ======================================================================
# 4. Selfie identik
# ======================================================================


class SelfieReplayTests(BiometricTestCase):
    def test_identical_selfie_bytes_are_rejected_before_any_check(self):
        employee, user = self.make_punch_employee()
        content = unique_png()

        with passing_engines():
            first = self.punch(
                employee, user, "in", wib(WEDNESDAY, 9, 55),
                photo=self.make_selfie(user, content=content),
            )

        self.assertEqual(first.decision, PunchDecision.ACCEPTED)
        before = row_of(employee, WEDNESDAY)

        # Upload baru, byte sama, tap baru.
        with passing_engines() as engines:
            replay = self.punch(
                employee, user, "out", wib(WEDNESDAY, 18, 5),
                photo=self.make_selfie(user, content=content),
            )

        self.assertEqual(replay.decision, PunchDecision.REJECTED)
        self.assertEqual(replay.verification.reason_code, PunchReason.SELFIE_REPLAYED)
        self.assertIsNone(replay.attendance)
        self.assertEqual(replay.verification.face_result, "not_run")
        self.assertEqual(replay.verification.liveness_result, "not_run")
        self.assertEqual(engines[checks.FACE].calls, [])
        self.assertEqual(engines[checks.LIVENESS].calls, [])

        after = row_of(employee, WEDNESDAY)
        self.assertEqual(after.check_out, before.check_out)

        # Bukti percobaan ulangannya tetap tersimpan.
        self.assertTrue(AttendanceLog.objects.filter(pk=replay.log.pk).exists())

    def test_bytes_of_a_rejected_attempt_also_count(self):
        employee, user = self.make_punch_employee()
        content = unique_png()

        with passing_engines(face=FixedCheck("no_face")):
            self.punch(
                employee, user, "in", wib(WEDNESDAY, 9, 55),
                photo=self.make_selfie(user, content=content),
            )

        with passing_engines():
            again = self.punch(
                employee, user, "in", wib(WEDNESDAY, 9, 58),
                photo=self.make_selfie(user, content=content),
            )

        self.assertEqual(again.verification.reason_code, PunchReason.SELFIE_REPLAYED)

    def test_another_employees_identical_bytes_are_not_reported(self):
        first, first_user = self.make_punch_employee()
        second, second_user = self.make_punch_employee()
        content = unique_png()

        with passing_engines():
            self.punch(
                first, first_user, "in", wib(WEDNESDAY, 9, 55),
                photo=self.make_selfie(first_user, content=content),
            )

            result = self.punch(
                second, second_user, "in", wib(WEDNESDAY, 9, 56),
                photo=self.make_selfie(second_user, content=content),
            )

        # Tidak membocorkan bahwa orang lain pernah mengunggahnya; foto
        # orang lain di akun sendiri adalah urusan pencocokan wajah.
        self.assertNotEqual(result.verification.reason_code, PunchReason.SELFIE_REPLAYED)

    def test_similar_but_not_identical_selfies_are_not_replays(self):
        employee, user = self.make_punch_employee()

        with passing_engines():
            first = self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55))
            second = self.punch(employee, user, "out", wib(WEDNESDAY, 18, 5))

        self.assertEqual(first.decision, PunchDecision.ACCEPTED)
        self.assertEqual(second.decision, PunchDecision.ACCEPTED)

    def test_legitimate_retry_is_a_replay_of_the_result_not_a_selfie_replay(self):
        employee, user = self.make_punch_employee()
        req = self.request("in", user=user)

        with passing_engines() as engines:
            first = self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55), req=req)
            retry = self.punch(employee, user, "in", wib(WEDNESDAY, 9, 57), req=req)

        self.assertEqual(first.decision, PunchDecision.ACCEPTED)
        self.assertTrue(retry.replayed)
        self.assertEqual(retry.log.pk, first.log.pk)
        self.assertEqual(retry.decision, PunchDecision.ACCEPTED)
        self.assertEqual(AttendanceLog.objects.filter(employee=employee).count(), 1)
        self.assertEqual(len(engines[checks.FACE].calls), 1)


# ======================================================================
# 5. Semantik presensi yang sudah diterima tetap
# ======================================================================


class AttendanceSemanticsTests(BiometricTestCase):
    def test_overnight_work_date_with_biometric_verification(self):
        employee, user = self.make_punch_employee(shift=self.late_night_shift)

        with passing_engines():
            check_in = self.punch(employee, user, "in", wib(WEDNESDAY, 20, 0))
            check_out = self.punch(employee, user, "out", wib(THURSDAY, 2, 0))

        self.assertEqual(check_in.decision, PunchDecision.ACCEPTED)
        self.assertEqual(check_out.decision, PunchDecision.ACCEPTED)
        self.assertEqual(check_out.verification.work_date, WEDNESDAY)
        self.assertEqual(check_out.attendance.pk, check_in.attendance.pk)
        self.assertIsNone(row_of(employee, THURSDAY))

    def test_permission_effect_with_biometric_verification(self):
        employee, user = self.make_punch_employee()

        AttendancePermission.objects.create(
            employee=employee,
            company=self.company,
            location=self.site,
            permission_type=AttendancePermissionType.LATE_ARRIVAL,
            date=WEDNESDAY,
            end_time=time(12, 0),
            reason="Urus dokumen",
            status=AttendancePermissionStatus.APPROVED,
        )

        with passing_engines():
            result = self.punch(employee, user, "in", wib(WEDNESDAY, 11, 0))

        self.assertEqual(result.decision, PunchDecision.ACCEPTED)
        self.assertEqual(result.attendance.excused_late_minutes, 60)
        self.assertEqual(result.attendance.permission_state, "excused")

    def test_device_sync_never_invokes_biometric_checks(self):
        employee, _user = self.make_punch_employee()
        device = self.make_device("BIO-DEV-1")

        with passing_engines() as engines:
            item = AttendanceSyncService.process_record(
                record={
                    "source_key": "bio-dev-1",
                    "employee_code": employee.employee_number,
                    "log_time": wib(WEDNESDAY, 9, 55),
                    "log_type": "in",
                },
                device=device,
            )

        self.assertTrue(item["success"])

        for key in (checks.FACE, checks.LIVENESS, checks.GEOFENCE):
            self.assertEqual(engines[key].calls, [], key)

        log = AttendanceLog.objects.get(device=device)
        self.assertEqual(log.source, "device")
        self.assertEqual(log.attendance_id, item["attendance_id"])
        self.assertFalse(AttendanceLogVerification.objects.filter(log=log).exists())


# ======================================================================
# 6. Tidak ada jalur baca untuk pendaftaran
# ======================================================================


class ExposureTests(BiometricTestCase):
    punch_enabled = False

    def test_no_url_exposes_biometric_enrollment(self):
        from django.urls import get_resolver

        def walk(patterns, prefix=""):
            for pattern in patterns:
                text = prefix + str(pattern.pattern)

                if hasattr(pattern, "url_patterns"):
                    yield from walk(pattern.url_patterns, text)
                else:
                    yield text, pattern

        for text, pattern in walk(get_resolver().url_patterns):
            with self.subTest(text):
                self.assertNotIn("biometric", text.lower())

                view = getattr(pattern.callback, "cls", None)
                queryset = getattr(view, "queryset", None)
                model = getattr(queryset, "model", None)
                self.assertIsNot(model, EmployeeBiometricEnrollment)

    def test_no_serializer_reads_enrollment_or_subject(self):
        from django.urls import get_resolver
        from rest_framework import serializers

        get_resolver().url_patterns  # memuat semua view → semua serializer

        def subclasses(cls):
            for sub in cls.__subclasses__():
                yield sub
                yield from subclasses(sub)

        for serializer in set(subclasses(serializers.ModelSerializer)):
            meta = getattr(serializer, "Meta", None)
            model = getattr(meta, "model", None)
            fields = getattr(meta, "fields", ()) or ()

            with self.subTest(serializer.__qualname__):
                self.assertIsNot(model, EmployeeBiometricEnrollment)

                if isinstance(fields, (list, tuple)):
                    self.assertNotIn("biometric_enrollments", fields)
                    self.assertNotIn("subject_id", fields)

    def test_enrollment_model_has_no_biometric_material_columns(self):
        names = {field.name for field in EmployeeBiometricEnrollment._meta.get_fields()}

        for forbidden in ("photo", "image", "embedding", "template", "vector", "token", "secret", "password"):
            for name in names:
                self.assertNotIn(forbidden, name)

    def test_policy_snapshot_carries_no_subject(self):
        employee, user = self.make_punch_employee()
        subject = BiometricEnrollmentService.subject_for(employee, TEST_FACE_PROVIDER)

        with ENABLED, passing_engines():
            result = self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55))

        stored = AttendanceLogVerification.objects.filter(pk=result.verification.pk).values().get()
        log = AttendanceLog.objects.filter(pk=result.log.pk).values().get()

        self.assertNotIn(subject.subject_id, str(stored))
        self.assertNotIn(subject.subject_id, str(log))
