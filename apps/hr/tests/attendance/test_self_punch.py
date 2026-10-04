"""
ATT-BIO-1 — tap kehadiran Self Service sampai `EmployeeAttendance`.

Yang dikunci:

1. **Gagal tertutup.** Mati bawaannya; menyala tanpa mesin wajah/
   liveness/geofence tetap tidak menerima apa pun dan tidak menulis apa
   pun. Mesin yang meledak atau menjawab di luar kosakatanya = REJECTED,
   bukan 500, bukan PASS.
2. **Bukti selalu tersimpan, presensi hanya dari yang ACCEPTED.** Tap
   REJECTED / REVIEW_REQUIRED punya `AttendanceLog` + verifikasi, dengan
   `attendance` kosong dan baris harian tidak tersentuh.
3. **Idempoten per `client_punch_id`**, mesin status IN/OUT, jeda
   minimum, kunci per pegawai.
4. **Hari kerja kanonik** — shift 20:00–05:00, OUT 02:00 milik hari
   sebelumnya.
5. **Semantik yang sudah ada tetap**: cuti, mangkir hasil penutup hari,
   izin, Business Trip, hari tidak terjadwal, payroll terkunci.
6. **Payroll** tetap hanya membaca `EmployeeAttendance`.
"""

from __future__ import annotations

from datetime import time
from decimal import Decimal
from pathlib import Path
from unittest import mock
from uuid import uuid4

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import connection
from django.test import override_settings
from django.test.utils import CaptureQueriesContext
from rest_framework.exceptions import ValidationError

from apps.hr.api.attendance import punch_checks as checks
from apps.hr.api.attendance.punch import (
    AttendanceNoOrganization,
    AttendanceNotApplicable,
    AttendancePunchDisabled,
    AttendancePunchIdConflict,
    AttendancePunchNotConfigured,
    AttendancePunchService,
)
from apps.hr.imports.services.attendance import AttendanceImportWriter
from apps.hr.models import (
    AttendanceLog,
    AttendanceLogVerification,
    AttendancePermission,
    AttendancePermissionStatus,
    AttendancePermissionType,
    EmployeeAttendance,
    OrganizationAssignment,
)
from apps.hr.models.attendance.choices import (
    AttendanceSource,
    AttendanceStatus,
)
from apps.hr.models.attendance.verification import (
    PunchCheckRequirement,
    PunchDecision,
    PunchReason,
)
from apps.uploads.models import UploadedFile
from apps.uploads.services.access_service import FileAccessService

from .punch_base import (
    ENABLED,
    ExplodingCheck,
    FixedCheck,
    SATURDAY,
    SelfPunchTestCase,
    THURSDAY,
    WEDNESDAY,
    passing_engines,
    wib,
)


def logs_of(employee):
    return AttendanceLog.objects.filter(employee=employee)


def row_of(employee, day):
    return EmployeeAttendance.objects.filter(
        employee=employee,
        work_date=day,
        is_deleted=False,
    ).first()


# ======================================================================
# 1. Gagal tertutup
# ======================================================================


class FeatureSafetyTests(SelfPunchTestCase):
    def test_disabled_by_default(self):
        self.assertFalse(settings.ATTENDANCE_SELF_PUNCH_ENABLED)

        employee, user = self.make_punch_employee()

        with passing_engines(), self.assertRaises(AttendancePunchDisabled):
            self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55))

        self.assertFalse(logs_of(employee).exists())
        self.assertIsNone(row_of(employee, WEDNESDAY))

    @ENABLED
    def test_enabled_without_engines_fails_closed_and_writes_nothing(self):
        employee, user = self.make_punch_employee()

        with self.assertRaises(AttendancePunchNotConfigured):
            self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55))

        self.assertFalse(logs_of(employee).exists())
        self.assertFalse(AttendanceLogVerification.objects.filter(
            log__employee=employee,
        ).exists())
        self.assertIsNone(row_of(employee, WEDNESDAY))

    def test_one_missing_engine_is_enough_to_fail_closed(self):
        employee, user = self.make_punch_employee()

        # Wajah dan liveness terpasang, geofence belum.
        with ENABLED, checks.override_checks(
            face=FixedCheck("pass"),
            liveness=FixedCheck("pass"),
        ), self.assertRaises(AttendancePunchNotConfigured):
            self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55))

        self.assertFalse(logs_of(employee).exists())

    def test_default_policy_requires_every_check(self):
        employee, _user = self.make_punch_employee()

        policy = checks.resolve_policy(employee, WEDNESDAY)

        self.assertEqual(
            policy.requirements,
            {key: PunchCheckRequirement.REQUIRED for key in checks.CHECK_ORDER},
        )

        # Tanpa mesin pengganti, wajah dan liveness memang belum terpasang.
        # Geofence nyata sejak ATT-GPS-1 (`GeofenceCheck`).
        self.assertEqual(
            sorted(policy.unconfigured_required()),
            sorted([checks.FACE, checks.LIVENESS]),
        )

    def test_not_configured_check_never_answers_pass(self):
        outcome = checks.NotConfiguredCheck().run(evidence=None)

        self.assertEqual(outcome.result, "not_configured")

    def test_override_restores_the_registry(self):
        with passing_engines():
            self.assertTrue(checks.get_check(checks.FACE).configured)

        self.assertFalse(checks.get_check(checks.FACE).configured)

    @ENABLED
    def test_exploding_engine_is_rejected_not_500(self):
        employee, user = self.make_punch_employee()

        with passing_engines(face=ExplodingCheck()):
            result = self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55))

        self.assertEqual(result.decision, PunchDecision.REJECTED)
        self.assertEqual(result.verification.reason_code, PunchReason.VALIDATOR_ERROR)
        self.assertEqual(result.verification.face_result, "error")
        self.assertIsNone(row_of(employee, WEDNESDAY))

    @ENABLED
    def test_engine_answering_outside_its_vocabulary_is_not_trusted(self):
        employee, user = self.make_punch_employee()

        # "pass" bukan hasil geofence; INSIDE yang benar.
        with passing_engines(geofence=FixedCheck("pass")):
            result = self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55))

        self.assertEqual(result.decision, PunchDecision.REJECTED)
        self.assertEqual(result.verification.geofence_result, "error")
        self.assertIsNone(row_of(employee, WEDNESDAY))

    @ENABLED
    def test_attendance_not_applicable_writes_nothing(self):
        employee, user = self.make_punch_employee(group=self.no_attendance_group)

        with passing_engines(), self.assertRaises(AttendanceNotApplicable):
            self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55))

        self.assertFalse(logs_of(employee).exists())

    @ENABLED
    def test_employee_without_organization_writes_nothing(self):
        employee, user = self.make_punch_employee()

        OrganizationAssignment.objects.filter(employee=employee).update(
            is_active=False,
        )

        with passing_engines(), self.assertRaises(AttendanceNoOrganization):
            self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55))

        self.assertFalse(logs_of(employee).exists())


