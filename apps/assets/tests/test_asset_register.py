"""
ASSET-2 — Asset Register, aktivasi, custody awal, dan riwayat kondisi.

Kontraknya `docs/claude/assets.md` §5, §6, §8, §12, §16, §17. Yang
dikunci di sini:

* aset lahir DRAFT dengan kode AST dari service; kode dan company tidak
  pernah berubah;
* lokasi/fasilitas milik company aset, fasilitas di lokasi aset;
* serial opsional kecuali kategori mewajibkan; unik per company tanpa
  membedakan huruf, company lain boleh sama;
* aktivasi = ACTIVE + tepat satu custody STORAGE + log kondisi, satu
  transaksi; aktivasi kedua ditolak;
* sesudah aktif, lokasi/fasilitas/kategori/kondisi tidak bisa disunting
  lewat jalur update — custody adalah authority-nya;
* tidak ada jalur API yang menulis custody;
* riwayat kondisi append-only.
"""

from __future__ import annotations

import json

from unittest import mock

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import override_settings
from django.urls import Resolver404, resolve
from django.utils import timezone
from django_tenants.test.client import TenantClient
from apps.accounts.jwt import TenantRefreshToken as RefreshToken

from apps.assets.models import (
    Asset,
    AssetCondition,
    AssetConditionLog,
    AssetCustody,
    AssetStatus,
    ConditionSource,
    CustodyType,
)
from apps.assets.services import (
    AssetCategoryService,
    AssetCustodyService,
    AssetService,
)

from .base import AssetsTestCase


ENDPOINT = "/api/assets/assets/"
LOOKUP = "/api/assets/lookup/assets/"


class AssetCategoryRulesTests(AssetsTestCase):
    def test_serial_requirement_defaults_to_off(self):
        category = AssetCategoryService.create(
            data={"code": self.next_code(), "name": "Furniture"},
        )

        self.assertFalse(category.requires_serial_number)

    def test_category_in_use_cannot_be_deleted_until_its_assets_are(self):
        category = self.make_category()
        asset = self.make_asset(category=category)

        with self.assertRaises(ValidationError) as caught:
            AssetCategoryService.soft_delete(instance=category)

        self.assertIn("category", caught.exception.message_dict)

        category.refresh_from_db()
        self.assertFalse(category.is_deleted)

        AssetService.soft_delete(instance=asset)
        AssetCategoryService.soft_delete(instance=category)

        category.refresh_from_db()
        self.assertTrue(category.is_deleted)


