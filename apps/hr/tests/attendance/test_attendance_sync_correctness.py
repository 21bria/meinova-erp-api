"""
ATT-SYNC-CORR-1 — tap agent lewat arsitektur presensi kanonik.

    kunci device → cakupan → AttendanceLog mentah → workdate.resolve()
    → AttendanceImportWriter → efek izin → log ditautkan

Lewat endpoint sungguhan (`/api/hr/attendance/sync/` + `X-Agent-Key`),
di atas panggung yang sama dengan tap Self Service: shift kantor
10:00–18:00, shift malam 20:00–05:00, shift site 07:00–17:00.
"""

from __future__ import annotations

from datetime import time
from datetime import timezone as dt_timezone

from rest_framework.test import APIClient

from apps.hr.api.attendance.schedule import WALL_CLOCK_TZ
from apps.hr.api.attendance_sync.credentials import AttendanceAgentCredentialService
from apps.hr.api.attendance_sync.services import AttendanceSyncService
from apps.hr.models import (
    AttendanceLog,
    AttendanceLogVerification,
    AttendancePermission,
    AttendancePermissionStatus,
    AttendancePermissionType,
    AttendanceSource,
    AttendanceStatus,
    EmployeeAttendance,
)

from .punch_base import SATURDAY, THURSDAY, WEDNESDAY, SelfPunchTestCase, wib


URL = "/api/hr/attendance/sync/"
DEVICE = "SYNC-CORR-1"


def rows_of(employee):
    return list(
        EmployeeAttendance.objects
        .filter(employee=employee, is_deleted=False)
        .order_by("work_date")
    )


def logs_of(employee):
    return list(
        AttendanceLog.objects
        .filter(employee=employee)
        .order_by("occurred_at", "id")
    )


class AttendanceSyncCorrectnessTestCase(SelfPunchTestCase):
    """Schema dan baseline milik tap Self Service dipakai ulang."""

    def setUp(self):
        super().setUp()

        self.domain = self.tenant.get_primary_domain().domain
        self.device = self.make_device(DEVICE)
        self.key = AttendanceAgentCredentialService.issue(self.device)

    def sync(self, *records, key=None):
        response = APIClient(HTTP_HOST=self.domain).post(
            URL,
            {"agent_code": "AGENT-1", "device_code": DEVICE, "records": list(records)},
            format="json",
            HTTP_X_AGENT_KEY=key or self.key,
        )

        self.assertEqual(response.status_code, 200, getattr(response, "data", None))

        return response.data["data"]

    @staticmethod
    def tap(employee, at, *, key=None, log_type="unknown", number=None):
        code = number or employee.employee_number

        return {
            "source_key": key or f"{code}|{at.isoformat()}",
            "employee_code": code,
            "log_time": at.isoformat(),
            "log_type": log_type,
            "raw_payload": {"serno": "42", "inout": log_type},
        }

    def assert_linked(self, log, attendance):
        self.assertEqual(log.attendance_id, attendance.pk)
        self.assertTrue(log.is_processed)
        self.assertIsNotNone(log.processed_at)
        self.assertEqual(log.processing_error, "")


# ======================================================================
# Provenance
# ======================================================================


