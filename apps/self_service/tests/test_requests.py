"""
Pengajuan pribadi — `POST /api/me/leave-requests/` dan
`POST /api/me/attendance-permissions/` — dan penjagaan subjek pada jalur
HR yang sama.

Yang dibuktikan:

* Subjek jalur pribadi **selalu** akun yang login, termasuk untuk atasan
  yang punya tim; kolom identitas apa pun ditolak dan tidak menulis
  apa-apa.
* Jalur pribadi tidak membuka kolom HR (status, override, organisasi)
  dan selalu lewat alur persetujuan — cuti tidak pernah lahir RECORDED.
* Jalur HR kini memeriksa `employee` di body terhadap cakupan tulis:
  pegawai `own` dan atasan (garis pelaporan) ditolak untuk orang lain,
  Admin Section dibatasi section-nya, HR tak berbatas tetap bisa.

Fixture dipinjam dari suite akses Shift Calendar (garis pelaporan tiga
tingkat, rekan di luar garis, Admin Section, HR).
"""

from __future__ import annotations

from django.contrib.auth.models import Permission
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection

from apps.administration.models import LeaveType
from apps.hr.models import (
    AttendancePermission,
    AttendancePermissionStatus,
    EmployeeLeave,
    LeaveStatus,
)
from apps.hr.tests.shift_calendar.test_calendar_access import (
    ShiftCalendarAccessTestCase,
)
from apps.self_service.services.requests import IDENTITY_FIELDS
from apps.workflow.models import (
    ApproverType,
    WorkflowDefinition,
    WorkflowStatus,
    WorkflowStep,
)


LEAVE_URL = "/api/me/leave-requests/"
PERMISSION_URL = "/api/me/attendance-permissions/"
HR_LEAVE_URL = "/api/hr/leaves/"
HR_PERMISSION_URL = "/api/hr/attendance-permissions/"

WRITE_CODENAMES = {
    "employeeleave": ("add", "change", "view"),
    "attendancepermission": ("add", "change", "view"),
}

# Tanggal dipilih jauh ke depan dan unik per test (lihat `next_day`),
# supaya aturan tumpang tindih tidak saling menjatuhkan antar test —
# `TenantTestCase` tidak me-rollback per test.
_DAY_OFFSET = [0]


def next_day() -> str:
    from datetime import date, timedelta

    _DAY_OFFSET[0] += 2

    return (date(2027, 1, 4) + timedelta(days=_DAY_OFFSET[0])).isoformat()


