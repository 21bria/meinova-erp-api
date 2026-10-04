"""
ATT-GPS-1 — geofence sungguhan + mode uji coba GPS per tenant.

* `GeofenceCheck`: Haversine ke `AttendanceGeofence` aktif milik lokasi
  kerja pegawai (lokasi dari penempatan aktif, lewat `AttendanceLog.location`).
* Uji coba (`ATTENDANCE_SELF_PUNCH_TRIAL_SCHEMAS`): lokasi + geofence
  dievaluasi, selfie disimpan, wajah/liveness tetap belum terpasang, dan
  tap **tidak pernah** menjadi kehadiran.
"""

from __future__ import annotations

from decimal import Decimal
from unittest import mock

from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.test import override_settings

from apps.hr.api.attendance import punch_checks as checks
from apps.hr.api.attendance.punch import (
    AttendancePunchDisabled,
    AttendancePunchNotConfigured,
)
from apps.hr.api.attendance_sync.services import AttendanceSyncService
from apps.hr.models import (
    AttendanceGeofence,
    AttendanceLog,
    AttendanceLogVerification,
    AttendanceSource,
    AttendanceStatus,
    EmployeeAttendance,
    OrganizationAssignment,
)
from apps.hr.models.attendance.verification import PunchDecision, PunchReason

from .punch_base import (
    ENABLED,
    WEDNESDAY,
    FixedCheck,
    SelfPunchTestCase,
    passing_engines,
    wib,
)


# Titik pusat = koordinat bawaan `SelfPunchTestCase.request()`.
CENTER_LAT = Decimal("-6.2000000")
CENTER_LNG = Decimal("106.8166667")

# ~150 m ke utara dari pusat (1e-6 derajat lintang ≈ 0,111 m).
NORTH_150M_LAT = "-6.1986510"


def row_of(employee, day=WEDNESDAY):
    return EmployeeAttendance.objects.filter(
        employee=employee,
        work_date=day,
        is_deleted=False,
    ).first()


def trial_for(*schemas):
    return override_settings(ATTENDANCE_SELF_PUNCH_TRIAL_SCHEMAS=list(schemas))


class GeofenceTestCase(SelfPunchTestCase):
    def make_geofence(self, location=None, *, radius=100, **extra):
        return AttendanceGeofence.objects.create(
            location=location or self.site,
            latitude=extra.pop("latitude", CENTER_LAT),
            longitude=extra.pop("longitude", CENTER_LNG),
            radius_m=radius,
            **extra,
        )

    @staticmethod
    def real_geofence(**overrides):
        """Wajah/liveness pengganti lolos, geofence = mesin sungguhan."""
        return passing_engines(geofence=checks.GeofenceCheck(), **overrides)

    @property
    def schema(self) -> str:
        return connection.schema_name


# ======================================================================
# 1. Jarak
# ======================================================================


class HaversineTests(GeofenceTestCase):
    def test_known_distances(self):
        # Satu derajat bujur di khatulistiwa ≈ 111,195 km (bola R rata-rata).
        self.assertAlmostEqual(
            float(checks.haversine_m(0, 0, 0, 1)), 111_195.08, delta=0.5,
        )
        self.assertEqual(checks.haversine_m(CENTER_LAT, CENTER_LNG, CENTER_LAT, CENTER_LNG), Decimal("0.00"))

        north = checks.haversine_m(Decimal(NORTH_150M_LAT), CENTER_LNG, CENTER_LAT, CENTER_LNG)
        self.assertAlmostEqual(float(north), 150.0, delta=0.5)

        # Simetris.
        self.assertEqual(
            checks.haversine_m(CENTER_LAT, CENTER_LNG, Decimal(NORTH_150M_LAT), CENTER_LNG),
            north,
        )


# ======================================================================
# 2. Model
# ======================================================================


class GeofenceModelTests(GeofenceTestCase):
    def test_validation(self):
        for field, value in (
            ("latitude", Decimal("90.0000001")),
            ("latitude", Decimal("-91")),
            ("longitude", Decimal("180.0000001")),
            ("longitude", Decimal("-181")),
            ("radius_m", 0),
        ):
            with self.subTest(field=field, value=value):
                geofence = AttendanceGeofence(
                    location=self.site,
                    latitude=CENTER_LAT,
                    longitude=CENTER_LNG,
                    radius_m=100,
                )
                setattr(geofence, field, value)

                with self.assertRaises(ValidationError):
                    geofence.full_clean()

    def test_database_rejects_out_of_range_values(self):
        for field, value in (("latitude", Decimal("95")), ("longitude", Decimal("190")), ("radius_m", 0)):
            with self.subTest(field), self.assertRaises(IntegrityError), transaction.atomic():
                AttendanceGeofence.objects.create(
                    location=self.site,
                    **{
                        "latitude": CENTER_LAT,
                        "longitude": CENTER_LNG,
                        "radius_m": 100,
                        field: value,
                    },
                )

    def test_one_active_geofence_per_location(self):
        first = self.make_geofence()

        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make_geofence()

        # Ganti = nonaktifkan yang lama, buat yang baru.
        first.is_active = False
        first.save(update_fields=["is_active"])
        self.make_geofence(radius=250)

        self.assertEqual(
            AttendanceGeofence.objects.filter(location=self.site).count(),
            2,
        )


