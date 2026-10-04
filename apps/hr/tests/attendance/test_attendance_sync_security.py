"""
SEC-ATT-SYNC-1 — `/api/hr/attendance/sync/` hanya untuk mesin, terikat
tenant dan cakupan device.

Dua schema tenant sungguhan. Tenant B sengaja kembar dengan A: kode
company, kode device, kode lokasi, dan nomor pegawai sama. Yang boleh
membedakan keduanya hanya kredensialnya.
"""

from __future__ import annotations

import io
from datetime import date

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connection
from django.test import override_settings
from django_tenants.utils import (
    get_public_schema_name,
    schema_context,
    tenant_context,
)
from rest_framework.test import APIClient

from apps.accounts.jwt import TenantRefreshToken
from apps.administration.models import Company, Location
from apps.administration.models.references.hr import EmployeeGroup
from apps.core.testing.tenant import ReusableTenantTestCase
from apps.hr.api.attendance_sync.credentials import AttendanceAgentCredentialService
from apps.hr.models import (
    AttendanceDevice,
    AttendanceDeviceEmployee,
    Employee,
    EmployeeAttendance,
    EmploymentAssignment,
    OrganizationAssignment,
)


User = get_user_model()

URL = "/api/hr/attendance/sync/"
B_SCHEMA = "attendance_sync_b"
B_DOMAIN = "attendance-sync-b.localhost"

TWIN = "SYNC0001"
DEVICE = "DEV-1"


def _world(tag: str):
    """Company + lokasi + device + pegawai kembar di schema aktif."""
    company, _ = Company.objects.get_or_create(
        code="SYNC-CO", is_deleted=False, defaults={"name": f"Sync Co {tag}"},
    )
    site, _ = Location.objects.get_or_create(
        code="SYNC-SITE", is_deleted=False, defaults={"company": company, "name": "Site"},
    )
    device = AttendanceDevice.objects.create(
        code=DEVICE, name=f"Device {tag}", company=company, location=site,
    )
    employee = _employee(TWIN, company, site, last_name=tag)
    return company, site, device, employee


def _employee(number, company, location, *, last_name="X", group=None, user=None):
    employee = Employee.objects.create(
        employee_number=number, first_name="Sync", last_name=last_name, user=user,
    )
    OrganizationAssignment.objects.create(
        employee=employee,
        company=company,
        location=location,
        organization_effective_date=date(2026, 1, 1),
    )
    EmploymentAssignment.objects.create(
        employee=employee, join_date=date(2025, 1, 1), employee_group=group,
    )
    return Employee.objects.get(pk=employee.pk)


def record(employee_code=TWIN, *, at="2026-07-01T09:55:00+07:00", key=None, **extra):
    return {
        "source_key": key or f"{employee_code}-{at}",
        "employee_code": employee_code,
        "log_time": at,
        "log_type": "unknown",
        **extra,
    }