class ProvenanceTests(AttendanceSyncCorrectnessTestCase):
    def test_valid_tap_creates_a_linked_raw_log(self):
        employee = self.make_employee(shift=self.office_shift)
        at = wib(WEDNESDAY, 9, 55)
        record = self.tap(employee, at, key="k-1")

        data = self.sync(record)

        self.assertEqual(data["created_records"], 1)
        item = data["results"][0]
        self.assertEqual(item["status"], "created")
        self.assertEqual(item["work_date"], WEDNESDAY.isoformat())

        [row] = rows_of(employee)
        [log] = logs_of(employee)

        self.assertEqual(item["attendance_id"], row.pk)
        self.assert_linked(log, row)

        self.assertEqual(log.source, AttendanceSource.DEVICE)
        self.assertEqual(
            log.external_id,
            AttendanceSyncService.external_id_for(self.device, "k-1"),
        )
        self.assertEqual(log.device_id, self.device.pk)
        self.assertEqual(log.company_id, self.company.pk)
        self.assertEqual(log.location_id, self.site.pk)
        self.assertEqual(log.occurred_at, at)
        self.assertEqual(log.log_type, "unknown")
        self.assertEqual(log.employee_identifier, employee.employee_number)
        self.assertEqual(log.raw_payload["source_key"], "k-1")
        self.assertEqual(log.raw_payload["agent_code"], "AGENT-1")
        self.assertEqual(log.raw_payload["machine"], {"serno": "42", "inout": "unknown"})

        self.assertEqual(row.source, AttendanceSource.DEVICE)
        self.assertEqual(row.work_date, WEDNESDAY)
        self.assertEqual(row.check_in, at)
        self.assertEqual(row.scheduled_check_in, wib(WEDNESDAY, 10, 0))

        # Tap mesin bukan bukti verifikasi Self Service.
        self.assertFalse(AttendanceLogVerification.objects.filter(log=log).exists())

    def test_in_and_out_produce_two_logs_on_one_day_and_retry_writes_nothing(self):
        employee = self.make_employee(shift=self.office_shift)

        batch = (
            self.tap(employee, wib(WEDNESDAY, 9, 55), key="k-in", log_type="in"),
            self.tap(employee, wib(WEDNESDAY, 18, 5), key="k-out", log_type="out"),
        )

        first = self.sync(*batch)

        self.assertEqual(first["accepted_records"], 2)

        [row] = rows_of(employee)
        logs = logs_of(employee)

        self.assertEqual([log.log_type for log in logs], ["in", "out"])

        for log in logs:
            self.assert_linked(log, row)

        self.assertEqual(row.check_in, wib(WEDNESDAY, 9, 55))
        self.assertEqual(row.check_out, wib(WEDNESDAY, 18, 5))

        snapshot = EmployeeAttendance.objects.filter(pk=row.pk).values().get()
        processed = [(log.pk, log.processed_at) for log in logs]

        retry = self.sync(*batch)

        self.assertEqual(retry["duplicate_records"], 2)
        self.assertEqual(retry["created_records"], 0)
        self.assertEqual(retry["updated_records"], 0)
        self.assertEqual(retry["failed_records"], 0)
        self.assertEqual(retry["accepted_records"], 2)

        for item in retry["results"]:
            self.assertTrue(item["success"])
            self.assertEqual(item["status"], "duplicate")
            self.assertEqual(item["attendance_id"], row.pk)

        self.assertEqual(
            [(log.pk, log.processed_at) for log in logs_of(employee)],
            processed,
        )
        self.assertEqual(
            EmployeeAttendance.objects.filter(pk=row.pk).values().get(),
            snapshot,
        )

    def test_same_source_key_for_a_different_tap_is_a_conflict(self):
        employee = self.make_employee(shift=self.office_shift)

        self.sync(self.tap(employee, wib(WEDNESDAY, 9, 55), key="k-same"))

        data = self.sync(self.tap(employee, wib(WEDNESDAY, 18, 5), key="k-same"))

        [item] = data["results"]
        self.assertFalse(item["success"])
        self.assertEqual(item["status"], "conflict")
        self.assertEqual(len(logs_of(employee)), 1)

        [row] = rows_of(employee)
        self.assertIsNone(row.check_out)

    def test_same_source_key_on_another_device_is_another_tap(self):
        employee = self.make_employee(shift=self.office_shift)
        other = self.make_device("SYNC-CORR-2")
        other_key = AttendanceAgentCredentialService.issue(other)

        self.sync(self.tap(employee, wib(WEDNESDAY, 9, 55), key="k-shared"))

        response = APIClient(HTTP_HOST=self.domain).post(
            URL,
            {
                "agent_code": "AGENT-2",
                "device_code": other.code,
                "records": [self.tap(employee, wib(WEDNESDAY, 18, 5), key="k-shared")],
            },
            format="json",
            HTTP_X_AGENT_KEY=other_key,
        )

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["updated_records"], 1)
        self.assertEqual(
            sorted(log.device_id for log in logs_of(employee)),
            sorted([self.device.pk, other.pk]),
        )


# ======================================================================
# Hari kerja
# ======================================================================