# ======================================================================
# 3. GeofenceCheck di jalur tap biasa (bukan uji coba)
# ======================================================================


class GeofenceCheckTests(GeofenceTestCase):
    punch_enabled = True

    def punch_at(self, employee, user, **kwargs):
        with self.real_geofence():
            return self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55), **kwargs)

    def test_production_registry_has_a_real_geofence(self):
        self.assertIsInstance(checks.get_check(checks.GEOFENCE), checks.GeofenceCheck)
        self.assertTrue(checks.get_check(checks.GEOFENCE).configured)
        # Wajah dan liveness tidak ikut berubah.
        self.assertFalse(checks.get_check(checks.FACE).configured)
        self.assertFalse(checks.get_check(checks.LIVENESS).configured)

    def test_inside_geofence_is_accepted_with_evidence(self):
        self.make_geofence(radius=100)
        employee, user = self.make_punch_employee()

        result = self.punch_at(employee, user)

        self.assertEqual(result.decision, PunchDecision.ACCEPTED)

        verification = result.verification
        self.assertEqual(verification.location_result, "pass")
        self.assertEqual(verification.geofence_result, "inside")
        self.assertEqual(verification.distance_from_geofence_meters, Decimal("0.00"))
        self.assertEqual(verification.geofence_radius_meters, Decimal("100.00"))
        self.assertEqual(verification.gps_accuracy_meters, Decimal("12.50"))

        # Koordinat kiriman tetap di bukti mentah.
        self.assertEqual(result.log.latitude, CENTER_LAT)
        self.assertEqual(result.log.longitude, CENTER_LNG)
        self.assertEqual(result.log.location_id, self.site.pk)
        self.assertIsNotNone(row_of(employee))

    def test_outside_geofence_is_rejected(self):
        self.make_geofence(radius=100)
        employee, user = self.make_punch_employee()

        result = self.punch_at(employee, user, latitude=NORTH_150M_LAT)

        self.assertEqual(result.decision, PunchDecision.REJECTED)
        self.assertEqual(result.verification.reason_code, PunchReason.OUTSIDE_GEOFENCE)
        self.assertEqual(result.verification.geofence_result, "outside")
        self.assertAlmostEqual(float(result.verification.distance_from_geofence_meters), 150.0, delta=0.5)
        self.assertEqual(result.verification.liveness_result, "not_run")
        self.assertIsNone(row_of(employee))

    def test_boundary_is_inside(self):
        self.make_geofence(radius=100)
        employee, user = self.make_punch_employee()

        for distance, expected in (("100.00", "inside"), ("100.01", "outside")):
            with self.subTest(distance), mock.patch.object(
                checks, "haversine_m", return_value=Decimal(distance),
            ):
                check = checks.GeofenceCheck()
                outcome = check.run(
                    mock.Mock(
                        log=mock.Mock(location_id=self.site.pk),
                        latitude=CENTER_LAT,
                        longitude=CENTER_LNG,
                        accuracy_meters=Decimal("5"),
                    ),
                )

                self.assertEqual(outcome.result, expected)
                self.assertEqual(outcome.radius_meters, Decimal("100"))

    def test_location_without_geofence(self):
        employee, user = self.make_punch_employee()

        result = self.punch_at(employee, user)

        self.assertEqual(result.decision, PunchDecision.REJECTED)
        self.assertEqual(result.verification.reason_code, PunchReason.GEOFENCE_NOT_CONFIGURED)
        self.assertEqual(result.verification.geofence_result, "no_geofence")

    def test_inactive_or_deleted_geofence_is_ignored(self):
        employee, user = self.make_punch_employee()
        self.make_geofence(is_active=False)

        result = self.punch_at(employee, user)
        self.assertEqual(result.verification.geofence_result, "no_geofence")

    def test_employee_without_work_location(self):
        self.make_geofence()
        employee, user = self.make_punch_employee()

        OrganizationAssignment.objects.filter(employee=employee).update(location=None)

        result = self.punch_at(employee, user)

        self.assertEqual(result.decision, PunchDecision.REJECTED)
        self.assertEqual(result.verification.reason_code, PunchReason.WORK_LOCATION_UNAVAILABLE)
        self.assertEqual(result.verification.geofence_result, "no_work_location")

    def test_geofence_comes_from_the_employees_own_location(self):
        # Geofence hanya di site A; pegawai ditempatkan di site B.
        self.make_geofence(self.site)
        employee, user = self.make_punch_employee(location=self.other_site)

        result = self.punch_at(employee, user)

        self.assertEqual(result.log.location_id, self.other_site.pk)
        self.assertEqual(result.verification.geofence_result, "no_geofence")

    def test_missing_coordinates_fail_before_geofence(self):
        self.make_geofence()
        employee, user = self.make_punch_employee()

        result = self.punch_at(employee, user, latitude=None, longitude=None)

        self.assertEqual(result.verification.reason_code, PunchReason.LOCATION_UNAVAILABLE)
        self.assertEqual(result.verification.geofence_result, "not_run")

    def test_poor_accuracy_fails_before_an_inside_result(self):
        self.make_geofence()
        employee, user = self.make_punch_employee()

        # Koordinatnya tepat di pusat, tapi akurasinya di atas batas.
        result = self.punch_at(employee, user, accuracy="150.00")

        self.assertEqual(result.verification.reason_code, PunchReason.LOCATION_LOW_ACCURACY)
        self.assertEqual(result.verification.location_result, "low_accuracy")
        self.assertEqual(result.verification.geofence_result, "not_run")
        self.assertIsNone(row_of(employee))

    def test_accuracy_limit_is_the_existing_setting(self):
        self.make_geofence()
        employee, user = self.make_punch_employee()

        with override_settings(ATTENDANCE_SELF_PUNCH_MAX_GPS_ACCURACY_METERS=200):
            result = self.punch_at(employee, user, accuracy="150.00")

        self.assertEqual(result.verification.geofence_result, "inside")


