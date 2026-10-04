"""
ASSET-1B — master Asset Category.

Yang dikunci berkas ini kontrak, bukan rincian implementasi
(`docs/claude/assets.md` §5):

* kategori master data tenant-wide — tanpa company, tabelnya hidup di
  schema tenant, bukan `public`;
* kode dinormalisasi (trim + huruf besar) dan unik tanpa membedakan
  huruf di antara baris yang belum dihapus — oleh service **dan**
  database;
* hapus = soft delete lewat service (beserta jejak audit), dan kode
  yang sudah dihapus boleh dipakai lagi;
* tulis lewat API wajib lewat service dan dijaga izin model; baca
  terbuka;
* kolom penghapusan tidak bisa ditulis lewat API.

Lewat HTTP sungguhan dengan token JWT untuk bagian API: yang diuji jalur
permission dan service, dan itu baru berarti kalau `request.user` datang
dari jalur layar.
"""

from __future__ import annotations

import json

from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, transaction
from django.test import override_settings
from django_tenants.test.client import TenantClient
from django_tenants.utils import schema_context
from apps.accounts.jwt import TenantRefreshToken as RefreshToken

from apps.administration.models import AuditTrail
from apps.assets.models import AssetCategory
from apps.assets.services import AssetCategoryService

from .base import AssetsTestCase


ENDPOINT = "/api/assets/categories/"
LOOKUP = "/api/assets/lookup/asset-categories/"


class AssetCategoryTestCase(AssetsTestCase):
    pass


class AssetCategoryServiceTests(AssetCategoryTestCase):
    def test_create_normalizes_code_and_trims_name(self):
        raw = self.next_code().lower()

        category = AssetCategoryService.create(
            data={"code": f"  {raw}  ", "name": "  Laptop  "},
        )

        category.refresh_from_db()

        self.assertEqual(category.code, raw.upper())
        self.assertEqual(category.name, "Laptop")
        self.assertTrue(category.is_active)
        self.assertFalse(category.is_deleted)

    def test_duplicate_code_is_rejected_regardless_of_case(self):
        code = self.next_code()

        AssetCategoryService.create(data={"code": code, "name": "First"})

        with self.assertRaises(ValidationError) as caught:
            AssetCategoryService.create(
                data={"code": code.lower(), "name": "Second"},
            )

        self.assertIn("code", caught.exception.message_dict)

    def test_update_keeps_code_unique_but_allows_own_code(self):
        taken = AssetCategoryService.create(
            data={"code": self.next_code(), "name": "Radio"},
        )
        category = AssetCategoryService.create(
            data={"code": self.next_code(), "name": "GPS"},
        )

        renamed = AssetCategoryService.update(
            instance=category,
            data={"code": category.code.lower(), "name": "GPS Handheld"},
        )

        self.assertEqual(renamed.code, category.code)
        self.assertEqual(renamed.name, "GPS Handheld")

        with self.assertRaises(ValidationError):
            AssetCategoryService.update(
                instance=category,
                data={"code": taken.code},
            )

    def test_soft_delete_hides_row_keeps_audit_and_frees_code(self):
        code = self.next_code()
        user = self.make_user()

        category = AssetCategoryService.create(
            data={"code": code, "name": "Furniture"},
            user=user,
        )

        AssetCategoryService.soft_delete(instance=category, user=user)

        category.refresh_from_db()

        self.assertTrue(category.is_deleted)
        self.assertEqual(category.deleted_by, user)
        self.assertNotIn(category, AssetCategoryService.list())

        self.assertTrue(
            AuditTrail.objects.filter(
                object_id=str(category.pk),
                action="delete",
            ).exists(),
        )

        reused = AssetCategoryService.create(
            data={"code": code, "name": "Furniture (new)"},
        )

        self.assertNotEqual(reused.pk, category.pk)
        self.assertEqual(reused.code, code)

    def test_database_rejects_two_active_rows_with_the_same_code(self):
        # Penjaga terakhir kalau jalur service dilewati: constraint
        # database, bukan hanya pemeriksaan service.
        code = self.next_code()

        AssetCategory.objects.create(code=code, name="One")

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AssetCategory.objects.create(code=code, name="Two")

    def test_table_lives_in_the_tenant_schema_not_public(self):
        self.assertIn(
            "assets_asset_category",
            connection.introspection.table_names(),
        )

        with schema_context("public"):
            self.assertNotIn(
                "assets_asset_category",
                connection.introspection.table_names(),
            )


