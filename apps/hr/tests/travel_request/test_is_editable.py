"""
Regression B3 (sisi kontrak): `is_editable` terbaca di payload, dan
ketiga tabel anak Travel Request membawa syarat terkuncinya di schema.

Penjagaan servicenya sudah ada sejak B3 — `assert_editable()` menolak
baris Travel Purpose/Arrangement pada dokumen `SUBMITTED`/`APPROVED`.
Yang belum ada adalah cara layar **mengetahuinya** sebelum mengirim:
`is_editable` cuma property model, dan tab resource cuma punya
`readonly` statis. Akibatnya tombol tambah/sunting tetap ditawarkan,
dan yang didapat pengguna adalah 400, bukan baris tersimpan.

Yang diuji di sini kontraknya, bukan penolakannya:

- payloadnya membawa `is_editable`, nilainya mengikuti property model;
- field itu read-only;
- ketiga tab resource membawa `readonly_when` yang menunjuk field itu;
- syaratnya menunjuk nama yang benar-benar ada di payload.

Satu kelas saja, bukan dipecah per topik: tiap `TenantTestCase`
menjalankan `migrate_schemas` sendiri, dan dua kelas berarti dua kali
ongkos itu untuk pemeriksaan yang sama-sama ringan.
"""

from __future__ import annotations

import json

from django.contrib.auth import get_user_model
from django_tenants.test.client import TenantClient
from apps.accounts.jwt import TenantRefreshToken as RefreshToken

from apps.hr.api.travel_request.serializers import TravelRequestSerializer
from apps.hr.models import TravelRequestStatus

from .base import TravelRequestTestCase


User = get_user_model()

SCHEMA_ENDPOINT = "/api/framework/schema/hr/travel-requests/"

RESOURCE_TABS = ("purposes", "travels", "accommodation")

LOCKED_WHEN = {
    "field": "is_editable",
    "op": "is_false",
}


class IsEditableContractTests(TravelRequestTestCase):
    """B3 — sinyal editability untuk tab resource."""

    _user_counter = 0

    def setUp(self):
        super().setUp()

        self.client = TenantClient(self.tenant)

    # ------------------------------------------------------------------
    # Helper
    # ------------------------------------------------------------------

    @classmethod
    def make_superuser(cls):
        """
        Superuser supaya yang diuji bentuk payloadnya, bukan cakupan
        data — penyaringan barisnya punya berkas testnya sendiri
        (`test_from_rotation_period.FromRotationPeriodScopeTests`).
        """
        cls._user_counter += 1

        return User.objects.create_user(
            username=f"trv.editable{cls._user_counter}",
            email=f"trv.editable{cls._user_counter}@example.test",
            password="Test-Only#Pw1",
            is_superuser=True,
            is_staff=True,
        )

    def auth(self, user=None):
        user = user or self.make_superuser()

        return {
            "HTTP_AUTHORIZATION": (
                f"Bearer {RefreshToken.for_user(user).access_token}"
            ),
        }

    def detail(self, request):
        response = self.client.get(
            f"/api/hr/travel-requests/{request.pk}/",
            **self.auth(),
        )

        self.assertEqual(response.status_code, 200)

        return response.json()

    def with_status(self, status):
        request = self.make_request()

        request.status = status
        request.save(update_fields=["status", "updated_at"])
        request.refresh_from_db()

        return request

    def schema(self):
        response = self.client.get(SCHEMA_ENDPOINT)

        self.assertEqual(response.status_code, 200)

        return response.json()

    # ------------------------------------------------------------------
    # Payload
    # ------------------------------------------------------------------

    def test_draft_is_editable(self):
        request = self.with_status(TravelRequestStatus.DRAFT)

        self.assertIs(self.detail(request)["is_editable"], True)

    def test_rejected_is_editable(self):
        """
        Dokumen yang ditolak harus bisa diperbaiki lalu diajukan lagi —
        kalau tabelnya ikut terkunci, tidak ada jalan memperbaikinya.
        """
        request = self.with_status(TravelRequestStatus.REJECTED)

        self.assertIs(self.detail(request)["is_editable"], True)

    def test_submitted_is_not_editable(self):
        request = self.with_status(TravelRequestStatus.SUBMITTED)

        self.assertIs(self.detail(request)["is_editable"], False)

    def test_approved_is_not_editable(self):
        request = self.with_status(TravelRequestStatus.APPROVED)

        self.assertIs(self.detail(request)["is_editable"], False)

    def test_cancelled_is_not_editable(self):
        request = self.with_status(TravelRequestStatus.CANCELLED)

        self.assertIs(self.detail(request)["is_editable"], False)

    def test_payload_follows_the_model_property(self):
        """
        Pengikat yang sebenarnya.

        Test per status di atas enak dibaca saat gagal, tapi keduanya
        bisa sama-sama benar sambil perlahan berbeda dari
        `TravelRequest.is_editable`. Yang ini menutup celah itu: kalau
        daftar status yang boleh disunting bergeser di model, payloadnya
        wajib ikut bergeser tanpa ada yang perlu menyunting berkas ini.
        """
        for status in TravelRequestStatus:
            with self.subTest(status=status):
                request = self.with_status(status)

                self.assertIs(
                    self.detail(request)["is_editable"],
                    request.is_editable,
                )

    def test_is_editable_is_read_only(self):
        """
        Dikirim di body pun diabaikan — kalau bisa ditulis, dokumen yang
        sudah disetujui bisa membuka kuncinya sendiri lewat PATCH.
        """
        request = self.with_status(TravelRequestStatus.DRAFT)

        response = self.client.patch(
            f"/api/hr/travel-requests/{request.pk}/",
            data=json.dumps(
                {
                    "is_editable": False,
                    "notes": "Disunting sambil mencoba mengunci diri.",
                },
            ),
            content_type="application/json",
            **self.auth(),
        )

        self.assertEqual(response.status_code, 200)

        request.refresh_from_db()

        self.assertIs(request.is_editable, True)
        self.assertIs(self.detail(request)["is_editable"], True)

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    def test_resource_tabs_carry_the_lock_rule(self):
        tabs = {
            tab["key"]: tab
            for tab in self.schema()["tabs"]
        }

        for key in RESOURCE_TABS:
            with self.subTest(tab=key):
                self.assertEqual(
                    tabs[key].get("readonly_when"),
                    LOCKED_WHEN,
                )

    def test_lock_rule_points_at_a_field_that_exists(self):
        """
        Syarat yang menunjuk nama yang salah ketik gagal tanpa suara:
        frontend menganggap syarat yang tidak bisa dinilai sebagai
        "terpenuhi", jadi tabelnya cuma tetap terbuka seperti sebelumnya.
        """
        self.assertIn(
            LOCKED_WHEN["field"],
            TravelRequestSerializer().fields,
        )

        self.assertIn(
            LOCKED_WHEN["field"],
            self.schema()["fields"],
        )

    def test_is_editable_is_not_a_grid_column(self):
        """
        Penanda internal, bukan kolom. Dibiarkan `table: true` ia akan
        terbit sebagai kolom "Is editable" di daftar TR pada regenerate
        frontend berikutnya.
        """
        definition = self.schema()["fields"]["is_editable"]

        self.assertIs(definition["read_only"], True)

        for flag in ("table", "filter", "search", "sortable"):
            with self.subTest(flag=flag):
                self.assertIs(definition[flag], False)