class AssetRegisterTests(AssetsTestCase):
    def test_create_is_draft_with_generated_code_and_no_custody(self):
        first = self.make_asset()
        second = self.make_asset()

        self.assertEqual(first.status, AssetStatus.DRAFT)
        self.assertTrue(first.asset_code.startswith("AST-"))
        self.assertNotEqual(first.asset_code, second.asset_code)
        self.assertIsNone(first.current_custody)
        self.assertFalse(AssetCustody.objects.filter(asset=first).exists())
        self.assertFalse(AssetConditionLog.objects.filter(asset=first).exists())

    def test_client_cannot_supply_system_fields(self):
        for field_name, value in (
            ("asset_code", "MY-OWN-CODE"),
            ("status", AssetStatus.ACTIVE),
        ):
            with self.subTest(field=field_name):
                with self.assertRaises(ValidationError) as caught:
                    self.make_asset(**{field_name: value})

                self.assertIn(field_name, caught.exception.message_dict)

    def test_code_and_company_never_change(self):
        asset = self.make_asset()

        for data in (
            {"asset_code": "AST-999999"},
            {"company": self.company_b, "location": self.loc_b1},
        ):
            with self.subTest(data=list(data)):
                with self.assertRaises(ValidationError):
                    AssetService.update(instance=asset, data=dict(data))

        asset.refresh_from_db()
        self.assertEqual(asset.company, self.company_a)

    def test_location_and_facility_must_belong_to_the_asset(self):
        cases = [
            ({"location": self.loc_b1}, "location"),
            ({"location": self.loc_a1, "facility": self.fac_a2}, "facility"),
        ]

        for extra, field_name in cases:
            with self.subTest(field=field_name, extra=list(extra)):
                with self.assertRaises(ValidationError) as caught:
                    self.make_asset(**extra)

                self.assertIn(field_name, caught.exception.message_dict)

        asset = self.make_asset(location=self.loc_a2, facility=self.fac_a2)
        self.assertEqual(asset.facility, self.fac_a2)

    def test_inactive_category_cannot_be_used(self):
        category = self.make_category(is_active=False)

        with self.assertRaises(ValidationError) as caught:
            self.make_asset(category=category)

        self.assertIn("category", caught.exception.message_dict)

    def test_serial_is_unique_per_company_ignoring_case_and_spaces(self):
        self.make_asset(serial_number="SN-ABC-1")

        with self.assertRaises(ValidationError) as caught:
            self.make_asset(serial_number="  sn-abc-1 ")

        self.assertIn("serial_number", caught.exception.message_dict)

        other = self.make_asset(company=self.company_b, serial_number="sn-abc-1")
        self.assertEqual(other.serial_number, "sn-abc-1")

    def test_blank_serials_do_not_collide(self):
        first = self.make_asset(serial_number="   ")
        second = self.make_asset(serial_number="")

        self.assertEqual(first.serial_number, "")
        self.assertEqual(second.serial_number, "")

    def test_deleted_draft_frees_its_serial(self):
        draft = self.make_asset(serial_number="SN-REUSE-1")
        AssetService.soft_delete(instance=draft)

        again = self.make_asset(serial_number="SN-REUSE-1")
        self.assertEqual(again.serial_number, "SN-REUSE-1")

    def test_tag_is_unique_per_company(self):
        self.make_asset(tag_number="TAG-001")

        with self.assertRaises(ValidationError) as caught:
            self.make_asset(tag_number="tag-001")

        self.assertIn("tag_number", caught.exception.message_dict)

    def test_database_backs_serial_uniqueness(self):
        # Penjaga terakhir kalau service dilewati.
        first = self.make_asset(serial_number="SN-DB-1")
        second = self.make_asset()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Asset.objects.filter(pk=second.pk).update(serial_number="sn-db-1")

        self.assertEqual(first.serial_number, "SN-DB-1")

    def test_only_drafts_can_be_deleted(self):
        draft = self.make_asset()
        AssetService.soft_delete(instance=draft)

        draft.refresh_from_db()
        self.assertTrue(draft.is_deleted)

        active = AssetService.activate(asset=self.make_asset())

        with self.assertRaises(ValidationError):
            AssetService.soft_delete(instance=active)

        active.refresh_from_db()
        self.assertFalse(active.is_deleted)


