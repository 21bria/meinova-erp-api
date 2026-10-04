"""
Tap kehadiran Self Service di dua schema tenant sungguhan.

Pola tenant kedua mengikuti `apps.finance.tests.test_access.
TenantIsolationTests`: dibuat dari schema public di dalam test, lalu
`SET CONSTRAINTS ALL IMMEDIATE` dan `delete(force_drop=True)`.

**Token sungguhan, bukan `force_authenticate`.** `force_authenticate`
menempelkan objek User dari schema A langsung ke request dan melewati
autentikasi — padahal yang menyeberang host di dunia nyata adalah
token-nya. Jadi test ini menerbitkan JWT di tenant A lalu memakainya di
host tenant B.

Kembar yang disengaja: nomor pegawai, username, `id` User, dan
`client_punch_id` dibuat sama di kedua tenant — id berurutan kecil
memang pasti bertabrakan antar schema di produksi.
"""

from __future__ import annotations

from unittest import mock
from uuid import uuid4

from django.db import connection
from django_tenants.utils import get_public_schema_name, schema_context, tenant_context
from rest_framework.test import APIClient

from apps.hr.api.attendance.punch import AttendancePunchService, PunchRequest
from apps.hr.models import (
    AttendanceLog,
    AttendanceLogVerification,
    Employee,
    EmployeeAttendance,
)
from apps.hr.tests.attendance.punch_base import (
    SelfPunchTestCase,
    WEDNESDAY,
    passing_engines,
    wib,
)
from apps.uploads.models import UploadedFile


URL = "/api/me/attendance/punch/"
NOW = "apps.hr.api.attendance.punch.timezone.now"

B_SCHEMA = "self_punch_tenant_b"
B_DOMAIN = "self-punch-tenant-b.localhost"
B_COMPANY = "SPB"
TWIN_NUMBER = "TWIN0001"