# ======================================================================
# 4. Mode uji coba
# ======================================================================


class TrialModeTests(GeofenceTestCase):
    def test_trial_is_off_by_default(self):
        employee, user = self.make_punch_employee()

        self.assertEqual(checks.trial_schemas(), frozenset())
        self.assertFalse(checks.trial_active())

        with self.assertRaises(AttendancePunchDisabled):
            self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55))

        with ENABLED, self.assertRaises(AttendancePunchNotConfigured):
            self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55))

        self.assertFalse(AttendanceLog.objects.filter(employee=employee).exists())

    def test_patterns_and_public_schema_never_enable_trial(self):
        for value in (["*"], ["public"], ["%"], [""], [" "], "*", f"{self.schema}*"):
            with self.subTest(value=value), override_settings(ATTENDANCE_SELF_PUNCH_TRIAL_SCHEMAS=value):
                self.assertFalse(checks.trial_active())

    def test_another_listed_schema_leaves_this_tenant_fail_closed(self):
        employee, user = self.make_punch_employee()

        with trial_for("some_other_tenant"):
            self.assertFalse(checks.trial_active())

            with self.assertRaises(AttendancePunchDisabled):
                self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55))

            with ENABLED, self.assertRaises(AttendancePunchNotConfigured):
                self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55))

        self.assertFalse(AttendanceLog.objects.filter(employee=employee).exists())

    def test_trial_evaluates_gps_and_stores_evidence_without_attendance(self):
        self.make_geofence(radius=100)
        employee, user = self.make_punch_employee(enrolled=False)

        with trial_for(self.schema):
            self.assertTrue(checks.trial_active())

            result = self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55))

        self.assertTrue(result.trial)
        self.assertEqual(result.decision, PunchDecision.REJECTED)

        verification = result.verification
        self.assertEqual(verification.location_result, "pass")
        self.assertEqual(verification.geofence_result, "inside")
        self.assertEqual(verification.distance_from_geofence_meters, Decimal("0.00"))
        self.assertEqual(verification.geofence_radius_meters, Decimal("100.00"))

        # Wajah/liveness tetap belum terpasang — bukan dilewati.
        self.assertEqual(verification.liveness_result, "not_configured")
        self.assertEqual(verification.face_result, "not_configured")
        self.assertEqual(verification.reason_code, PunchReason.LIVENESS_NOT_VERIFIED)
        self.assertTrue(verification.policy_snapshot["trial"])
        self.assertTrue(verification.policy_snapshot["requirements"][checks.FACE] == "required")

        # Selfie tersimpan sebagai bukti.
        self.assertIsNotNone(result.log.photo_id)
        self.assertEqual(result.log.source, AttendanceSource.MOBILE)

        # Tidak ada kehadiran.
        self.assertIsNone(result.attendance)
        self.assertIsNone(result.log.attendance_id)
        self.assertFalse(EmployeeAttendance.objects.filter(employee=employee).exists())

    def test_trial_outside_geofence(self):
        self.make_geofence(radius=100)
        employee, user = self.make_punch_employee()

        with trial_for(self.schema):
            result = self.punch(
                employee, user, "in", wib(WEDNESDAY, 9, 55), latitude=NORTH_150M_LAT,
            )

        self.assertEqual(result.verification.reason_code, PunchReason.OUTSIDE_GEOFENCE)
        self.assertEqual(result.verification.geofence_result, "outside")
        self.assertFalse(EmployeeAttendance.objects.filter(employee=employee).exists())

    def test_trial_never_becomes_attendance_even_when_every_check_passes(self):
        """
        Invarian kritis: sekalipun lokasi, geofence, liveness, dan wajah
        semuanya LOLOS, tap uji coba tidak membuat atau mengubah
        `EmployeeAttendance`.
        """
        self.make_geofence(radius=100)
        employee, user = self.make_punch_employee()

        with trial_for(self.schema), self.real_geofence() as engines:
            created = self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55))

        # Semua mesin memang dijalankan dan lolos.
        self.assertEqual(len(engines[checks.FACE].calls), 1)
        self.assertEqual(created.verification.face_result, "pass")
        self.assertEqual(created.verification.liveness_result, "pass")
        self.assertEqual(created.verification.geofence_result, "inside")

        self.assertEqual(created.decision, PunchDecision.REJECTED)
        self.assertEqual(created.verification.reason_code, PunchReason.TRIAL_NOT_RECORDED)
        self.assertIsNone(created.attendance)
        self.assertFalse(EmployeeAttendance.objects.filter(employee=employee).exists())

        # Baris yang sudah ada juga tidak diubah: OUT sah di atas IN mesin.
        existing = EmployeeAttendance.objects.create(
            employee=employee,
            company=self.company,
            work_date=WEDNESDAY,
            status=AttendanceStatus.PRESENT,
            source=AttendanceSource.DEVICE,
            check_in=wib(WEDNESDAY, 9, 50),
            first_check_in=wib(WEDNESDAY, 9, 50),
        )
        before = EmployeeAttendance.objects.filter(pk=existing.pk).values().get()

        with trial_for(self.schema), self.real_geofence():
            updated = self.punch(employee, user, "out", wib(WEDNESDAY, 18, 5))

        self.assertEqual(updated.verification.reason_code, PunchReason.TRIAL_NOT_RECORDED)
        self.assertEqual(EmployeeAttendance.objects.filter(pk=existing.pk).values().get(), before)
        self.assertEqual(EmployeeAttendance.objects.filter(employee=employee).count(), 1)

    def test_trial_cannot_skip_location_or_geofence(self):
        employee, user = self.make_punch_employee()

        # Geofence "belum terpasang" di uji coba → tetap UNAVAILABLE.
        with trial_for(self.schema), passing_engines(geofence=checks.NotConfiguredCheck()):
            with self.assertRaises(AttendancePunchNotConfigured):
                self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55))

        self.assertFalse(AttendanceLog.objects.filter(employee=employee).exists())

    def test_trial_replay_keeps_trial_semantics(self):
        self.make_geofence()
        employee, user = self.make_punch_employee()
        req = self.request("in", user=user)

        with trial_for(self.schema):
            first = self.punch(employee, user, "in", wib(WEDNESDAY, 9, 55), req=req)

        # Bahkan sesudah uji coba dimatikan, hasil yang diputar ulang tetap
        # hasil uji coba — diambil dari bukti, bukan dari settings sekarang.
        with ENABLED, passing_engines():
            retry = self.punch(employee, user, "in", wib(WEDNESDAY, 9, 57), req=req)

        self.assertTrue(retry.replayed)
        self.assertTrue(retry.trial)
        self.assertEqual(retry.log.pk, first.log.pk)
        self.assertIsNone(retry.attendance)


# ======================================================================
# 5. DEVICE tidak tersentuh
# ======================================================================


class DeviceUntouchedTests(GeofenceTestCase):
    def test_device_sync_runs_no_self_service_checks(self):
        self.make_geofence()
        employee, _user = self.make_punch_employee()
        device = self.make_device("GPS-DEV-1")

        spy = FixedCheck("inside")

        with trial_for(self.schema), passing_engines(geofence=spy) as engines:
            item = AttendanceSyncService.process_record(
                record={
                    "source_key": "gps-dev-1",
                    "employee_code": employee.employee_number,
                    "log_time": wib(WEDNESDAY, 9, 55),
                    "log_type": "in",
                },
                device=device,
            )

        self.assertTrue(item["success"])
        self.assertEqual(spy.calls, [])
        self.assertEqual(engines[checks.FACE].calls, [])
        self.assertEqual(engines[checks.LIVENESS].calls, [])

        log = AttendanceLog.objects.get(device=device)
        self.assertEqual(log.source, AttendanceSource.DEVICE)
        self.assertIsNotNone(log.attendance_id)
        self.assertFalse(AttendanceLogVerification.objects.filter(log=log).exists())
