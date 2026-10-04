"""
SEC-TENANT-JWT-1 — token hanya sah di tenant tempat ia terbit.

Dua schema tenant sungguhan. User kedua tenant sengaja ber-**id sama**,
username sama, dan pegawainya ber-nomor sama: itu persis keadaan yang
dulu membuat token tenant A lolos sebagai User tenant B.

Tenant B dibuat sekali per kelas dari schema public (pola
`apps.finance.tests.test_access.TenantIsolationTests`) dan dibuang di
`tearDownClass`.
"""

from __future__ import annotations

import base64
import json
from datetime import date

from django.contrib.auth import get_user_model
from django.db import connection
from django_tenants.utils import get_public_schema_name, schema_context
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import AccessToken, RefreshToken

from apps.accounts.jwt import TENANT_CLAIM
from apps.core.testing.tenant import ReusableTenantTestCase


User = get_user_model()

PASSWORD = "Test-Only#Pw1"
B_SCHEMA = "tenant_jwt_b"
B_DOMAIN = "tenant-jwt-b.localhost"
TWIN = "JWT0001"

LOGIN = "/api/accounts/auth/login/"
REFRESH = "/api/accounts/auth/refresh/"
AUTH_ME = "/api/accounts/auth/me/"
SELF_ME = "/api/me/"
UPLOADS = "/api/uploads/"


def _twin_employee(user, last_name):
    from apps.administration.models import Company, Location
    from apps.hr.models import Employee, OrganizationAssignment

    company, _ = Company.objects.get_or_create(
        code="JWT-CO",
        is_deleted=False,
        defaults={"name": "JWT Co"},
    )
    location, _ = Location.objects.get_or_create(
        code="JWT-HO",
        is_deleted=False,
        defaults={"company": company, "name": "HO"},
    )

    employee = Employee.objects.create(
        employee_number=TWIN,
        first_name="Twin",
        last_name=last_name,
        user=user,
    )
    OrganizationAssignment.objects.create(
        employee=employee,
        company=company,
        location=location,
        organization_effective_date=date(2026, 1, 1),
    )

    return employee


def _tamper(token: str, **claims) -> str:
    """Ganti klaim payload **tanpa** menandatangani ulang."""
    header, payload, signature = token.split(".")

    padded = payload + "=" * (-len(payload) % 4)
    data = json.loads(base64.urlsafe_b64decode(padded))
    data.update(claims)

    forged = base64.urlsafe_b64encode(
        json.dumps(data, separators=(",", ":")).encode(),
    ).rstrip(b"=").decode()

    return f"{header}.{forged}.{signature}"