class AssetActivationTests(AssetsTestCase):
    def test_activation_opens_exactly_one_storage_custody(self):
        asset = self.make_asset(
            location=self.loc_a2,
            facility=self.fac_a2,
            condition=AssetCondition.FAIR,
        )

        activated = AssetService.activate(asset=asset)

        custodies = AssetCustody.objects.filter(asset=asset)
        self.assertEqual(custodies.count(), 1)

        custody = custodies.get()

        self.assertEqual(activated.status, AssetStatus.ACTIVE)
        self.assertEqual(activated.current_custody, custody)
        self.assertIsNotNone(activated.activated_at)

        self.assertEqual(custody.custody_type, CustodyType.STORAGE)
        self.assertEqual(custody.company, self.company_a)
        self.assertEqual(custody.location, self.loc_a2)
        self.assertEqual(custody.facility, self.fac_a2)
        self.assertIsNone(custody.ended_on)
        self.assertEqual(custody.start_condition, AssetCondition.FAIR)
        self.assertEqual(custody.opened_by_type, "registration")

        log = AssetConditionLog.objects.get(asset=asset)
        self.assertEqual(log.source, ConditionSource.REGISTRATION)
        self.assertEqual(log.previous_condition, "")
        self.assertEqual(log.new_condition, AssetCondition.FAIR)

        self.assertEqual(AssetCustodyService.integrity_issues(), [])

    def test_serial_optional_category_activates_without_serial(self):
        asset = self.make_asset(category=self.make_category())

        self.assertEqual(
            AssetService.activate(asset=asset).status,
            AssetStatus.ACTIVE,
        )

    def test_serial_required_category_blocks_activation_without_serial(self):
        category = self.make_category(requires_serial_number=True)
        asset = self.make_asset(category=category)

        with self.assertRaises(ValidationError) as caught:
            AssetService.activate(asset=asset)

        self.assertIn("serial_number", caught.exception.message_dict)

        asset.refresh_from_db()
        self.assertEqual(asset.status, AssetStatus.DRAFT)
        self.assertFalse(AssetCustody.objects.filter(asset=asset).exists())

        AssetService.update(instance=asset, data={"serial_number": "SN-REQ-1"})

        self.assertEqual(
            AssetService.activate(asset=asset).status,
            AssetStatus.ACTIVE,
        )

    def test_inactive_category_blocks_activation(self):
        category = self.make_category()
        asset = self.make_asset(category=category)

        AssetCategoryService.update(instance=category, data={"is_active": False})

        with self.assertRaises(ValidationError):
            AssetService.activate(asset=asset)

        asset.refresh_from_db()
        self.assertEqual(asset.status, AssetStatus.DRAFT)

    def test_activation_is_atomic(self):
        asset = self.make_asset()

        target = "apps.assets.services.operations.asset.AssetConditionLog.objects.create"

        with mock.patch(target, side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                AssetService.activate(asset=asset)

        asset.refresh_from_db()
        self.assertEqual(asset.status, AssetStatus.DRAFT)
        self.assertIsNone(asset.current_custody)
        self.assertFalse(AssetCustody.objects.filter(asset=asset).exists())

    def test_second_activation_is_rejected_even_from_a_stale_object(self):
        asset = self.make_asset()
        stale = Asset.objects.get(pk=asset.pk)

        AssetService.activate(asset=asset)

        # `stale` masih DRAFT di memori; service membaca ulang di dalam
        # kunci, jadi ia tidak membuka custody kedua.
        self.assertEqual(stale.status, AssetStatus.DRAFT)

        with self.assertRaises(ValidationError):
            AssetService.activate(asset=stale)

        self.assertEqual(AssetCustody.objects.filter(asset=asset).count(), 1)

    def test_active_asset_placement_and_condition_are_locked(self):
        asset = AssetService.activate(
            asset=self.make_asset(location=self.loc_a1),
        )

        locked = [
            {"location": self.loc_a2},
            {"facility": self.fac_a1},
            {"category": self.make_category()},
            {"condition": AssetCondition.DAMAGED},
        ]

        for data in locked:
            with self.subTest(field=list(data)):
                with self.assertRaises(ValidationError):
                    AssetService.update(instance=asset, data=dict(data))

        asset.refresh_from_db()
        self.assertEqual(asset.location, self.loc_a1)
        self.assertEqual(asset.current_custody.location, self.loc_a1)

        renamed = AssetService.update(
            instance=asset,
            data={"name": "Laptop Dell", "serial_number": "SN-LATE-1"},
        )
        self.assertEqual(renamed.name, "Laptop Dell")

    def test_required_serial_cannot_be_blanked_after_activation(self):
        category = self.make_category(requires_serial_number=True)
        asset = AssetService.activate(
            asset=self.make_asset(category=category, serial_number="SN-KEEP-1"),
        )

        with self.assertRaises(ValidationError):
            AssetService.update(instance=asset, data={"serial_number": "  "})


class CustodyInvariantTests(AssetsTestCase):
    def test_database_allows_only_one_open_custody_per_asset(self):
        asset = AssetService.activate(asset=self.make_asset())

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                AssetCustody.objects.create(
                    asset=asset,
                    company=asset.company,
                    custody_type=CustodyType.STORAGE,
                    location=asset.location,
                    started_on=timezone.localdate(),
                    start_condition=asset.condition,
                    opened_by_type="test",
                    opened_by_id="1",
                )

    def test_database_rejects_non_storage_custody_until_asset_3(self):
        asset = self.make_asset()

        for custody_type in (CustodyType.EMPLOYEE, CustodyType.ORGANIZATION):
            with self.subTest(custody_type=custody_type):
                with self.assertRaises(IntegrityError):
                    with transaction.atomic():
                        AssetCustody.objects.create(
                            asset=asset,
                            company=asset.company,
                            custody_type=custody_type,
                            location=asset.location,
                            started_on=timezone.localdate(),
                            start_condition=asset.condition,
                            opened_by_type="test",
                            opened_by_id="1",
                        )

    def test_database_rejects_active_asset_without_custody(self):
        asset = self.make_asset()

        with self.assertRaises(IntegrityError):
            with transaction.atomic():
                Asset.objects.filter(pk=asset.pk).update(status=AssetStatus.ACTIVE)


class AssetConditionTests(AssetsTestCase):
    def test_inspection_appends_history_and_updates_the_asset(self):
        user = self.make_user()
        asset = AssetService.activate(asset=self.make_asset())

        AssetService.record_condition(
            asset=asset,
            condition=AssetCondition.DAMAGED,
            note=" layar retak ",
            user=user,
        )
        AssetService.record_condition(
            asset=asset,
            condition=AssetCondition.DAMAGED,
            user=user,
        )

        asset.refresh_from_db()
        self.assertEqual(asset.condition, AssetCondition.DAMAGED)

        logs = list(
            AssetConditionLog.objects
            .filter(asset=asset, source=ConditionSource.INSPECTION)
            .order_by("id")
        )

        self.assertEqual(len(logs), 2)
        self.assertEqual(logs[0].previous_condition, AssetCondition.GOOD)
        self.assertEqual(logs[0].new_condition, AssetCondition.DAMAGED)
        self.assertEqual(logs[0].note, "layar retak")
        self.assertEqual(logs[0].recorded_by, user)
        self.assertEqual(logs[1].previous_condition, AssetCondition.DAMAGED)

    def test_draft_and_unknown_conditions_are_rejected(self):
        draft = self.make_asset()

        with self.assertRaises(ValidationError):
            AssetService.record_condition(
                asset=draft,
                condition=AssetCondition.FAIR,
            )

        active = AssetService.activate(asset=self.make_asset())

        with self.assertRaises(ValidationError):
            AssetService.record_condition(asset=active, condition="BROKEN")

    def test_history_cannot_be_changed_or_deleted(self):
        asset = AssetService.activate(asset=self.make_asset())
        log = AssetConditionLog.objects.get(asset=asset)

        log.note = "rewritten"

        with self.assertRaises(ValueError):
            log.save()

        with self.assertRaises(ValueError):
            log.delete()

        log.refresh_from_db()
        self.assertEqual(log.note, "")


@override_settings(
    ENFORCE_MODEL_PERMISSIONS=True,
    ENFORCE_VIEW_PERMISSIONS=True,
)
class AssetApiTests(AssetsTestCase):
    ALL = ("view_asset", "add_asset", "change_asset", "delete_asset")

    def setUp(self):
        super().setUp()

        self.http = TenantClient(self.tenant)

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

    def ids(self, response) -> set[int]:
        self.assertEqual(response.status_code, 200, response.content[:500])

        return {row["id"] for row in self.body(response)["data"]}

    # ------------------------------------------------------------------

    def test_register_and_activate_through_the_api(self):
        writer = self.make_user(permissions=self.ALL)
        category = self.make_category()

        created = self.call("post", ENDPOINT, writer, {
            "company": self.company_a.pk,
            "category": category.pk,
            "location": self.loc_a1.pk,
            "facility": self.fac_a1.pk,
            "name": " Radio HT ",
            "serial_number": " sn-ht-1 ",
            # Diabaikan: read-only di serializer.
            "asset_code": "HACK-1",
            "status": AssetStatus.ACTIVE,
            "current_custody": 1,
        })

        self.assertEqual(created.status_code, 201, created.content[:500])

        asset = Asset.objects.get(company=self.company_a, serial_number="sn-ht-1")

        self.assertTrue(asset.asset_code.startswith("AST-"))
        self.assertEqual(asset.status, AssetStatus.DRAFT)
        self.assertEqual(asset.name, "Radio HT")
        self.assertIsNone(asset.current_custody)
        self.assertEqual(asset.created_by, writer)

        activated = self.call("post", f"{ENDPOINT}{asset.pk}/activate/", writer)

        self.assertEqual(activated.status_code, 200, activated.content[:500])
        self.assertEqual(
            self.body(activated)["data"]["custody_type"],
            CustodyType.STORAGE,
        )

        again = self.call("post", f"{ENDPOINT}{asset.pk}/activate/", writer)
        self.assertEqual(again.status_code, 400)
        self.assertEqual(AssetCustody.objects.filter(asset=asset).count(), 1)

        moved = self.call("patch", f"{ENDPOINT}{asset.pk}/", writer, {
            "location": self.loc_a2.pk,
        })
        self.assertEqual(moved.status_code, 400, moved.content[:500])

        relabelled = self.call("patch", f"{ENDPOINT}{asset.pk}/", writer, {
            "status": AssetStatus.DRAFT,
            "asset_code": "HACK-2",
            "name": "Radio HT Motorola",
        })
        self.assertEqual(relabelled.status_code, 200, relabelled.content[:500])

        asset.refresh_from_db()
        self.assertEqual(asset.status, AssetStatus.ACTIVE)
        self.assertTrue(asset.asset_code.startswith("AST-"))
        self.assertEqual(asset.name, "Radio HT Motorola")
        self.assertEqual(asset.location, self.loc_a1)

        inspected = self.call(
            "post",
            f"{ENDPOINT}{asset.pk}/record-condition/",
            writer,
            {"condition": AssetCondition.FAIR, "note": "baterai lemah"},
        )
        self.assertEqual(inspected.status_code, 200, inspected.content[:500])

        asset.refresh_from_db()
        self.assertEqual(asset.condition, AssetCondition.FAIR)

        deleted = self.call("delete", f"{ENDPOINT}{asset.pk}/", writer)
        self.assertEqual(deleted.status_code, 400, deleted.content[:500])

    def test_there_is_no_public_custody_write_endpoint(self):
        for path in (
            "/api/assets/custodies/",
            "/api/assets/asset-custodies/",
        ):
            with self.subTest(path=path):
                with self.assertRaises(Resolver404):
                    resolve(path)

    def test_permissions(self):
        asset = self.make_asset()

        nobody = self.make_user()
        viewer = self.make_user(permissions=("view_asset",))

        self.assertEqual(self.call("get", ENDPOINT, nobody).status_code, 403)
        self.assertIn(asset.pk, self.ids(self.call("get", ENDPOINT, viewer)))

        created = self.call("post", ENDPOINT, viewer, {
            "company": self.company_a.pk,
            "category": self.make_category().pk,
            "location": self.loc_a1.pk,
            "name": "X",
        })
        self.assertEqual(created.status_code, 403)

        activated = self.call("post", f"{ENDPOINT}{asset.pk}/activate/", viewer)
        self.assertIn(activated.status_code, (403, 404))

        asset.refresh_from_db()
        self.assertEqual(asset.status, AssetStatus.DRAFT)

    def test_data_scope_follows_location_including_drafts(self):
        at_a1_draft = self.make_asset(location=self.loc_a1)
        at_a1_active = AssetService.activate(
            asset=self.make_asset(location=self.loc_a1),
        )
        at_a2 = self.make_asset(location=self.loc_a2)
        at_b1 = self.make_asset(company=self.company_b)

        scoped = self.make_user(
            permissions=("view_asset",),
            authorities=[("location", self.loc_a1.pk)],
        )

        visible = self.ids(self.call("get", f"{ENDPOINT}?page_size=500", scoped))

        self.assertIn(at_a1_draft.pk, visible)
        self.assertIn(at_a1_active.pk, visible)
        self.assertNotIn(at_a2.pk, visible)
        self.assertNotIn(at_b1.pk, visible)

    def test_lookup_offers_only_active_assets_in_scope(self):
        active = AssetService.activate(asset=self.make_asset(location=self.loc_a1))
        draft = self.make_asset(location=self.loc_a1)
        elsewhere = AssetService.activate(
            asset=self.make_asset(location=self.loc_a2),
        )

        scoped = self.make_user(
            permissions=("view_asset",),
            authorities=[("location", self.loc_a1.pk)],
        )

        response = self.call("get", f"{LOOKUP}?page_size=1000", scoped)
        self.assertEqual(response.status_code, 200, response.content[:500])

        offered = {row["value"] for row in self.body(response)["results"]}

        self.assertIn(active.pk, offered)
        self.assertNotIn(draft.pk, offered)
        self.assertNotIn(elsewhere.pk, offered)

    def test_ui_schema_declares_register_fields_and_actions(self):
        viewer = self.make_user(permissions=("view_asset",))

        response = self.call("get", f"{ENDPOINT}ui-schema/", viewer)
        self.assertEqual(response.status_code, 200, response.content[:500])

        schema = self.body(response)
        schema = schema.get("data", schema)

        self.assertEqual(schema["endpoint"], ENDPOINT)
        self.assertLessEqual(
            {
                "asset_code", "company", "category", "name", "serial_number",
                "condition", "status", "location", "facility",
            },
            set(schema["fields"]),
        )
        self.assertFalse(
            set(schema["fields"]) & {"is_deleted", "deleted_at", "deleted_by"},
        )
        self.assertLessEqual(
            {"activate", "record_condition"},
            {item["key"] for item in schema.get("actions", [])},
        )