# ======================================================================
# 2. Mesin status IN/OUT & bukti
# ======================================================================


class StateMachineTests(SelfPunchTestCase):
    punch_enabled = True

    def test_check_in_is_accepted_and_reaches_the_canonical_row(self):
        employee, user = self.make_punch_employee()

        with passing_engines():
            result = self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55))

        self.assertEqual(result.decision, PunchDecision.ACCEPTED)
        self.assertEqual(result.verification.reason_code, "")

        log = result.log
        log.refresh_from_db()

        row = row_of(employee, WEDNESDAY)

        self.assertEqual(log.attendance_id, row.pk)
        self.assertEqual(log.source, AttendanceSource.MOBILE)
        self.assertEqual(log.log_type, "in")
        self.assertTrue(log.is_processed)
        self.assertEqual(log.company_id, self.company.pk)
        self.assertTrue(log.external_id.startswith("self-punch:"))

        self.assertEqual(row.source, AttendanceSource.MOBILE)
        self.assertEqual(row.check_in, wib(WEDNESDAY, 9, 55))
        self.assertIsNone(row.check_out)
        self.assertEqual(row.status, AttendanceStatus.PRESENT)
        self.assertEqual(row.check_in_latitude, Decimal("-6.2000000"))
        self.assertTrue(row.is_geofence_valid)

        verification = result.verification
        self.assertEqual(verification.location_result, "pass")
        self.assertEqual(verification.gps_accuracy_meters, Decimal("12.50"))
        self.assertEqual(verification.geofence_result, "inside")
        self.assertEqual(verification.face_result, "pass")
        self.assertEqual(verification.liveness_result, "pass")
        self.assertEqual(verification.work_date, WEDNESDAY)
        self.assertEqual(
            verification.policy_snapshot["requirements"][checks.FACE],
            PunchCheckRequirement.REQUIRED,
        )

    def test_duplicate_check_in_is_rejected_and_preserved(self):
        employee, user = self.make_punch_employee()

        with passing_engines():
            self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55))
            second = self.punch(employee, user, "in", wib(WEDNESDAY, 11, 0))

        self.assertEqual(second.decision, PunchDecision.REJECTED)
        self.assertEqual(second.verification.reason_code, PunchReason.DUPLICATE_CHECK_IN)
        self.assertIsNone(second.attendance)

        second.log.refresh_from_db()
        self.assertIsNone(second.log.attendance_id)
        self.assertEqual(second.log.processing_error, PunchReason.DUPLICATE_CHECK_IN)

        # Pemeriksaan tidak dijalankan untuk tap yang sudah tidak sah.
        self.assertEqual(second.verification.face_result, "not_run")

        self.assertEqual(row_of(employee, WEDNESDAY).check_in, wib(WEDNESDAY, 9, 55))
        self.assertEqual(logs_of(employee).count(), 2)

    def test_check_out_after_check_in_is_accepted(self):
        employee, user = self.make_punch_employee()

        with passing_engines():
            self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55))
            out = self.punch(employee, user, "out", wib(WEDNESDAY, 18, 5))

        self.assertEqual(out.decision, PunchDecision.ACCEPTED)

        row = row_of(employee, WEDNESDAY)

        self.assertEqual(row.check_in, wib(WEDNESDAY, 9, 55))
        self.assertEqual(row.check_out, wib(WEDNESDAY, 18, 5))
        self.assertEqual(row.check_out_latitude, Decimal("-6.2000000"))
        self.assertGreater(row.worked_minutes, 0)
        self.assertEqual(out.log.attendance_id, row.pk)

    def test_check_out_without_check_in_is_rejected_and_creates_no_row(self):
        employee, user = self.make_punch_employee()

        with passing_engines():
            result = self.punch(employee, user, "out", wib(WEDNESDAY, 18, 5))

        self.assertEqual(result.decision, PunchDecision.REJECTED)
        self.assertEqual(
            result.verification.reason_code,
            PunchReason.CHECK_OUT_WITHOUT_CHECK_IN,
        )
        self.assertIsNone(row_of(employee, WEDNESDAY))
        self.assertEqual(logs_of(employee).count(), 1)

    def test_duplicate_check_out_is_rejected(self):
        employee, user = self.make_punch_employee()

        with passing_engines():
            self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55))
            self.punch(employee, user, "out", wib(WEDNESDAY, 18, 5))
            again = self.punch(employee, user, "out", wib(WEDNESDAY, 19, 0))

        self.assertEqual(again.verification.reason_code, PunchReason.DUPLICATE_CHECK_OUT)
        self.assertEqual(row_of(employee, WEDNESDAY).check_out, wib(WEDNESDAY, 18, 5))

    def test_device_tap_counts_as_check_in(self):
        """Mesin status membaca baris kanonik, apa pun sumber tap-nya."""
        employee, user = self.make_punch_employee()

        AttendanceImportWriter.upsert(
            employee=employee,
            normalized={"log_time": wib(WEDNESDAY, 9, 50)},
            work_date=WEDNESDAY,
        )

        with passing_engines():
            result = self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55))

        self.assertEqual(result.verification.reason_code, PunchReason.DUPLICATE_CHECK_IN)

    @override_settings(ATTENDANCE_SELF_PUNCH_MIN_INTERVAL_SECONDS=60)
    def test_debounce_blocks_an_accidental_quick_second_punch(self):
        employee, user = self.make_punch_employee()

        with passing_engines():
            self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55, 0))
            quick = self.punch(employee, user, "out", wib(WEDNESDAY, 9, 55, 30))
            later = self.punch(employee, user, "out", wib(WEDNESDAY, 9, 57, 0))

        self.assertEqual(quick.verification.reason_code, PunchReason.PUNCH_TOO_SOON)
        self.assertEqual(later.decision, PunchDecision.ACCEPTED)

    @override_settings(ATTENDANCE_SELF_PUNCH_MIN_INTERVAL_SECONDS=60)
    def test_debounce_does_not_block_retry_after_a_rejected_punch(self):
        employee, user = self.make_punch_employee()

        with passing_engines():
            bad = self.punch(
                employee,
                user,
                "in",
                wib(WEDNESDAY, 9, 55, 0),
                accuracy="900",
            )
            good = self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55, 10))

        self.assertEqual(bad.verification.reason_code, PunchReason.LOCATION_LOW_ACCURACY)
        self.assertEqual(good.decision, PunchDecision.ACCEPTED)