class PersonalRequestTestCase(ShiftCalendarAccessTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        for role in (cls.role_employee, cls.role_admin_section, cls.role_hr):
            for model, actions in WRITE_CODENAMES.items():
                role.permissions.add(
                    *Permission.objects.filter(
                        content_type__app_label="hr",
                        content_type__model=model,
                        codename__in=[f"{a}_{model}" for a in actions],
                    )
                )

        cls.leave_type = LeaveType.objects.create(
            code="SS-ANNUAL", name="Cuti Tahunan",
        )

        # Satu meja HR untuk kedua dokumen. Pemegangnya `user_hr`.
        for document_type in ("leave_request", "attendance_permission"):
            definition = WorkflowDefinition.objects.create(
                code=f"SS-{document_type}",
                name=document_type,
                module="hr",
                document_type=document_type,
                company=cls.company,
                status=WorkflowStatus.ACTIVE,
            )

            WorkflowStep.objects.create(
                definition=definition,
                sequence=1,
                name="HR Review",
                approver_type=ApproverType.ROLE,
                approver_role=cls.role_hr,
            )

    # ------------------------------------------------------------------

    def post(self, user, url, body):
        return self.api(user).post(url, body, content_type="application/json")

    def leave_body(self, **extra):
        day = next_day()

        return {
            "leave_type": self.leave_type.pk,
            "start_date": day,
            "end_date": day,
            "notes": "personal",
            **extra,
        }

    def permission_body(self, **extra):
        return {
            "permission_type": "full_day",
            "date": next_day(),
            "reason": "Keperluan keluarga",
            **extra,
        }

    def created(self, response, model):
        self.assertEqual(response.status_code, 201, response.content)

        body = response.json()

        # `/api/me/*` membalas beramplop; viewset HR tidak.
        return model.objects.get(pk=body.get("data", body)["id"])

    def upload(self, user):
        from apps.uploads.services.upload_service import UploadService

        return UploadService.create(
            uploaded_file=SimpleUploadedFile(
                "surat.pdf",
                b"%PDF-1.4\n1 0 obj<<>>endobj\ntrailer<<>>\n%%EOF\n",
                content_type="application/pdf",
            ),
            user=user,
            metadata={"category": "attachment"},
            generate_preview=False,
        )


# ======================================================================
# Cuti — jalur pribadi
# ======================================================================


class PersonalLeaveTests(PersonalRequestTestCase):
    def test_employee_creates_leave_for_himself(self):
        leave = self.created(
            self.post(self.user_crew, LEAVE_URL, self.leave_body()),
            EmployeeLeave,
        )

        self.assertEqual(leave.employee_id, self.crew.pk)

    def test_manager_creates_leave_for_himself_not_his_team(self):
        leave = self.created(
            self.post(self.user_manager, LEAVE_URL, self.leave_body()),
            EmployeeLeave,
        )

        self.assertEqual(leave.employee_id, self.manager.pk)

    def test_personal_leave_goes_through_approval_never_recorded(self):
        leave = self.created(
            self.post(self.user_crew, LEAVE_URL, self.leave_body()),
            EmployeeLeave,
        )

        self.assertEqual(leave.status, LeaveStatus.SUBMITTED)
        self.assertTrue(leave.document_number)
        self.assertIsNotNone(leave.total_days)

    def test_identity_fields_are_rejected_and_nothing_is_written(self):
        before = EmployeeLeave.objects.count()

        for field in sorted(IDENTITY_FIELDS):
            for value in (self.peer.pk, self.hr.pk, self.peer.employee_number):
                with self.subTest(field=field, value=value):
                    response = self.post(
                        self.user_manager,
                        LEAVE_URL,
                        self.leave_body(**{field: value}),
                    )

                    self.assertEqual(response.status_code, 400)

                    body = response.json()

                    self.assertEqual(body["code"], "field_not_accepted")
                    self.assertIn(field, body["errors"])

        self.assertEqual(EmployeeLeave.objects.count(), before)

    def test_hr_only_fields_are_rejected(self):
        for field, value in (
            ("status", "recorded"),
            ("status", "approved"),
            ("company", self.company.pk),
            ("location", self.head_office.pk),
            ("total_days", "0"),
            ("document_number", "LV-FAKE"),
        ):
            with self.subTest(field=field, value=value):
                response = self.post(
                    self.user_crew,
                    LEAVE_URL,
                    self.leave_body(**{field: value}),
                )

                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json()["errors"])

    def test_canonical_validation_still_applies(self):
        response = self.post(
            self.user_crew,
            LEAVE_URL,
            self.leave_body(start_date="2027-03-10", end_date="2027-03-01"),
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("end_date", response.json()["errors"])

    def test_overlap_rule_still_applies(self):
        body = self.leave_body()

        self.created(self.post(self.user_crew, LEAVE_URL, body), EmployeeLeave)

        again = self.post(self.user_crew, LEAVE_URL, body)

        self.assertEqual(again.status_code, 400)

    def test_own_attachment_is_accepted(self):
        attachment = self.upload(self.user_crew)

        leave = self.created(
            self.post(
                self.user_crew,
                LEAVE_URL,
                self.leave_body(uploaded_file=attachment.pk),
            ),
            EmployeeLeave,
        )

        self.assertEqual(leave.uploaded_file_id, attachment.pk)

    def test_someone_elses_attachment_is_rejected(self):
        attachment = self.upload(self.user_hr)

        response = self.post(
            self.user_crew,
            LEAVE_URL,
            self.leave_body(uploaded_file=attachment.pk),
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("uploaded_file", response.json()["errors"])

    def test_without_the_model_permission_is_403(self):
        user = self.make_user("noperm", roles=[self.role_admin_department])
        self.make_employee(section=self.section_a, user=user)

        response = self.post(user, LEAVE_URL, self.leave_body())

        self.assertEqual(response.status_code, 403)

    def test_only_post(self):
        client = self.api(self.user_crew)

        self.assertEqual(client.get(LEAVE_URL).status_code, 405)
        self.assertEqual(client.put(LEAVE_URL, {}, content_type="application/json").status_code, 405)
        self.assertEqual(client.get(f"{LEAVE_URL}{self.crew.pk}/").status_code, 404)


# ======================================================================
# Izin — jalur pribadi
# ======================================================================


class PersonalAttendancePermissionTests(PersonalRequestTestCase):
    def test_employee_creates_permission_for_himself(self):
        row = self.created(
            self.post(self.user_crew, PERMISSION_URL, self.permission_body()),
            AttendancePermission,
        )

        self.assertEqual(row.employee_id, self.crew.pk)
        self.assertIn(
            row.status,
            {
                AttendancePermissionStatus.SUBMITTED,
                AttendancePermissionStatus.IN_REVIEW,
            },
        )

    def test_manager_creates_permission_for_himself(self):
        row = self.created(
            self.post(self.user_manager, PERMISSION_URL, self.permission_body()),
            AttendancePermission,
        )

        self.assertEqual(row.employee_id, self.manager.pk)

    def test_identity_fields_are_rejected_and_nothing_is_written(self):
        before = AttendancePermission.objects.count()

        for field in sorted(IDENTITY_FIELDS):
            with self.subTest(field=field):
                response = self.post(
                    self.user_manager,
                    PERMISSION_URL,
                    self.permission_body(**{field: self.crew.pk}),
                )

                self.assertEqual(response.status_code, 400)
                self.assertEqual(response.json()["code"], "field_not_accepted")

        self.assertEqual(AttendancePermission.objects.count(), before)

    def test_hr_override_fields_are_rejected(self):
        for field, value in (
            ("allow_outside_shift", True),
            ("outside_shift_reason", "saya sendiri"),
            ("status", "approved"),
            ("company", self.company.pk),
        ):
            with self.subTest(field=field):
                response = self.post(
                    self.user_crew,
                    PERMISSION_URL,
                    self.permission_body(**{field: value}),
                )

                self.assertEqual(response.status_code, 400)
                self.assertIn(field, response.json()["errors"])

    def test_canonical_shape_validation_still_applies(self):
        response = self.post(
            self.user_crew,
            PERMISSION_URL,
            self.permission_body(permission_type="late_arrival"),
        )

        self.assertEqual(response.status_code, 400)
        self.assertIn("end_time", response.json()["errors"])


# ======================================================================
# Jalur HR — subjek dijaga cakupan tulis
# ======================================================================


class HrCreateAuthorizationTests(PersonalRequestTestCase):
    def hr_leave(self, user, employee):
        return self.post(
            user,
            HR_LEAVE_URL,
            {**self.leave_body(), "employee": employee.pk},
        )

    def hr_permission(self, user, employee):
        return self.post(
            user,
            HR_PERMISSION_URL,
            {**self.permission_body(), "employee": employee.pk},
        )

    def test_employee_cannot_create_leave_for_someone_else(self):
        before = EmployeeLeave.objects.count()

        for other in (self.peer, self.hr, self.supervisor):
            with self.subTest(other=other.employee_number):
                response = self.hr_leave(self.user_crew, other)

                self.assertEqual(response.status_code, 400)
                self.assertIn("employee", response.json()["errors"])

        self.assertEqual(EmployeeLeave.objects.count(), before)

    def test_employee_cannot_create_permission_for_someone_else(self):
        response = self.hr_permission(self.user_crew, self.peer)

        self.assertEqual(response.status_code, 400)
        self.assertIn("employee", response.json()["errors"])

    def test_reporting_line_alone_does_not_grant_create(self):
        for response in (
            self.hr_leave(self.user_manager, self.crew),
            self.hr_permission(self.user_supervisor, self.crew),
        ):
            self.assertEqual(response.status_code, 400)

    def test_own_document_through_hr_still_works(self):
        leave = self.created(self.hr_leave(self.user_crew, self.crew), EmployeeLeave)

        self.assertEqual(leave.employee_id, self.crew.pk)

    def test_hr_creates_for_anyone(self):
        for employee in (self.crew, self.ho_employee, self.other_department_employee):
            with self.subTest(employee=employee.employee_number):
                self.created(self.hr_leave(self.user_hr, employee), EmployeeLeave)
                self.created(
                    self.hr_permission(self.user_hr, employee),
                    AttendancePermission,
                )

    def test_admin_section_is_limited_to_its_section(self):
        self.created(
            self.hr_leave(self.user_admin_section, self.peer),
            EmployeeLeave,
        )

        response = self.hr_leave(self.user_admin_section, self.other_section_employee)

        self.assertEqual(response.status_code, 400)

    def test_moving_a_document_to_someone_else_is_refused(self):
        leave = self.created(self.hr_leave(self.user_crew, self.crew), EmployeeLeave)

        response = self.api(self.user_crew).patch(
            f"{HR_LEAVE_URL}{leave.pk}/",
            {"employee": self.peer.pk},
            content_type="application/json",
        )

        self.assertEqual(response.status_code, 400)

        leave.refresh_from_db()

        self.assertEqual(leave.employee_id, self.crew.pk)

    def test_hr_permission_without_employee_still_defaults_to_the_caller(self):
        response = self.post(self.user_crew, HR_PERMISSION_URL, self.permission_body())

        row = self.created(response, AttendancePermission)

        self.assertEqual(row.employee_id, self.crew.pk)

    def test_system_callers_are_not_guarded(self):
        """Service tanpa `user` (seed, TR) tidak melewati penjagaan API."""
        from apps.hr.api.leave.services import EmployeeLeaveService

        from datetime import date

        day = date.fromisoformat(next_day())

        leave = EmployeeLeaveService.create(
            data={
                "employee": self.peer,
                "leave_type": self.leave_type,
                "start_date": day,
                "end_date": day,
                "status": LeaveStatus.RECORDED,
            },
            user=self.user_crew,
        )

        self.assertEqual(leave.employee_id, self.peer.pk)


# ======================================================================
# Umum
# ======================================================================


class PersonalRequestGeneralTests(PersonalRequestTestCase):
    def test_unauthenticated_is_401(self):
        from django_tenants.test.client import TenantClient

        for url in (LEAVE_URL, PERMISSION_URL):
            response = TenantClient(self.tenant).post(
                url, {}, content_type="application/json",
            )

            self.assertEqual(response.status_code, 401)

    def test_account_without_employee_is_not_linked(self):
        user = self.make_user("nolink", roles=[self.role_hr])

        for url, body in (
            (LEAVE_URL, self.leave_body()),
            (PERMISSION_URL, self.permission_body()),
        ):
            response = self.post(user, url, body)

            self.assertEqual(response.status_code, 404)
            self.assertEqual(response.json()["code"], "employee_not_linked")

    def test_inactive_employee_is_refused(self):
        user = self.make_user("inactive", roles=[self.role_employee])
        self.make_employee(section=self.section_a, user=user, is_active=False)

        for url, body in (
            (LEAVE_URL, self.leave_body()),
            (PERMISSION_URL, self.permission_body()),
        ):
            response = self.post(user, url, body)

            self.assertEqual(response.status_code, 403)
            self.assertEqual(response.json()["code"], "employee_inactive")

    def test_request_stays_inside_the_tenant_schema(self):
        response = self.post(self.user_crew, PERMISSION_URL, self.permission_body())

        self.assertEqual(response.status_code, 201)
        self.assertEqual(connection.schema_name, self.tenant.schema_name)