class WorkDateTests(AttendanceSyncCorrectnessTestCase):
    def test_overnight_shift_stays_on_its_start_date(self):
        employee = self.make_employee(shift=self.late_night_shift)

        # Dua batch terpisah, seperti agent sungguhan: masuk malam ini,
        # pulang dikirim sesudah tengah malam.
        self.sync(self.tap(employee, wib(WEDNESDAY, 20, 0), key="n-in", log_type="in"))
        self.sync(self.tap(employee, wib(THURSDAY, 2, 0), key="n-out", log_type="out"))

        [row] = rows_of(employee)

        self.assertEqual(row.work_date, WEDNESDAY)
        self.assertEqual(row.check_in, wib(WEDNESDAY, 20, 0))
        self.assertEqual(row.check_out, wib(THURSDAY, 2, 0))
        self.assertEqual(row.scheduled_check_out, wib(THURSDAY, 5, 0))

        self.assertFalse(
            EmployeeAttendance.objects.filter(
                employee=employee,
                work_date=THURSDAY,
                is_deleted=False,
            ).exists()
        )

        logs = logs_of(employee)
        self.assertEqual(len(logs), 2)

        for log in logs:
            self.assert_linked(log, row)

    def test_checkout_after_wall_clock_date_change_still_belongs_to_the_shift(self):
        employee = self.make_employee(shift=self.late_night_shift)
        out = wib(THURSDAY, 7, 30)

        # Tanggal UTC dan tanggal jam dinding sama-sama Kamis; hanya
        # jadwal yang tahu tap ini milik shift Rabu malam.
        self.assertEqual(out.astimezone(WALL_CLOCK_TZ).date(), THURSDAY)

        self.sync(self.tap(employee, wib(WEDNESDAY, 20, 5), key="l-in"))
        self.sync(self.tap(employee, out, key="l-out"))

        [row] = rows_of(employee)

        self.assertEqual(row.work_date, WEDNESDAY)
        self.assertEqual(row.check_out, out)

    def test_early_morning_tap_uses_wall_clock_not_utc_date(self):
        employee = self.make_employee(shift=self.day_shift)

        # 06:30 di zona jam dinding = 23:30 UTC hari sebelumnya.
        at = wib(THURSDAY, 6, 30)

        # Prasyarat test: tanggal UTC dan tanggal jam dinding berbeda.
        self.assertEqual(at.astimezone(WALL_CLOCK_TZ).date(), THURSDAY)
        self.assertEqual(at.astimezone(dt_timezone.utc).date(), WEDNESDAY)

        data = self.sync(self.tap(employee, at, key="tz-1"))

        self.assertEqual(data["results"][0]["work_date"], THURSDAY.isoformat())

        [row] = rows_of(employee)

        self.assertEqual(row.work_date, THURSDAY)
        self.assertEqual(row.scheduled_check_in, wib(THURSDAY, 7, 0))

    def test_normal_day_shift(self):
        employee = self.make_employee(shift=self.day_shift)

        self.sync(
            self.tap(employee, wib(WEDNESDAY, 6, 50), key="d-in"),
            self.tap(employee, wib(WEDNESDAY, 17, 10), key="d-out"),
        )

        [row] = rows_of(employee)

        self.assertEqual(row.work_date, WEDNESDAY)
        self.assertEqual(row.check_in, wib(WEDNESDAY, 6, 50))
        self.assertEqual(row.check_out, wib(WEDNESDAY, 17, 10))
        self.assertEqual(row.late_minutes, 0)


# ======================================================================
# Izin & perilaku harian yang sudah ada
# ======================================================================