# ======================================================================
# 3. Pemeriksaan
# ======================================================================


class CheckTests(SelfPunchTestCase):
    punch_enabled = True

    def test_low_accuracy_rejects_and_skips_the_rest(self):
        employee, user = self.make_punch_employee()

        with passing_engines():
            result = self.punch(
                employee,
                user,
                "in",
                wib(WEDNESDAY, 9, 55),
                accuracy="250",
            )

        verification = result.verification

        self.assertEqual(verification.decision, PunchDecision.REJECTED)
        self.assertEqual(verification.reason_code, PunchReason.LOCATION_LOW_ACCURACY)
        self.assertEqual(verification.location_result, "low_accuracy")
        self.assertEqual(verification.gps_accuracy_meters, Decimal("250.00"))
        self.assertEqual(verification.geofence_result, "not_run")
        self.assertEqual(verification.face_result, "not_run")
        self.assertIsNone(row_of(employee, WEDNESDAY))

    def test_missing_coordinates_reject(self):
        employee, user = self.make_punch_employee()

        with passing_engines():
            result = self.punch(
                employee,
                user,
                "in",
                wib(WEDNESDAY, 9, 55),
                latitude=None,
                longitude=None,
            )

        self.assertEqual(result.verification.reason_code, PunchReason.LOCATION_UNAVAILABLE)

    def test_missing_selfie_cannot_pass_biometric_checks(self):
        employee, user = self.make_punch_employee()

        with passing_engines():
            result = self.punch(
                employee,
                user,
                "in",
                wib(WEDNESDAY, 9, 55),
                photo=None,
            )

        self.assertEqual(result.decision, PunchDecision.REJECTED)
        self.assertEqual(result.verification.reason_code, PunchReason.LIVENESS_NOT_VERIFIED)
        self.assertEqual(result.verification.liveness_result, "not_run")
        self.assertIsNone(row_of(employee, WEDNESDAY))

    def test_outside_geofence_rejects(self):
        employee, user = self.make_punch_employee()

        with passing_engines(geofence=FixedCheck(
            "outside",
            distance_meters=Decimal("850.00"),
            radius_meters=Decimal("200.00"),
        )):
            result = self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55))

        verification = result.verification

        self.assertEqual(verification.reason_code, PunchReason.OUTSIDE_GEOFENCE)
        self.assertEqual(verification.distance_from_geofence_meters, Decimal("850.00"))
        self.assertEqual(verification.geofence_radius_meters, Decimal("200.00"))

    def test_face_mismatch_stays_failed_forever(self):
        employee, user = self.make_punch_employee()

        with passing_engines(face=FixedCheck(
            "fail",
            score=Decimal("0.412000"),
            threshold=Decimal("0.600000"),
        )):
            result = self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55))

        verification = result.verification

        self.assertEqual(verification.reason_code, PunchReason.FACE_MISMATCH)
        self.assertEqual(verification.face_score, Decimal("0.412000"))
        self.assertEqual(verification.face_provider, "test-double")
        self.assertIsNone(row_of(employee, WEDNESDAY))

        # Bukti yang sudah diputuskan tidak bisa "diluluskan".
        stored = AttendanceLogVerification.objects.get(pk=verification.pk)
        stored.face_result = "pass"

        with self.assertRaises(DjangoValidationError):
            stored.save()

        stored = AttendanceLogVerification.objects.get(pk=verification.pk)
        stored.decision = PunchDecision.ACCEPTED

        with self.assertRaises(DjangoValidationError):
            stored.save()

        self.assertEqual(
            AttendanceLogVerification.objects.get(pk=verification.pk).face_result,
            "fail",
        )

    def test_rejected_face_mismatch_cannot_become_accepted_pass(self):
        """Mutasi gabungan yang persis dilarang: accepted + pass sekaligus."""
        employee, user = self.make_punch_employee()

        with passing_engines(face=FixedCheck("fail")):
            result = self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55))

        pk = result.verification.pk

        stored = AttendanceLogVerification.objects.get(pk=pk)
        self.assertEqual(stored.decision, PunchDecision.REJECTED)
        self.assertEqual(stored.reason_code, PunchReason.FACE_MISMATCH)

        stored.decision = PunchDecision.ACCEPTED
        stored.face_result = "pass"
        stored.reason_code = ""

        with self.assertRaises(DjangoValidationError):
            stored.save()

        fresh = AttendanceLogVerification.objects.get(pk=pk)
        self.assertEqual(
            (fresh.decision, fresh.face_result, fresh.reason_code),
            (PunchDecision.REJECTED, "fail", PunchReason.FACE_MISMATCH),
        )

    def test_accepted_verification_is_equally_frozen(self):
        employee, user = self.make_punch_employee()

        with passing_engines():
            result = self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55))

        pk = result.verification.pk

        for field, value in (
            ("decision", PunchDecision.REJECTED),
            ("face_result", "fail"),
            ("liveness_result", "fail"),
            ("geofence_result", "outside"),
            ("reason_code", PunchReason.FACE_MISMATCH),
            ("work_date", SATURDAY),
        ):
            with self.subTest(field=field):
                stored = AttendanceLogVerification.objects.get(pk=pk)
                setattr(stored, field, value)

                with self.assertRaises(DjangoValidationError):
                    stored.save()

        fresh = AttendanceLogVerification.objects.get(pk=pk)
        self.assertEqual(fresh.decision, PunchDecision.ACCEPTED)
        self.assertEqual(fresh.face_result, "pass")