class TenantBoundJWTTests(ReusableTenantTestCase):
    reusable_schema_name = "fast_tenant_jwt"

    @classmethod
    def setup_tenant(cls, tenant):
        tenant.code = "tenant-jwt"
        tenant.name = "Tenant JWT"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()

        cls.a_domain = cls.tenant.get_primary_domain().domain

        cls.user_a = User.objects.create_user(
            username="twin.user",
            email="twin.a@example.test",
            password=PASSWORD,
        )
        _twin_employee(cls.user_a, "Tenant A")

        from apps.tenants.models import Client, Domain

        with schema_context(get_public_schema_name()):
            stale = Client.objects.filter(schema_name=B_SCHEMA).first()

            if stale is not None:
                stale.delete(force_drop=True)

            cls.tenant_b = Client(
                schema_name=B_SCHEMA,
                code="tenant-jwt-b",
                name="Tenant JWT B",
            )
            cls.tenant_b.save()
            Domain.objects.create(
                domain=B_DOMAIN,
                tenant=cls.tenant_b,
                is_primary=True,
            )

        with schema_context(B_SCHEMA):
            cls.user_b = User.objects.create_user(
                id=cls.user_a.pk,
                username="twin.user",
                email="twin.b@example.test",
                password=PASSWORD,
            )
            _twin_employee(cls.user_b, "Tenant B")

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
        # Request ke host B meninggalkan koneksi di schema B.
        self.addCleanup(connection.set_tenant, self.tenant)

    # ------------------------------------------------------------------

    @staticmethod
    def api(domain, access=None) -> APIClient:
        client = APIClient(HTTP_HOST=domain)

        if access:
            client.credentials(HTTP_AUTHORIZATION=f"Bearer {access}")

        return client

    def login(self, domain) -> dict:
        response = self.api(domain).post(
            LOGIN,
            {"username": "twin.user", "password": PASSWORD},
            format="json",
        )

        self.assertEqual(response.status_code, 200, response.data)

        return response.data

    def assert_rejected(self, response):
        self.assertEqual(response.status_code, 401, response.data)
        # Tidak membocorkan alasan tenant.
        self.assertNotIn("tenant", json.dumps(response.data, default=str).lower())

    # ------------------------------------------------------------------

    def test_precondition_same_numeric_user_id(self):
        self.assertEqual(self.user_a.pk, self.user_b.pk)

    def test_issued_tokens_carry_the_tenant_claim(self):
        a = self.login(self.a_domain)
        b = self.login(B_DOMAIN)

        for tokens, tenant in ((a, self.tenant), (b, self.tenant_b)):
            for key in ("access", "refresh"):
                payload = (
                    AccessToken(tokens["access"]).payload
                    if key == "access"
                    else RefreshToken(tokens["refresh"]).payload
                )
                self.assertEqual(payload[TENANT_CLAIM], str(tenant.pk))

        self.assertNotEqual(str(self.tenant.pk), str(self.tenant_b.pk))

    def test_access_token_is_bound_to_its_tenant(self):
        a = self.login(self.a_domain)["access"]
        b = self.login(B_DOMAIN)["access"]

        own_a = self.api(self.a_domain, a).get(AUTH_ME)
        self.assertEqual(own_a.status_code, 200, own_a.data)
        self.assertEqual(own_a.data["email"], "twin.a@example.test")

        own_b = self.api(B_DOMAIN, b).get(AUTH_ME)
        self.assertEqual(own_b.status_code, 200, own_b.data)
        self.assertEqual(own_b.data["email"], "twin.b@example.test")

        self.assert_rejected(self.api(B_DOMAIN, a).get(AUTH_ME))
        self.assert_rejected(self.api(self.a_domain, b).get(AUTH_ME))

    def test_self_service_identity_never_crosses(self):
        a = self.login(self.a_domain)["access"]

        own = self.api(self.a_domain, a).get(SELF_ME)
        self.assertEqual(own.status_code, 200, own.data)
        self.assertEqual(own.data["data"]["full_name"], "Twin Tenant A")

        crossed = self.api(B_DOMAIN, a).get(SELF_ME)
        self.assert_rejected(crossed)
        self.assertNotIn("Tenant B", json.dumps(crossed.data, default=str))

    def test_enforcement_is_central_for_other_apis(self):
        a = self.login(self.a_domain)["access"]

        self.assertEqual(
            self.api(self.a_domain, a).get(UPLOADS).status_code,
            200,
        )
        self.assert_rejected(self.api(B_DOMAIN, a).get(UPLOADS))

    def test_refresh_token_is_bound_to_its_tenant(self):
        refresh = self.login(self.a_domain)["refresh"]

        same = self.api(self.a_domain).post(
            REFRESH,
            {"refresh": refresh},
            format="json",
        )
        self.assertEqual(same.status_code, 200, same.data)
        self.assertEqual(
            AccessToken(same.data["access"]).payload[TENANT_CLAIM],
            str(self.tenant.pk),
        )
        self.assertEqual(
            self.api(self.a_domain, same.data["access"]).get(AUTH_ME).status_code,
            200,
        )

        crossed = self.api(B_DOMAIN).post(
            REFRESH,
            {"refresh": refresh},
            format="json",
        )
        self.assert_rejected(crossed)
        self.assertNotIn("access", crossed.data)

    def test_legacy_tokens_without_tenant_claim_are_rejected(self):
        legacy = RefreshToken.for_user(self.user_a)

        self.assertNotIn(TENANT_CLAIM, legacy.payload)

        self.assert_rejected(
            self.api(self.a_domain, str(legacy.access_token)).get(AUTH_ME),
        )
        self.assert_rejected(
            self.api(self.a_domain).post(
                REFRESH,
                {"refresh": str(legacy)},
                format="json",
            ),
        )

    def test_tampered_tenant_claim_fails_signature(self):
        a = self.login(self.a_domain)

        forged_access = _tamper(a["access"], **{TENANT_CLAIM: str(self.tenant_b.pk)})
        forged_refresh = _tamper(a["refresh"], **{TENANT_CLAIM: str(self.tenant_b.pk)})

        self.assert_rejected(self.api(B_DOMAIN, forged_access).get(AUTH_ME))
        self.assert_rejected(
            self.api(B_DOMAIN).post(
                REFRESH,
                {"refresh": forged_refresh},
                format="json",
            ),
        )