@override_settings(ENFORCE_MODEL_PERMISSIONS=True)
class AssetCategoryApiTests(AssetCategoryTestCase):
    WRITE_PERMISSIONS = (
        "view_assetcategory",
        "add_assetcategory",
        "change_assetcategory",
        "delete_assetcategory",
    )

    def setUp(self):
        super().setUp()

        self.http = TenantClient(self.tenant)

    # ------------------------------------------------------------------

    def call(self, method, path, user, payload=None):
        token = RefreshToken.for_user(user).access_token

        kwargs = {"HTTP_AUTHORIZATION": f"Bearer {token}"}

        if payload is not None:
            kwargs["data"] = json.dumps(payload)
            kwargs["content_type"] = "application/json"

        return getattr(self.http, method)(path, **kwargs)

    @staticmethod
    def body(response):
        return json.loads(response.content) if response.content else None

    @classmethod
    def rows(cls, response) -> list[dict]:
        body = cls.body(response)

        return body["data"] if isinstance(body, dict) else body

    # ------------------------------------------------------------------

    def test_crud_runs_through_the_service(self):
        writer = self.make_user(permissions=self.WRITE_PERMISSIONS)
        code = self.next_code()

        created = self.call(
            "post",
            ENDPOINT,
            writer,
            {"code": f" {code.lower()} ", "name": " Light Vehicle "},
        )

        self.assertEqual(created.status_code, 201, created.content[:500])

        category = AssetCategory.objects.get(code=code, is_deleted=False)

        # Normalisasi dan `created_by` hanya diisi service — kalau
        # tulisnya lewat `serializer.save()`, keduanya tidak terjadi.
        self.assertEqual(category.name, "Light Vehicle")
        self.assertEqual(category.created_by, writer)
        self.assertTrue(
            AuditTrail.objects.filter(
                object_id=str(category.pk),
                action="create",
            ).exists(),
        )

        listed = self.call("get", f"{ENDPOINT}?search={code}", writer)

        self.assertEqual(listed.status_code, 200)
        self.assertEqual(
            [row["code"] for row in self.rows(listed)],
            [code],
        )

        patched = self.call(
            "patch",
            f"{ENDPOINT}{category.pk}/",
            writer,
            {"name": "LV"},
        )

        self.assertEqual(patched.status_code, 200, patched.content[:500])

        category.refresh_from_db()

        self.assertEqual(category.name, "LV")
        self.assertEqual(category.updated_by, writer)

        deleted = self.call("delete", f"{ENDPOINT}{category.pk}/", writer)

        self.assertIn(deleted.status_code, (200, 204), deleted.content[:500])

        category.refresh_from_db()

        self.assertTrue(category.is_deleted)
        self.assertEqual(category.deleted_by, writer)

        after = self.call("get", f"{ENDPOINT}?search={code}", writer)

        self.assertEqual(self.rows(after), [])

    def test_duplicate_code_returns_validation_error(self):
        writer = self.make_user(permissions=self.WRITE_PERMISSIONS)
        code = self.next_code()

        AssetCategoryService.create(data={"code": code, "name": "Existing"})

        response = self.call(
            "post",
            ENDPOINT,
            writer,
            {"code": code.lower(), "name": "Duplicate"},
        )

        self.assertEqual(response.status_code, 400, response.content[:500])
        self.assertIn("code", response.content.decode())
        self.assertEqual(
            AssetCategory.objects.filter(code=code, is_deleted=False).count(),
            1,
        )

    def test_deleted_flag_cannot_be_written_through_the_api(self):
        writer = self.make_user(permissions=self.WRITE_PERMISSIONS)

        category = AssetCategoryService.create(
            data={"code": self.next_code(), "name": "Tablet"},
        )

        self.call(
            "patch",
            f"{ENDPOINT}{category.pk}/",
            writer,
            {"is_deleted": True, "deleted_at": "2026-01-01T00:00:00Z"},
        )

        category.refresh_from_db()

        self.assertFalse(category.is_deleted)
        self.assertIsNone(category.deleted_at)

    def test_read_is_open_but_writes_need_model_permission(self):
        reader = self.make_user()

        category = AssetCategoryService.create(
            data={"code": self.next_code(), "name": "Mobile Phone"},
        )

        listed = self.call("get", f"{ENDPOINT}?search={category.code}", reader)

        self.assertEqual(listed.status_code, 200)
        self.assertEqual(len(self.rows(listed)), 1)

        attempts = [
            ("post", ENDPOINT, {"code": self.next_code(), "name": "X"}),
            ("patch", f"{ENDPOINT}{category.pk}/", {"name": "Changed"}),
            ("delete", f"{ENDPOINT}{category.pk}/", None),
        ]

        for method, path, payload in attempts:
            with self.subTest(method=method):
                response = self.call(method, path, reader, payload)

                self.assertEqual(response.status_code, 403)

        category.refresh_from_db()

        self.assertEqual(category.name, "Mobile Phone")
        self.assertFalse(category.is_deleted)

    def test_lookup_offers_only_active_categories(self):
        user = self.make_user()

        active = AssetCategoryService.create(
            data={"code": self.next_code("LKA"), "name": "Survey Equipment"},
        )
        inactive = AssetCategoryService.create(
            data={
                "code": self.next_code("LKI"),
                "name": "Old Equipment",
                "is_active": False,
            },
        )
        deleted = AssetCategoryService.create(
            data={"code": self.next_code("LKD"), "name": "Gone"},
        )
        AssetCategoryService.soft_delete(instance=deleted)

        response = self.call("get", f"{LOOKUP}?page_size=1000", user)

        self.assertEqual(response.status_code, 200, response.content[:500])

        # Bentuk lookup `{value, label}` — value adalah id.
        offered = {row["value"] for row in self.body(response)["results"]}

        self.assertIn(active.pk, offered)
        self.assertNotIn(inactive.pk, offered)
        self.assertNotIn(deleted.pk, offered)

    def test_ui_schema_is_served_for_the_generator(self):
        user = self.make_user()

        response = self.call("get", f"{ENDPOINT}ui-schema/", user)

        self.assertEqual(response.status_code, 200, response.content[:500])

        schema = self.body(response)
        schema = schema.get("data", schema)

        self.assertEqual(schema["endpoint"], ENDPOINT)

        # Schema gabungan: field deklaratif + hasil introspeksi
        # serializer (id, timestamp). Yang dikunci: seluruh field form
        # ada, dan kolom penghapusan tidak pernah sampai ke generator.
        fields = set(schema["fields"])

        self.assertLessEqual(
            {"code", "name", "description", "sort_order", "is_active"},
            fields,
        )
        self.assertFalse(
            fields & {"is_deleted", "deleted_at", "deleted_by"},
        )