# ======================================================================
# 4. Idempotensi & konkurensi
# ======================================================================


class IdempotencyTests(SelfPunchTestCase):
    punch_enabled = True

    def test_retry_returns_the_stored_result_without_writing(self):
        employee, user = self.make_punch_employee()

        req = self.request("in", user=user)

        with passing_engines():
            first = self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55), req=req)

            row = row_of(employee, WEDNESDAY)
            stamp = row.updated_at

            retry = self.punch(employee, user, "in", wib(WEDNESDAY, 9, 58), req=req)

        self.assertTrue(retry.replayed)
        self.assertEqual(retry.log.pk, first.log.pk)
        self.assertEqual(retry.verification.pk, first.verification.pk)
        self.assertEqual(retry.decision, PunchDecision.ACCEPTED)

        self.assertEqual(logs_of(employee).count(), 1)
        self.assertEqual(
            AttendanceLogVerification.objects.filter(log__employee=employee).count(),
            1,
        )

        row.refresh_from_db()
        self.assertEqual(row.updated_at, stamp)
        self.assertEqual(row.check_in, wib(WEDNESDAY, 9, 55))

    def test_retry_of_a_rejected_punch_stays_rejected(self):
        employee, user = self.make_punch_employee()

        req = self.request("out", user=user)

        with passing_engines():
            first = self.punch(employee, user, "out", wib(WEDNESDAY, 18, 0), req=req)
            retry = self.punch(employee, user, "out", wib(WEDNESDAY, 18, 1), req=req)

        self.assertEqual(first.decision, PunchDecision.REJECTED)
        self.assertTrue(retry.replayed)
        self.assertEqual(retry.verification.reason_code, first.verification.reason_code)
        self.assertEqual(logs_of(employee).count(), 1)

    def test_same_id_for_a_different_punch_is_a_conflict(self):
        employee, user = self.make_punch_employee()

        req = self.request("in", user=user)

        with passing_engines():
            self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55), req=req)

            with self.assertRaises(AttendancePunchIdConflict):
                self.punch(
                    employee,
                    user,
                    "out",
                    wib(WEDNESDAY, 18, 0),
                    req=self.request(
                        "out",
                        punch_id=req.client_punch_id,
                        photo=req.photo,
                    ),
                )

        self.assertEqual(logs_of(employee).count(), 1)

    def test_another_employees_id_cannot_be_replayed(self):
        victim, victim_user = self.make_punch_employee()
        attacker, attacker_user = self.make_punch_employee()

        req = self.request("in", user=victim_user)

        with passing_engines():
            self.punch(victim, victim_user, "in", wib(WEDNESDAY, 9, 55), req=req)

            with self.assertRaises(AttendancePunchIdConflict):
                self.punch(
                    attacker,
                    attacker_user,
                    "in",
                    wib(WEDNESDAY, 9, 56),
                    req=self.request(
                        "in",
                        punch_id=req.client_punch_id,
                        user=attacker_user,
                    ),
                )

        self.assertFalse(logs_of(attacker).exists())
        self.assertIsNone(row_of(attacker, WEDNESDAY))

    def test_concurrent_id_collision_is_caught_by_the_database(self):
        """
        Dua pegawai berbeda tidak saling menunggu kunci, jadi pemeriksaan
        aplikasi bisa sama-sama melihat "belum ada". Unique
        `(source, external_id)` yang menangkapnya — dibuktikan dengan
        membutakan pemeriksaan aplikasinya.
        """
        first, first_user = self.make_punch_employee()
        second, second_user = self.make_punch_employee()

        punch_id = uuid4()

        with passing_engines():
            self.punch(
                first,
                first_user,
                "in",
                wib(WEDNESDAY, 9, 55),
                req=self.request("in", punch_id=punch_id, user=first_user),
            )

            with mock.patch.object(
                AttendancePunchService,
                "_existing",
                return_value=None,
            ), self.assertRaises(AttendancePunchIdConflict):
                self.punch(
                    second,
                    second_user,
                    "in",
                    wib(WEDNESDAY, 9, 55),
                    req=self.request("in", punch_id=punch_id, user=second_user),
                )

        self.assertFalse(logs_of(second).exists())
        self.assertIsNone(row_of(second, WEDNESDAY))

    def test_employee_row_is_locked_before_state_is_read(self):
        employee, user = self.make_punch_employee()

        with passing_engines(), CaptureQueriesContext(connection) as ctx:
            self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55))

        statements = [q["sql"] for q in ctx.captured_queries]

        lock_index = next(
            i for i, sql in enumerate(statements)
            if "FOR UPDATE" in sql and '"hr_employee"' in sql
        )

        state_index = next(
            i for i, sql in enumerate(statements)
            if '"hr_employee_attendance"' in sql and "FOR UPDATE" in sql
        )

        idempotency_index = next(
            i for i, sql in enumerate(statements)
            if '"hr_attendance_log"' in sql and "self-punch:" in sql
        )

        self.assertLess(lock_index, idempotency_index)
        self.assertLess(lock_index, state_index)