class AttendanceSyncSecurityTests(ReusableTenantTestCase):
    reusable_schema_name = "fast_attendance_sync"

    _n = 0

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "attendance-sync"
        tenant.name = "Attendance Sync"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.a_domain = cls.tenant.get_primary_domain().domain

        from apps.tenants.models import Client, Domain

        with schema_context(get_public_schema_name()):
            stale = Client.objects.filter(schema_name=B_SCHEMA).first()

            if stale is not None:
                stale.delete(force_drop=True)

            cls.tenant_b = Client(schema_name=B_SCHEMA, code="attendance-sync-b", name="Sync B")
            cls.tenant_b.save()
            Domain.objects.create(domain=B_DOMAIN, tenant=cls.tenant_b, is_primary=True)

        connection.set_tenant(cls.tenant)

    @classmethod
    def tearDownClass(cls):
        connection.set_tenant(cls.tenant)

        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")

        with schema_context(get_public_schema_name()):
            cls.tenant_b.delete(force_drop=True)

        super().tearDownClass()

    def setUp(self):
        super().setUp()
        self.addCleanup(connection.set_tenant, self.tenant)

        self.company, self.site, self.device, self.employee = _world("A")
        self.key = AttendanceAgentCredentialService.issue(self.device)

        with tenant_context(self.tenant_b):
            _c, _s, self.device_b, self.employee_b = _world("B")
            self.key_b = AttendanceAgentCredentialService.issue(self.device_b)

        def drop_b_rows():
            # Data B dibuat di dalam transaksi test yang sama, jadi
            # ikut di-rollback; ini hanya memastikan koneksi kembali ke A.
            connection.set_tenant(self.tenant)

        self.addCleanup(drop_b_rows)

    # ------------------------------------------------------------------

    @staticmethod
    def post(domain, payload, *, key=None, bearer=None):
        client = APIClient(HTTP_HOST=domain)
        headers = {}

        if key is not None:
            headers["HTTP_X_AGENT_KEY"] = key

        if bearer is not None:
            headers["HTTP_AUTHORIZATION"] = f"Bearer {bearer}"

        return client.post(URL, payload, format="json", **headers)

    @staticmethod
    def payload(*records, device_code=DEVICE):
        return {"agent_code": "AGENT-1", "device_code": device_code, "records": list(records)}

    def rows(self, tenant=None):
        with tenant_context(tenant or self.tenant):
            return list(
                EmployeeAttendance.objects
                .filter(employee__employee_number=TWIN, is_deleted=False)
                .values_list("work_date", "check_in", "source")
            )

    def assert_rejected(self, response, codes=(401,)):
        self.assertIn(response.status_code, codes, getattr(response, "data", None))
        body = str(response.data)
        for leak in (TWIN, "Sync", "employee_id", "tenant"):
            self.assertNotIn(leak, body)

    # ------------------------------------------------------------------
    # Tenant binding
    # ------------------------------------------------------------------

    def test_credential_tenant_matrix(self):
        self.assertEqual(self.rows(), [])
        self.assertEqual(self.rows(self.tenant_b), [])

        ok_a = self.post(self.a_domain, self.payload(record()), key=self.key)
        self.assertEqual(ok_a.status_code, 200, ok_a.data)
        self.assertEqual(ok_a.data["data"]["created_records"], 1)
        self.assertEqual(len(self.rows()), 1)

        self.assert_rejected(self.post(B_DOMAIN, self.payload(record()), key=self.key))
        self.assertEqual(self.rows(self.tenant_b), [])

        ok_b = self.post(B_DOMAIN, self.payload(record()), key=self.key_b)
        self.assertEqual(ok_b.status_code, 200, ok_b.data)
        self.assertEqual(len(self.rows(self.tenant_b)), 1)

        before_a = self.rows()
        self.assert_rejected(
            self.post(self.a_domain, self.payload(record(at="2026-07-01T18:05:00+07:00")), key=self.key_b),
        )
        self.assertEqual(self.rows(), before_a)

    def test_copied_credential_row_is_useless_in_another_tenant(self):
        """Ikatan tenant ada di hash, bukan cuma di hostname."""
        with tenant_context(self.tenant_b):
            AttendanceDevice.objects.filter(pk=self.device_b.pk).update(
                agent_key_id=self.device.agent_key_id,
                agent_key_hash=self.device.agent_key_hash,
            )

        self.assert_rejected(self.post(B_DOMAIN, self.payload(record()), key=self.key))
        self.assertEqual(self.rows(self.tenant_b), [])

    def test_employee_number_never_escapes_the_tenant(self):
        response = self.post(self.a_domain, self.payload(record()), key=self.key)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertEqual(response.data["data"]["results"][0]["employee_id"], self.employee.pk)

        with tenant_context(self.tenant_b):
            self.assertFalse(
                EmployeeAttendance.objects.filter(employee=self.employee_b).exists()
            )

    # ------------------------------------------------------------------
    # Manusia
    # ------------------------------------------------------------------

    def test_human_jwt_cannot_use_sync(self):
        self.__class__._n += 1
        user = User.objects.create_user(
            username=f"sync.human{self._n}", email=f"h{self._n}@example.test", password="Test-Only#Pw1",
        )
        Employee.objects.filter(pk=self.employee.pk).update(user=user)

        root = User.objects.create_user(
            username=f"sync.root{self._n}", email=f"r{self._n}@example.test",
            password="Test-Only#Pw1", is_superuser=True, is_staff=True,
        )

        for who in (user, root):
            with self.subTest(user=who.username):
                bearer = str(TenantRefreshToken.for_user(who).access_token)
                self.assert_rejected(self.post(self.a_domain, self.payload(record()), bearer=bearer))

        # Pegawai biasa juga tidak bisa menulis untuk pegawai lain.
        other = _employee("SYNC0002", self.company, self.site, last_name="Other")
        bearer = str(TenantRefreshToken.for_user(user).access_token)
        self.assert_rejected(
            self.post(self.a_domain, self.payload(record("SYNC0002")), bearer=bearer),
        )

        self.assertEqual(self.rows(), [])
        self.assertFalse(EmployeeAttendance.objects.filter(employee=other).exists())

    def test_missing_credentials_are_rejected(self):
        self.assert_rejected(self.post(self.a_domain, self.payload(record())))
        self.assertEqual(self.rows(), [])

    @override_settings(MEINOVA_AGENT_API_KEY="legacy-global-agent-key")
    def test_legacy_global_key_no_longer_authenticates(self):
        for domain in (self.a_domain, B_DOMAIN):
            with self.subTest(domain=domain):
                self.assert_rejected(
                    self.post(domain, self.payload(record()), key="legacy-global-agent-key"),
                )

        self.assertEqual(self.rows(), [])
        self.assertEqual(self.rows(self.tenant_b), [])

    # ------------------------------------------------------------------
    # Siklus hidup kredensial
    # ------------------------------------------------------------------

    def test_credential_lifecycle(self):
        key_id, secret = self.key[len("atk_"):].split(".", 1)

        cases = {
            "wrong secret": f"atk_{key_id}.{'x' * len(secret)}",
            "unknown key id": f"atk_{'0' * 16}.{secret}",
            "malformed": "not-a-key",
            "empty-ish": "atk_.",
        }

        for label, bad in cases.items():
            with self.subTest(label):
                self.assert_rejected(self.post(self.a_domain, self.payload(record()), key=bad))

        new_key = AttendanceAgentCredentialService.rotate(self.device)

        with self.subTest("rotated: old key dead"):
            self.assert_rejected(self.post(self.a_domain, self.payload(record()), key=self.key))

        with self.subTest("rotated: new key works"):
            response = self.post(self.a_domain, self.payload(record()), key=new_key)
            self.assertEqual(response.status_code, 200, response.data)

        AttendanceAgentCredentialService.revoke(self.device)

        with self.subTest("revoked"):
            self.assert_rejected(
                self.post(self.a_domain, self.payload(record(at="2026-07-01T18:05:00+07:00")), key=new_key),
            )

        third = AttendanceAgentCredentialService.issue(self.device)
        AttendanceDevice.objects.filter(pk=self.device.pk).update(is_active=False)

        with self.subTest("inactive device"):
            self.assert_rejected(
                self.post(self.a_domain, self.payload(record(at="2026-07-01T18:05:00+07:00")), key=third),
            )

        # Hanya tap dari kunci hasil rotasi yang sah yang tercatat.
        self.assertEqual(len(self.rows()), 1)

    def test_secret_is_stored_hashed_only(self):
        self.device.refresh_from_db()

        _key_id, secret = self.key[len("atk_"):].split(".", 1)

        self.assertTrue(self.device.agent_key_hash.startswith("pbkdf2_"))
        self.assertNotIn(secret, self.device.agent_key_hash)
        self.assertNotIn(secret, self.device.agent_key_id)
        self.assertEqual(self.device.integration_key, "")

    def test_management_command_lifecycle(self):
        out = io.StringIO()
        call_command("attendance_agent_key", "rotate", DEVICE, stdout=out)

        printed = out.getvalue().strip().splitlines()[-1]

        self.assertTrue(printed.startswith("atk_"))
        self.assertEqual(
            self.post(self.a_domain, self.payload(record()), key=printed).status_code,
            200,
        )

        status_out = io.StringIO()
        call_command("attendance_agent_key", "status", DEVICE, stdout=status_out)
        self.assertNotIn(printed.split(".", 1)[1], status_out.getvalue())

        call_command("attendance_agent_key", "revoke", DEVICE, stdout=io.StringIO())
        self.assert_rejected(self.post(self.a_domain, self.payload(record()), key=printed))

    # ------------------------------------------------------------------
    # Cakupan device
    # ------------------------------------------------------------------

    def test_device_scope(self):
        other_company = Company.objects.create(code="SYNC-OTHER", name="Other Co")
        other_site = Location.objects.create(company=self.company, code="SYNC-SITE-2", name="Site 2")
        board, _ = EmployeeGroup.objects.get_or_create(
            code="SYNC-BOARD", is_deleted=False,
            defaults={"name": "Board", "attendance_applicable": False},
        )

        foreign_company = _employee("SYNC1001", other_company, None, last_name="Foreign")
        other_location = _employee("SYNC1002", self.company, other_site, last_name="Elsewhere")
        not_applicable = _employee("SYNC1003", self.company, self.site, group=board)
        visitor = _employee("SYNC1004", self.company, other_site, last_name="Visitor")

        AttendanceDeviceEmployee.objects.create(
            device=self.device, external_employee_id="SYNC1004", employee=visitor,
        )

        response = self.post(
            self.a_domain,
            self.payload(
                record("SYNC1001"),
                record("SYNC1002"),
                record("SYNC1003"),
                record("SYNC1004"),
                record(TWIN),
            ),
            key=self.key,
        )

        self.assertEqual(response.status_code, 200, response.data)

        by_code = {item["employee_code"]: item for item in response.data["data"]["results"]}

        for code in ("SYNC1001", "SYNC1002", "SYNC1003"):
            with self.subTest(code=code):
                item = by_code[code]
                # Persis seperti nomor yang tidak ada — tanpa info pegawai.
                self.assertEqual(item["status"], "unmatched")
                self.assertNotIn("employee_id", item)
                self.assertNotIn("name_warning", item)

        self.assertEqual(by_code["SYNC1004"]["status"], "created")
        self.assertEqual(by_code[TWIN]["status"], "created")

        for employee in (foreign_company, other_location, not_applicable):
            self.assertFalse(EmployeeAttendance.objects.filter(employee=employee).exists())

        self.assertTrue(EmployeeAttendance.objects.filter(employee=visitor).exists())

    def test_declared_device_must_match_the_credential(self):
        response = self.post(self.a_domain, self.payload(record(), device_code="DEV-OTHER"), key=self.key)

        self.assert_rejected(response, codes=(403,))
        self.assertEqual(self.rows(), [])

    # ------------------------------------------------------------------
    # Regresi: hasil kanonik tidak berubah
    # ------------------------------------------------------------------

    def test_legitimate_sync_produces_the_canonical_row_and_is_idempotent(self):
        first = self.payload(
            record(at="2026-07-01T09:55:00+07:00", key="k-in"),
            record(at="2026-07-01T18:05:00+07:00", key="k-out"),
        )

        response = self.post(self.a_domain, first, key=self.key)

        self.assertEqual(response.status_code, 200, response.data)
        self.assertTrue(response.data["success"])

        row = EmployeeAttendance.objects.get(employee=self.employee, is_deleted=False)

        # ATT-SYNC-CORR-1: tap mesin ditandai DEVICE, bukan IMPORT (file).
        self.assertEqual(row.source, "device")
        self.assertEqual(row.device_code, DEVICE)
        self.assertEqual(row.check_in.isoformat(), "2026-07-01T02:55:00+00:00")
        self.assertEqual(row.check_out.isoformat(), "2026-07-01T11:05:00+00:00")

        snapshot = (row.check_in, row.check_out, row.first_check_in, row.last_check_out)

        retry = self.post(self.a_domain, first, key=self.key)
        self.assertEqual(retry.status_code, 200, retry.data)

        row.refresh_from_db()
        self.assertEqual(
            (row.check_in, row.check_out, row.first_check_in, row.last_check_out),
            snapshot,
        )
        self.assertEqual(
            EmployeeAttendance.objects.filter(employee=self.employee, is_deleted=False).count(),
            1,
        )

        self.device.refresh_from_db()
        self.assertIsNotNone(self.device.last_sync_at)