class SelfPunchTenancyTests(SelfPunchTestCase):
    reusable_schema_name = "fast_self_punch_tenancy"
    punch_enabled = True

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "self-punch-tenancy"
        tenant.name = "Self Punch Tenancy"

    # ------------------------------------------------------------------

    def client_on(self, domain: str, user) -> APIClient:
        """
        Token diterbitkan lewat jalur login kanonik di **tenant A** — sejak
        SEC-TENANT-JWT-1 token tanpa klaim tenant ditolak di mana pun.
        """
        from apps.accounts.api.auth.serializers import LoginSerializer

        with tenant_context(self.tenant):
            access = str(LoginSerializer.get_token(user).access_token)

        client = APIClient(HTTP_HOST=domain)
        client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")
        return client

    def post(self, domain, user, payload, *, at):
        with mock.patch(NOW, return_value=at):
            return self.client_on(domain, user).post(URL, payload, format="json")

    def body(self, owner, /, **overrides):
        payload = {
            "client_punch_id": str(uuid4()),
            "punch_type": "in",
            "latitude": "-6.2000000",
            "longitude": "106.8166667",
            "location_accuracy": "10",
            "selfie": self.make_selfie(owner).pk,
        }
        payload.update(overrides)
        return payload

    def build_tenant_b(self, *, user_id: int, username: str, punch_id):
        """Tenant B lengkap dengan pegawai kembar dan satu tap ACCEPTED."""
        from apps.administration.models import Company, Location
        from apps.administration.models.references.hr_attendance import Shift
        from apps.hr.models import EmploymentAssignment, OrganizationAssignment
        from apps.tenants.models import Client, Domain
        from datetime import date
        from decimal import Decimal

        from django.contrib.auth import get_user_model

        with schema_context(get_public_schema_name()):
            other = Client(
                schema_name=B_SCHEMA,
                code="self-punch-b",
                name="Self Punch B",
            )
            other.save()
            Domain.objects.create(domain=B_DOMAIN, tenant=other, is_primary=True)

        with schema_context(B_SCHEMA):
            company = Company.objects.create(code=B_COMPANY, name="Tenant B Co")
            location = Location.objects.create(
                company=company,
                code="SPB-HO",
                name="B Head Office",
            )
            shift = Shift.objects.create(
                code="SPB-OFFICE",
                name="Office",
                start_time="10:00",
                end_time="18:00",
            )

            user = get_user_model().objects.create_user(
                id=user_id,
                username=username,
                email=f"b.{username}@example.test",
                password="Test-Only#Pw1",
            )

            employee = Employee.objects.create(
                employee_number=TWIN_NUMBER,
                first_name="Twin",
                last_name="Tenant B",
                user=user,
            )
            OrganizationAssignment.objects.create(
                employee=employee,
                company=company,
                location=location,
                organization_effective_date=date(2026, 1, 1),
            )
            EmploymentAssignment.objects.create(
                employee=employee,
                join_date=date(2025, 1, 1),
                shift=shift,
            )
            employee = Employee.objects.get(pk=employee.pk)

            # Pendaftaran wajah tenant B tinggal di schema B (ATT-BIO-2A).
            from apps.hr.api.attendance.biometric_enrollment import (
                BiometricEnrollmentService,
            )
            from apps.hr.tests.attendance.punch_base import TEST_FACE_PROVIDER

            enrollment = BiometricEnrollmentService.enroll(
                employee=employee,
                provider=TEST_FACE_PROVIDER,
                user=None,
            )

            selfie = self.make_selfie(user)

            result = AttendancePunchService.record(
                employee=employee,
                user=user,
                request=PunchRequest(
                    client_punch_id=punch_id,
                    punch_type="in",
                    latitude=Decimal("-6.2"),
                    longitude=Decimal("106.8"),
                    accuracy_meters=Decimal("10"),
                    photo=selfie,
                ),
                now=wib(WEDNESDAY, 9, 55),
            )

            return other, {
                "employee_pk": employee.pk,
                "log_pk": result.log.pk,
                "verification_pk": result.verification.pk,
                "decision": result.decision,
                "selfie_public_id": selfie.public_id,
                "subject_id": str(enrollment.subject_id),
            }

    @staticmethod
    def drop(other) -> None:
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")

        with schema_context(get_public_schema_name()):
            other.delete(force_drop=True)

    @staticmethod
    def b_state():
        with schema_context(B_SCHEMA):
            return {
                "logs": list(
                    AttendanceLog.objects
                    .filter(employee__employee_number=TWIN_NUMBER)
                    .values_list("log_type", "external_id", "company__code")
                ),
                "rows": list(
                    EmployeeAttendance.objects
                    .filter(employee__employee_number=TWIN_NUMBER)
                    .values_list("work_date", "check_in", "check_out")
                ),
            }

    # ------------------------------------------------------------------

    def test_punch_evidence_never_crosses_tenants(self):
        a_domain = self.tenant.get_primary_domain().domain

        employee_a, user_a = self.make_punch_employee(number=TWIN_NUMBER)

        punch_id = uuid4()

        with passing_engines():
            other, b = self.build_tenant_b(
                user_id=user_a.pk,
                username=user_a.username,
                punch_id=punch_id,
            )

            try:
                self.assertEqual(b["decision"], "accepted")

                b_before = self.b_state()

                # --- Kembar: nomor pegawai & client_punch_id sama ----------
                with self.subTest("identical ids do not collide"):
                    response = self.post(
                        a_domain,
                        user_a,
                        self.body(user_a, client_punch_id=str(punch_id)),
                        at=wib(WEDNESDAY, 9, 56),
                    )

                    self.assertEqual(response.status_code, 201, response.data)
                    self.assertEqual(response.data["data"]["result"], "accepted")
                    self.assertFalse(response.data["data"]["replayed"])

                    log = AttendanceLog.objects.get(
                        external_id=f"self-punch:{punch_id}",
                    )
                    self.assertEqual(log.employee_id, employee_a.pk)
                    self.assertEqual(log.company_id, self.company.pk)

                # --- Manipulasi payload ke pegawai B -------------------------
                with self.subTest("payload cannot name tenant B employee"):
                    response = self.post(
                        a_domain,
                        user_a,
                        self.body(
                            user_a,
                            punch_type="out",
                            employee_id=b["employee_pk"],
                        ),
                        at=wib(WEDNESDAY, 18, 5),
                    )

                    self.assertEqual(response.status_code, 400)
                    self.assertEqual(response.data["code"], "field_not_accepted")

                # --- Bukti B tidak terlihat dari A ---------------------------
                with self.subTest("tenant B evidence invisible from A"):
                    self.assertFalse(
                        AttendanceLog.objects.filter(
                            company__code=B_COMPANY,
                        ).exists()
                    )
                    self.assertFalse(
                        AttendanceLogVerification.objects.filter(
                            log__company__code=B_COMPANY,
                        ).exists()
                    )
                    self.assertEqual(
                        set(
                            AttendanceLog.objects
                            .filter(employee__employee_number=TWIN_NUMBER)
                            .values_list("company_id", flat=True)
                        ),
                        {self.company.pk},
                    )
                    self.assertFalse(
                        UploadedFile.objects.filter(
                            public_id=b["selfie_public_id"],
                        ).exists()
                    )

                    response = self.client_on(a_domain, user_a).get(
                        f"/api/uploads/{b['selfie_public_id']}/download/",
                    )
                    self.assertEqual(response.status_code, 404)

                # --- Pendaftaran wajah B tidak terlihat dari A (ATT-BIO-2A) ----
                with self.subTest("tenant B biometric enrollment invisible from A"):
                    from apps.hr.api.attendance.biometric_enrollment import (
                        BiometricEnrollmentService,
                    )
                    from apps.hr.models import EmployeeBiometricEnrollment
                    from apps.hr.tests.attendance.punch_base import TEST_FACE_PROVIDER

                    self.assertFalse(
                        EmployeeBiometricEnrollment.objects.filter(
                            subject_id=b["subject_id"],
                        ).exists()
                    )

                    subject_a = BiometricEnrollmentService.subject_for(
                        employee_a,
                        TEST_FACE_PROVIDER,
                    )
                    self.assertIsNotNone(subject_a)
                    self.assertNotEqual(subject_a.subject_id, b["subject_id"])

                # --- Token tenant A dipakai di host tenant B -----------------
                with self.subTest("tenant A token cannot resolve a tenant B identity"):
                    response = self.client_on(B_DOMAIN, user_a).get("/api/me/")

                    self.assertIn(response.status_code, (401, 403), response.data)

                with self.subTest("tenant A token cannot act on tenant B"):
                    response = self.post(
                        B_DOMAIN,
                        user_a,
                        self.body(user_a, punch_type="out"),
                        at=wib(WEDNESDAY, 18, 5),
                    )

                    self.assertIn(response.status_code, (401, 403), response.data)
                    self.assertEqual(self.b_state(), b_before)

                with self.subTest("tenant A token cannot read tenant B selfie"):
                    response = self.client_on(B_DOMAIN, user_a).get(
                        f"/api/uploads/{b['selfie_public_id']}/download/",
                    )

                    self.assertIn(response.status_code, (401, 403, 404))

                # --- B utuh ----------------------------------------------
                with self.subTest("tenant B data intact"):
                    self.assertEqual(
                        b_before["logs"],
                        [("in", f"self-punch:{punch_id}", B_COMPANY)],
                    )
            finally:
                # Request ke host B meninggalkan koneksi di schema B
                # (`TenantMainMiddleware`). Kembalikan dulu ke A.
                connection.set_tenant(self.tenant)
                self.drop(other)