# ======================================================================
# 5. Hari kerja
# ======================================================================


class WorkDateTests(SelfPunchTestCase):
    punch_enabled = True

    def test_daytime_shift(self):
        employee, user = self.make_punch_employee()

        with passing_engines():
            self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55))

        row = row_of(employee, WEDNESDAY)

        self.assertEqual(row.scheduled_check_in, wib(WEDNESDAY, 10, 0))
        self.assertEqual(row.scheduled_check_out, wib(WEDNESDAY, 18, 0))

    def test_post_midnight_check_out_belongs_to_the_previous_work_date(self):
        employee, user = self.make_punch_employee(shift=self.late_night_shift)

        with passing_engines():
            check_in = self.punch(employee, user, "in", wib(WEDNESDAY, 19, 50))
            check_out = self.punch(employee, user, "out", wib(THURSDAY, 2, 0))

        self.assertEqual(check_in.verification.work_date, WEDNESDAY)
        self.assertEqual(check_out.verification.work_date, WEDNESDAY)
        self.assertEqual(check_out.decision, PunchDecision.ACCEPTED)

        rows = EmployeeAttendance.objects.filter(employee=employee, is_deleted=False)

        self.assertEqual(rows.count(), 1)

        row = rows.get()

        self.assertEqual(row.work_date, WEDNESDAY)
        self.assertEqual(row.check_in, wib(WEDNESDAY, 19, 50))
        self.assertEqual(row.check_out, wib(THURSDAY, 2, 0))
        self.assertEqual(row.scheduled_check_out, wib(THURSDAY, 5, 0))
        self.assertEqual(row.early_leave_minutes, 180)

    def test_unscheduled_day_is_accepted_as_off_worked(self):
        employee, user = self.make_punch_employee()

        with passing_engines():
            result = self.punch(employee, user, "in", wib(SATURDAY, 9, 0))

        self.assertEqual(result.decision, PunchDecision.ACCEPTED)

        row = row_of(employee, SATURDAY)

        self.assertIsNotNone(row)
        self.assertIsNone(row.scheduled_check_in)
        self.assertEqual(row.late_minutes, 0)


# ======================================================================
# 6. Keadaan hari yang sudah ada
# ======================================================================


class ConflictTests(SelfPunchTestCase):
    punch_enabled = True

    def make_row(self, employee, day, status, **extra):
        return EmployeeAttendance.objects.create(
            employee=employee,
            company=self.company,
            location=self.site,
            work_date=day,
            status=status,
            source=AttendanceSource.SYSTEM,
            **extra,
        )

    def test_absent_day_needs_review_and_is_not_touched(self):
        employee, user = self.make_punch_employee()

        row = self.make_row(
            employee,
            WEDNESDAY,
            AttendanceStatus.ABSENT,
            external_id="CLOSE-X-20260701",
        )

        with passing_engines():
            result = self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55))

        self.assertEqual(result.decision, PunchDecision.REVIEW_REQUIRED)
        self.assertEqual(result.verification.reason_code, PunchReason.DAY_CLOSED_ABSENT)
        self.assertIsNone(result.attendance)

        # Pemeriksaannya tetap dijalankan — yang ditinjau HR tap yang lolos.
        self.assertEqual(result.verification.face_result, "pass")

        row.refresh_from_db()

        self.assertEqual(row.status, AttendanceStatus.ABSENT)
        self.assertIsNone(row.check_in)

        result.log.refresh_from_db()
        self.assertIsNone(result.log.attendance_id)

    def test_leave_row_needs_review(self):
        employee, user = self.make_punch_employee()

        row = self.make_row(employee, WEDNESDAY, AttendanceStatus.LEAVE)

        with passing_engines():
            result = self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55))

        self.assertEqual(result.verification.reason_code, PunchReason.ON_LEAVE)

        row.refresh_from_db()
        self.assertEqual(row.status, AttendanceStatus.LEAVE)
        self.assertIsNone(row.check_in)

    def test_approved_leave_without_a_row_needs_review(self):
        employee, user = self.make_punch_employee()

        self.make_leave(employee, WEDNESDAY)

        with passing_engines():
            result = self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55))

        self.assertEqual(result.decision, PunchDecision.REVIEW_REQUIRED)
        self.assertEqual(result.verification.reason_code, PunchReason.ON_LEAVE)
        self.assertIsNone(row_of(employee, WEDNESDAY))

    def test_failed_check_on_a_conflict_day_is_rejected_not_reviewed(self):
        employee, user = self.make_punch_employee()

        self.make_row(employee, WEDNESDAY, AttendanceStatus.ABSENT)

        with passing_engines(face=FixedCheck("fail")):
            result = self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55))

        self.assertEqual(result.decision, PunchDecision.REJECTED)
        self.assertEqual(result.verification.reason_code, PunchReason.FACE_MISMATCH)

    def test_permit_row_is_not_rejected(self):
        employee, user = self.make_punch_employee()

        self.make_row(employee, WEDNESDAY, AttendanceStatus.PERMIT)

        with passing_engines():
            result = self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55))

        self.assertEqual(result.decision, PunchDecision.ACCEPTED)

        row = row_of(employee, WEDNESDAY)

        # Sama dengan tap mesin: status yang bukan hasil tap tidak dihitung ulang.
        self.assertEqual(row.status, AttendanceStatus.PERMIT)
        self.assertEqual(row.check_in, wib(WEDNESDAY, 9, 55))

    def test_business_trip_day_keeps_existing_semantics(self):
        employee, user = self.make_punch_employee()

        self.make_row(
            employee,
            WEDNESDAY,
            AttendanceStatus.BUSINESS_TRIP,
            scheduled_check_in=wib(WEDNESDAY, 10, 0),
            scheduled_check_out=wib(WEDNESDAY, 18, 0),
        )

        with passing_engines():
            result = self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55))

        self.assertEqual(result.decision, PunchDecision.ACCEPTED)

        row = row_of(employee, WEDNESDAY)

        # Tap fisik di hari dinas = hari hadir (perilaku mesin yang sudah
        # ada, dan yang dibaca Payroll), sumber barisnya tetap SYSTEM, dan
        # IN tidak ikut mengisi jam pulang.
        self.assertEqual(row.status, AttendanceStatus.PRESENT)
        self.assertEqual(row.source, AttendanceSource.SYSTEM)
        self.assertEqual(row.check_in, wib(WEDNESDAY, 9, 55))
        self.assertIsNone(row.check_out)

    def test_locked_payroll_period_needs_review(self):
        from apps.payroll.models import PayrollGroup, PayrollPeriod
        from apps.payroll.models.choices import PayrollPeriodStatus

        employee, user = self.make_punch_employee()

        group = PayrollGroup.objects.create(code="AIM-PUNCH-GRP", name="Bulanan")

        PayrollPeriod.objects.create(
            company=self.company,
            payroll_group=group,
            code="AIM-PUNCH-202607",
            name="Juli 2026",
            start_date=WEDNESDAY.replace(day=1),
            end_date=WEDNESDAY.replace(day=31),
            status=PayrollPeriodStatus.FINALIZED,
        )

        with passing_engines():
            result = self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55))

        self.assertEqual(result.decision, PunchDecision.REVIEW_REQUIRED)
        self.assertEqual(result.verification.reason_code, PunchReason.PAYROLL_PERIOD_LOCKED)
        self.assertIsNone(row_of(employee, WEDNESDAY))