class DailyBehaviourTests(AttendanceSyncCorrectnessTestCase):
    def test_permission_approved_before_the_first_device_tap_is_applied(self):
        employee = self.make_employee(shift=self.office_shift)

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

        self.sync(self.tap(employee, wib(WEDNESDAY, 11, 0), key="p-1"))

        [row] = rows_of(employee)

        self.assertEqual(row.status, AttendanceStatus.LATE)
        self.assertEqual(row.late_minutes, 60)
        self.assertEqual(row.excused_late_minutes, 60)
        self.assertEqual(row.permission_state, "excused")

        # Kiriman ulang tidak menghitung izinnya dua kali.
        self.sync(self.tap(employee, wib(WEDNESDAY, 11, 0), key="p-1"))

        row.refresh_from_db()
        self.assertEqual(row.excused_late_minutes, 60)

    def test_earliest_in_and_latest_out_regardless_of_arrival_order(self):
        employee = self.make_employee(shift=self.office_shift)

        self.sync(self.tap(employee, wib(WEDNESDAY, 12, 0), key="o-1"))
        self.sync(self.tap(employee, wib(WEDNESDAY, 9, 50), key="o-2"))
        self.sync(self.tap(employee, wib(WEDNESDAY, 18, 30), key="o-3"))
        self.sync(self.tap(employee, wib(WEDNESDAY, 17, 0), key="o-4"))

        [row] = rows_of(employee)

        self.assertEqual(row.check_in, wib(WEDNESDAY, 9, 50))
        self.assertEqual(row.first_check_in, wib(WEDNESDAY, 9, 50))
        self.assertEqual(row.check_out, wib(WEDNESDAY, 18, 30))
        self.assertEqual(row.last_check_out, wib(WEDNESDAY, 18, 30))
        self.assertEqual(len(logs_of(employee)), 4)

    def test_business_trip_day_follows_physical_fact_wins(self):
        employee = self.make_employee(shift=self.office_shift)

        trip = EmployeeAttendance.objects.create(
            employee=employee,
            company=self.company,
            work_date=WEDNESDAY,
            status=AttendanceStatus.BUSINESS_TRIP,
            source=AttendanceSource.SYSTEM,
        )

        self.sync(self.tap(employee, wib(WEDNESDAY, 9, 50), key="bt-1"))

        trip.refresh_from_db()

        # Aturan Business Trip yang terkunci: tap fisik di hari dinas =
        # hari hadir ("physical fact wins"), sumber baris tetap SYSTEM —
        # sama dengan tap Self Service dan perilaku agent sebelumnya.
        self.assertEqual(trip.status, AttendanceStatus.PRESENT)
        self.assertEqual(trip.source, AttendanceSource.SYSTEM)
        self.assertEqual(trip.check_in, wib(WEDNESDAY, 9, 50))
        self.assert_linked(logs_of(employee)[0], trip)

    def test_unscheduled_day_is_recorded_as_off_worked(self):
        employee = self.make_employee(shift=self.office_shift)

        self.sync(self.tap(employee, wib(SATURDAY, 9, 0), key="off-1"))

        [row] = rows_of(employee)

        self.assertEqual(row.work_date, SATURDAY)
        self.assertIsNone(row.scheduled_check_in)
        self.assertEqual(row.late_minutes, 0)
        self.assert_linked(logs_of(employee)[0], row)


# ======================================================================
# Record yang tidak diterima
# ======================================================================


class RejectedRecordTests(AttendanceSyncCorrectnessTestCase):
    def test_unmatched_and_out_of_scope_leave_no_evidence(self):
        outsider = self.make_employee(shift=self.office_shift, location=self.other_site)

        data = self.sync(
            self.tap(outsider, wib(WEDNESDAY, 9, 55), key="x-1"),
            self.tap(outsider, wib(WEDNESDAY, 9, 56), key="x-2", number="NOBODY-1"),
        )

        self.assertEqual(data["unmatched_records"], 2)

        for item in data["results"]:
            self.assertFalse(item["success"])
            self.assertEqual(item["status"], "unmatched")
            self.assertNotIn("employee_id", item)

        self.assertEqual(rows_of(outsider), [])
        self.assertFalse(AttendanceLog.objects.filter(device=self.device).exists())

    def test_failed_record_rolls_back_alone_and_says_nothing_about_the_employee(self):
        closed = self.make_employee(shift=self.office_shift)
        fine = self.make_employee(shift=self.office_shift)

        # Hari yang sudah ditutup ABSENT tidak boleh diberi jam masuk
        # diam-diam (`full_clean()` menolaknya).
        absent = EmployeeAttendance.objects.create(
            employee=closed,
            company=self.company,
            work_date=WEDNESDAY,
            status=AttendanceStatus.ABSENT,
            source=AttendanceSource.SYSTEM,
        )

        data = self.sync(
            self.tap(closed, wib(WEDNESDAY, 9, 55), key="f-1"),
            self.tap(fine, wib(WEDNESDAY, 9, 55), key="f-2"),
        )

        failed, ok = data["results"]

        self.assertFalse(failed["success"])
        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["message"], "Record could not be processed.")
        self.assertNotIn(closed.full_name, str(data))

        absent.refresh_from_db()
        self.assertIsNone(absent.check_in)
        self.assertEqual(logs_of(closed), [])

        self.assertTrue(ok["success"])
        self.assert_linked(logs_of(fine)[0], rows_of(fine)[0])