# ======================================================================
# 7. Izin
# ======================================================================


class PermissionEffectTests(SelfPunchTestCase):
    punch_enabled = True

    def test_permission_approved_before_the_first_punch_is_applied(self):
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
            self.punch(employee, user, "in", wib(WEDNESDAY, 11, 0))

        row = row_of(employee, WEDNESDAY)

        self.assertEqual(row.status, AttendanceStatus.LATE)
        self.assertEqual(row.late_minutes, 60)
        self.assertEqual(row.excused_late_minutes, 60)
        self.assertEqual(row.permission_state, "excused")

    def test_unexcused_late_is_still_classified(self):
        employee, user = self.make_punch_employee()

        with passing_engines():
            self.punch(employee, user, "in", wib(WEDNESDAY, 11, 0))

        row = row_of(employee, WEDNESDAY)

        self.assertEqual(row.late_minutes, 60)
        self.assertEqual(row.excused_late_minutes, 0)
        self.assertEqual(row.permission_state, "unauthorized")


# ======================================================================
# 8. Writer — perilaku lama tidak bergeser
# ======================================================================


class WriterRegressionTests(SelfPunchTestCase):
    def test_default_source_and_raw_tap_behaviour_unchanged(self):
        employee = self.make_employee(shift=self.office_shift)

        row, created = AttendanceImportWriter.upsert(
            employee=employee,
            normalized={"log_time": wib(WEDNESDAY, 9, 50)},
            work_date=WEDNESDAY,
        )

        self.assertTrue(created)
        self.assertEqual(row.source, AttendanceSource.IMPORT)
        self.assertEqual(row.check_in, wib(WEDNESDAY, 9, 50))
        self.assertEqual(row.first_check_in, wib(WEDNESDAY, 9, 50))
        self.assertEqual(row.last_check_out, wib(WEDNESDAY, 9, 50))
        self.assertIsNone(row.check_out)

        AttendanceImportWriter.upsert(
            employee=employee,
            normalized={"log_time": wib(WEDNESDAY, 18, 10)},
            work_date=WEDNESDAY,
        )

        row.refresh_from_db()

        self.assertEqual(row.check_out, wib(WEDNESDAY, 18, 10))

    def test_raw_tap_on_a_tapless_row_still_moves_both_sides(self):
        employee = self.make_employee(shift=self.office_shift)

        EmployeeAttendance.objects.create(
            employee=employee,
            company=self.company,
            work_date=WEDNESDAY,
            status=AttendanceStatus.BUSINESS_TRIP,
            source=AttendanceSource.SYSTEM,
        )

        row, _ = AttendanceImportWriter.upsert(
            employee=employee,
            normalized={"log_time": wib(WEDNESDAY, 9, 50)},
            work_date=WEDNESDAY,
        )

        self.assertEqual(row.check_in, wib(WEDNESDAY, 9, 50))
        self.assertEqual(row.check_out, wib(WEDNESDAY, 9, 50))

    def test_typed_check_in_only_moves_its_own_side(self):
        employee = self.make_employee(shift=self.office_shift)

        EmployeeAttendance.objects.create(
            employee=employee,
            company=self.company,
            work_date=WEDNESDAY,
            status=AttendanceStatus.BUSINESS_TRIP,
            source=AttendanceSource.SYSTEM,
        )

        row, _ = AttendanceImportWriter.upsert(
            employee=employee,
            normalized={"log_time": wib(WEDNESDAY, 9, 50)},
            work_date=WEDNESDAY,
            source=AttendanceSource.MOBILE,
            log_type="in",
        )

        self.assertEqual(row.check_in, wib(WEDNESDAY, 9, 50))
        self.assertIsNone(row.check_out)
        self.assertIsNone(row.last_check_out)
        # Sumber hanya menandai baris baru.
        self.assertEqual(row.source, AttendanceSource.SYSTEM)

    def test_mobile_source_marks_a_new_row(self):
        employee = self.make_employee(shift=self.office_shift)

        row, created = AttendanceImportWriter.upsert(
            employee=employee,
            normalized={"log_time": wib(WEDNESDAY, 9, 50)},
            work_date=WEDNESDAY,
            source=AttendanceSource.MOBILE,
            log_type="in",
        )

        self.assertTrue(created)
        self.assertEqual(row.source, AttendanceSource.MOBILE)
        self.assertIsNone(row.last_check_out)


# ======================================================================
# 9. Payroll & berkas
# ======================================================================


class PayrollIsolationTests(SelfPunchTestCase):
    punch_enabled = True

    def facts(self, employee):
        from apps.payroll.services.sources import PayrollSourceService

        return PayrollSourceService.collect(
            employee=employee,
            start_date=WEDNESDAY.replace(day=1),
            end_date=WEDNESDAY.replace(day=31),
        )

    def test_rejected_punch_cannot_reach_payroll_facts(self):
        employee, user = self.make_punch_employee()

        before = self.facts(employee)

        with passing_engines(face=FixedCheck("fail")):
            self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55))

        after = self.facts(employee)

        self.assertEqual(after.attendance_days, before.attendance_days)
        self.assertEqual(after.attendance_days, 0)

    def test_accepted_punch_reaches_payroll_through_employee_attendance(self):
        employee, user = self.make_punch_employee()

        with passing_engines():
            self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55))

        self.assertEqual(self.facts(employee).attendance_days, 1)

    def test_payroll_source_has_no_evidence_dependency(self):
        root = Path(settings.BASE_DIR) / "apps" / "payroll"

        offenders = []

        for path in root.rglob("*.py"):
            if "migrations" in path.parts or "tests" in path.parts:
                continue

            text = path.read_text(encoding="utf-8")

            for needle in (
                "AttendanceLogVerification",
                "AttendanceLog",
                "attendance.punch",
                "punch_checks",
            ):
                if needle in text:
                    offenders.append(f"{path.relative_to(root)}: {needle}")

        self.assertEqual(offenders, [])


class EvidenceFileTests(SelfPunchTestCase):
    punch_enabled = True

    def test_someone_elses_upload_cannot_be_used_as_selfie(self):
        employee, user = self.make_punch_employee()
        _other, other_user = self.make_punch_employee()

        foreign = self.make_selfie(other_user)

        with passing_engines(), self.assertRaises(ValidationError):
            self.punch(
                employee,
                user,
                "in",
                wib(WEDNESDAY, 9, 55),
                photo=foreign,
            )

        self.assertFalse(logs_of(employee).exists())

    def test_selfie_must_be_uploaded_as_attendance_selfie(self):
        employee, user = self.make_punch_employee()

        general = self.make_selfie(user, category=UploadedFile.Category.GENERAL)

        with passing_engines(), self.assertRaises(ValidationError):
            self.punch(
                employee,
                user,
                "in",
                wib(WEDNESDAY, 9, 55),
                photo=general,
            )

        self.assertFalse(logs_of(employee).exists())

    def test_a_selfie_cannot_be_reused_for_a_second_punch(self):
        employee, user = self.make_punch_employee()

        selfie = self.make_selfie(user)

        with passing_engines():
            self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55), photo=selfie)

            with self.assertRaises(ValidationError):
                self.punch(
                    employee,
                    user,
                    "out",
                    wib(WEDNESDAY, 18, 5),
                    photo=selfie,
                )

    def test_attached_selfie_is_closed_to_ordinary_readers(self):
        employee, user = self.make_punch_employee()
        _other, other_user = self.make_punch_employee()
        root = self.make_user(superuser=True)

        selfie = self.make_selfie(user)

        self.assertTrue(FileAccessService.can_read(user, selfie))

        with passing_engines():
            self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55), photo=selfie)

        # `AttendanceLog` tidak punya viewset → induk tanpa aturan baca →
        # ditutup. Pengunggahnya pun kehilangan akses begitu tertaut.
        self.assertFalse(FileAccessService.can_read(other_user, selfie))
        self.assertFalse(FileAccessService.can_download(other_user, selfie))
        self.assertFalse(FileAccessService.can_read(user, selfie))
        self.assertFalse(FileAccessService.can_write(user, selfie))
        self.assertTrue(FileAccessService.can_read(root, selfie))


# ======================================================================
# 10. Kekebalan bukti final (ATT-BIO-1B)
# ======================================================================


class VerificationImmutabilityTests(SelfPunchTestCase):
    """
    Kekebalan **tingkat aplikasi**: `save()`, `QuerySet.update()`,
    `bulk_update()`, dan `delete()` menolak bukti final. SQL mentah dan
    `_base_manager` tidak diuji karena memang tidak dijaga.
    """

    punch_enabled = True

    # Nilai pengganti per kolom — semuanya berbeda dari nilai tersimpan.
    @staticmethod
    def rewrites(other_log):
        from datetime import datetime, timezone as dt_tz

        return {
            "log": other_log,
            # Berbeda dari REJECTED maupun ACCEPTED yang tersimpan.
            "decision": PunchDecision.REVIEW_REQUIRED,
            "reason_code": PunchReason.LOCATION_UNAVAILABLE,
            "reason_detail": "ditulis ulang",
            "work_date": SATURDAY,
            "face_result": "error",
            "face_score": Decimal("0.999999"),
            "face_threshold": Decimal("0.100000"),
            "face_provider": "rewritten",
            "face_model_version": "v-rewritten",
            "liveness_result": "error",
            "liveness_score": Decimal("0.111111"),
            "liveness_threshold": Decimal("0.222222"),
            "liveness_provider": "rewritten",
            "liveness_model_version": "v-rewritten",
            "location_result": "error",
            "gps_accuracy_meters": Decimal("1.00"),
            "geofence_result": "error",
            "distance_from_geofence_meters": Decimal("1.00"),
            "geofence_radius_meters": Decimal("9999.00"),
            "policy_snapshot": {"rewritten": True},
            "validated_at": datetime(2030, 1, 1, tzinfo=dt_tz.utc),
        }

    def finalized(self, decision):
        employee, user = self.make_punch_employee()

        if decision == PunchDecision.REJECTED:
            engines = passing_engines(face=FixedCheck(
                "fail",
                score=Decimal("0.412000"),
                threshold=Decimal("0.600000"),
                model_version="m-1",
            ))
        else:
            engines = passing_engines()

        with engines:
            result = self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55))

        self.assertEqual(result.decision, decision)

        # Log lain sebagai sasaran pemindahan `log`.
        with passing_engines():
            other = self.punch(employee, user, "out", wib(WEDNESDAY, 18, 5))

        return result.verification.pk, other.log

    def snapshot(self, pk):
        from apps.hr.models.attendance.verification import FROZEN_FIELDS

        row = AttendanceLogVerification.objects.get(pk=pk)

        return {
            name: getattr(row, row._meta.get_field(name).attname)
            for name in FROZEN_FIELDS
        }

    def assert_every_field_frozen(self, decision):
        pk, other_log = self.finalized(decision)
        before = self.snapshot(pk)

        for field, value in self.rewrites(other_log).items():
            with self.subTest(path="save", field=field):
                row = AttendanceLogVerification.objects.get(pk=pk)
                setattr(row, field, value)

                with self.assertRaises(DjangoValidationError):
                    row.save()

            with self.subTest(path="queryset.update", field=field):
                with self.assertRaises(DjangoValidationError):
                    AttendanceLogVerification.objects.filter(pk=pk).update(
                        **{field: value},
                    )

            with self.subTest(path="bulk_update", field=field):
                row = AttendanceLogVerification.objects.get(pk=pk)
                setattr(row, field, value)

                with self.assertRaises(DjangoValidationError):
                    AttendanceLogVerification.objects.bulk_update([row], [field])

        self.assertEqual(self.snapshot(pk), before)

    def test_rejected_face_mismatch_is_frozen_on_every_path(self):
        self.assert_every_field_frozen(PunchDecision.REJECTED)

    def test_accepted_is_frozen_on_every_path(self):
        self.assert_every_field_frozen(PunchDecision.ACCEPTED)

    def test_rejected_cannot_be_rewritten_to_accepted_pass_by_update(self):
        pk, _ = self.finalized(PunchDecision.REJECTED)

        with self.assertRaises(DjangoValidationError):
            AttendanceLogVerification.objects.filter(pk=pk).update(
                decision=PunchDecision.ACCEPTED,
                face_result="pass",
                reason_code="",
                reason_detail="",
            )

        row = AttendanceLogVerification.objects.get(pk=pk)
        self.assertEqual(
            (row.decision, row.face_result, row.reason_code),
            (PunchDecision.REJECTED, "fail", PunchReason.FACE_MISMATCH),
        )

    def test_mixed_queryset_update_touches_nothing(self):
        """Satu baris final di dalam set → seluruh update ditolak."""
        final_pk, _ = self.finalized(PunchDecision.REJECTED)

        employee, _user = self.make_punch_employee()
        pending_log = AttendanceLog.objects.create(
            employee=employee,
            company=self.company,
            occurred_at=wib(WEDNESDAY, 9, 0),
            log_type="in",
            source=AttendanceSource.MOBILE,
            external_id=f"self-punch:{uuid4()}",
        )
        pending = AttendanceLogVerification.objects.create(log=pending_log)

        with self.assertRaises(DjangoValidationError):
            AttendanceLogVerification.objects.filter(
                pk__in=[final_pk, pending.pk],
            ).update(reason_detail="x")

        pending.refresh_from_db()
        self.assertEqual(pending.reason_detail, "")

    def test_pending_rows_can_still_be_finalized(self):
        """Alur normal tidak dilemahkan: PENDING boleh diisi dan diputuskan."""
        employee, _user = self.make_punch_employee()
        log = AttendanceLog.objects.create(
            employee=employee,
            company=self.company,
            occurred_at=wib(WEDNESDAY, 9, 0),
            log_type="in",
            source=AttendanceSource.MOBILE,
            external_id=f"self-punch:{uuid4()}",
        )
        row = AttendanceLogVerification.objects.create(log=log)

        AttendanceLogVerification.objects.filter(pk=row.pk).update(
            reason_detail="diisi saat pending",
        )

        row.refresh_from_db()
        row.decision = PunchDecision.REJECTED
        row.reason_code = PunchReason.FACE_MISMATCH
        row.save()

        row.refresh_from_db()
        self.assertEqual(row.decision, PunchDecision.REJECTED)
        self.assertEqual(row.reason_detail, "diisi saat pending")

    def test_ordinary_deletion_is_refused_and_protect_holds(self):
        from django.db.models import ProtectedError

        pk, _ = self.finalized(PunchDecision.REJECTED)
        row = AttendanceLogVerification.objects.get(pk=pk)

        with self.assertRaises(ProtectedError):
            AttendanceLog.objects.filter(pk=row.log_id).delete()

        with self.assertRaises(ProtectedError):
            AttendanceLog.objects.get(pk=row.log_id).delete()

        with self.assertRaises(DjangoValidationError):
            row.delete()

        with self.assertRaises(DjangoValidationError):
            AttendanceLogVerification.objects.filter(pk=pk).delete()

        self.assertTrue(AttendanceLogVerification.objects.filter(pk=pk).exists())
        self.assertTrue(AttendanceLog.objects.filter(pk=row.log_id).exists())

    def test_only_the_governed_purge_removes_final_evidence(self):
        pk, _ = self.finalized(PunchDecision.REJECTED)
        log_id = AttendanceLogVerification.objects.get(pk=pk).log_id

        deleted, _ = AttendanceLogVerification.objects.filter(
            pk=pk,
        ).purge_for_governed_reset()

        self.assertEqual(deleted, 1)

        # Sesudah buktinya dibuang lewat jalur yang dijaga, log-nya bisa.
        AttendanceLog.objects.filter(pk=log_id).delete()
        self.assertFalse(AttendanceLog.objects.filter(pk=log_id).exists())
